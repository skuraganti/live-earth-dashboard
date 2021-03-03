"""SQLite persistence for events, weather, watches, alerts, and source history."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from functools import wraps
from pathlib import Path

from app.parse import parse_iso_ms, parse_source
from app.sources import (
    CLOCK_SKEW_MS,
    FRESH_MS,
    HISTORY_LIMIT,
    MAX_BODY_BYTES,
    MAX_EVENTS_RETURNED,
    SOURCE_URLS,
    USGS_ID,
    WATCH_RECENCY_MS,
    load_manifest,
    seed_filename,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    depth_km REAL NOT NULL,
    mag REAL,
    type TEXT NOT NULL DEFAULT 'unknown',
    place TEXT,
    time INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    status TEXT,
    source_url TEXT,
    source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weather (
    station TEXT NOT NULL,
    time INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    temperature_c REAL,
    wind_kmh REAL,
    captured_at INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    PRIMARY KEY (station, time)
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    last_attempt INTEGER,
    last_success INTEGER,
    observed_at INTEGER,
    error TEXT,
    record_count INTEGER
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    attempted_at INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    sha256 TEXT,
    record_count INTEGER,
    error TEXT,
    observed_at INTEGER
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    retrieved_at INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    observed_at INTEGER,
    seeded INTEGER NOT NULL,
    raw_body BLOB
);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    radius_km REAL NOT NULL,
    min_mag REAL,
    max_temperature_c REAL,
    max_wind_kmh REAL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    message TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    UNIQUE (watch_id, kind, evidence_id)
);
"""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return guarded


class Store:
    def __init__(self, db_path: str, seed_dir: Path | None, now_ms):
        self.db_path = db_path
        self.seed_dir = seed_dir
        self.now_ms = now_ms
        self.lock = threading.RLock()
        self.closed = False
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        for table, column, definition in (
            ("events", "type", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("weather", "captured_at", "INTEGER NOT NULL DEFAULT 0"),
            ("snapshots", "raw_body", "BLOB"),
        ):
            if column not in {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self.conn.commit()

    @serialized
    def close(self) -> None:
        if not self.closed:
            self.conn.close()
            self.closed = True

    def _trim(self, table: str, source_id: str) -> None:
        self.conn.execute(
            f"""DELETE FROM {table} WHERE source_id=? AND id NOT IN (
                SELECT id FROM {table} WHERE source_id=? ORDER BY id DESC LIMIT ?
            )""",
            (source_id, source_id, HISTORY_LIMIT),
        )

    @serialized
    def seed(self) -> bool:
        if self.seed_dir is None:
            return bool(self.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone())
        manifest_path = self.seed_dir / "manifest.json"
        if not manifest_path.is_file():
            return bool(self.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone())
        manifest = load_manifest(self.seed_dir)
        applied = bool(self.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone())
        for source_id, item in manifest.items():
            if self.conn.execute(
                "SELECT 1 FROM sources WHERE id=? AND last_success IS NOT NULL", (source_id,)
            ).fetchone():
                continue
            filename = seed_filename(source_id)
            path = self.seed_dir / filename
            if not path.is_file():
                continue
            if path.stat().st_size > MAX_BODY_BYTES:
                raise ValueError(f"seed exceeds size limit: {filename}")
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            recorded = item.get("sha256")
            if isinstance(recorded, str) and recorded and recorded != digest:
                raise ValueError(f"seed checksum mismatch for {filename}")
            retrieved = parse_iso_ms(item.get("retrieved_at"), "retrieved")
            self.apply_payload(
                source_id,
                item["url"],
                json.loads(body.decode("utf-8")),
                digest,
                retrieved,
                seeded=True,
                raw_bytes=body,
            )
            applied = True
        return applied

    @serialized
    def apply_payload(
        self,
        source_id: str,
        url: str,
        body: object,
        digest: str,
        retrieved_at: int,
        seeded: bool,
        raw_bytes: bytes | None = None,
    ) -> dict:
        parsed = parse_source(source_id, body)
        observed = parsed["generated"]
        if parsed["weather"]:
            observed = max(item["time"] for item in parsed["weather"])
        with self.lock:
            try:
                self.conn.execute("BEGIN")
                kept = 0
                if source_id == USGS_ID:
                    for event in parsed["events"]:
                        row = self.conn.execute(
                            "SELECT updated FROM events WHERE id=?", (event["id"],)
                        ).fetchone()
                        if row is not None and int(row["updated"]) > event["updated"]:
                            continue
                        self.conn.execute(
                            """INSERT INTO events
                            (id,lat,lon,depth_km,mag,type,place,time,updated,status,source_url,source_sha256)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET
                              lat=excluded.lat, lon=excluded.lon, depth_km=excluded.depth_km,
                              mag=excluded.mag, type=excluded.type,
                              place=excluded.place, time=excluded.time,
                              updated=excluded.updated, status=excluded.status,
                              source_url=excluded.source_url, source_sha256=excluded.source_sha256
                            WHERE excluded.updated>=events.updated""",
                            (
                                event["id"],
                                event["lat"],
                                event["lon"],
                                event["depth_km"],
                                event["mag"],
                                event["type"],
                                event["place"],
                                event["time"],
                                event["updated"],
                                event["status"],
                                event["source_url"],
                                digest,
                            ),
                        )
                        kept += 1
                else:
                    for report in parsed["weather"]:
                        self.conn.execute(
                            """INSERT INTO weather
                            (station,time,lat,lon,temperature_c,wind_kmh,description,source_url,source_sha256,captured_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(station,time) DO UPDATE SET
                              lat=excluded.lat, lon=excluded.lon,
                              temperature_c=excluded.temperature_c, wind_kmh=excluded.wind_kmh,
                              description=excluded.description, source_url=excluded.source_url,
                              source_sha256=excluded.source_sha256, captured_at=excluded.captured_at
                            WHERE excluded.captured_at>=weather.captured_at""",
                            (
                                report["station"],
                                report["time"],
                                report["lat"],
                                report["lon"],
                                report["temperature_c"],
                                report["wind_kmh"],
                                report["description"],
                                url,
                                digest,
                                retrieved_at,
                            ),
                        )
                        kept += 1
                count = len(parsed["events"] or parsed["weather"])
                self.conn.execute(
                    """INSERT INTO sources
                    (id,url,last_attempt,last_success,observed_at,error,record_count)
                    VALUES (?,?,?,?,?,NULL,?)
                    ON CONFLICT(id) DO UPDATE SET
                      url=excluded.url, last_attempt=excluded.last_attempt,
                      last_success=excluded.last_success, observed_at=excluded.observed_at,
                      error=NULL, record_count=excluded.record_count
                    WHERE excluded.last_success>=COALESCE(sources.last_success,0)""",
                    (source_id, url, retrieved_at, retrieved_at, observed, count),
                )
                self.conn.execute(
                    """INSERT INTO attempts
                    (source_id,attempted_at,ok,sha256,record_count,error,observed_at)
                    VALUES (?,?,1,?,?,NULL,?)""",
                    (source_id, retrieved_at, digest, count, observed),
                )
                self.conn.execute(
                    """INSERT INTO snapshots
                    (source_id,url,retrieved_at,sha256,record_count,observed_at,seeded,raw_body)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (source_id, url, retrieved_at, digest, count, observed, int(seeded), raw_bytes),
                )
                self._trim("attempts", source_id)
                self._trim("snapshots", source_id)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        if not seeded:
            for watch in self.watches():
                self.evaluate_watch(watch, self.now_ms())
        return {"ok": True, "record_count": count, "applied": kept, "observed_at": observed}

    @serialized
    def record_failure(self, source_id: str, url: str, message: str, attempted_at: int) -> None:
        safe = message[:200]
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.execute(
                """INSERT INTO sources
                    (id,url,last_attempt,last_success,observed_at,error,record_count)
                VALUES (?,?,?,NULL,NULL,?,NULL)
                ON CONFLICT(id) DO UPDATE SET
                  url=excluded.url, last_attempt=excluded.last_attempt, error=excluded.error""",
                (source_id, url, attempted_at, safe),
            )
            self.conn.execute(
                """INSERT INTO attempts
                (source_id,attempted_at,ok,sha256,record_count,error,observed_at)
                VALUES (?,?,0,NULL,NULL,?,NULL)""",
                (source_id, attempted_at, safe),
            )
            self._trim("attempts", source_id)
            self.conn.commit()

    @serialized
    def source_rows(self, now: int) -> list[dict]:
        stored = {r["id"]: r for r in self.conn.execute("SELECT * FROM sources").fetchall()}
        rows = [
            stored.get(
                source_id,
                {
                    "id": source_id,
                    "url": url,
                    "last_attempt": None,
                    "last_success": None,
                    "observed_at": None,
                    "error": None,
                },
            )
            for source_id, url in sorted(SOURCE_URLS.items())
        ]
        result = []
        for row in rows:
            observed = row["observed_at"]
            error = row["error"]
            if observed is None:
                state = "error" if error else "missing"
                age = None
            else:
                age_ms = now - int(observed)
                age = age_ms / 1000
                if age_ms < -CLOCK_SKEW_MS:
                    state = "clock_skew"
                elif error:
                    state = "error"
                elif age_ms <= FRESH_MS:
                    state = "fresh"
                else:
                    state = "stale"
            result.append(
                {
                    "id": row["id"],
                    "url": row["url"],
                    "last_attempt": row["last_attempt"],
                    "last_success": row["last_success"],
                    "observed_at": observed,
                    "age_seconds": age,
                    "state": state,
                    "error": error,
                }
            )
        return result

    @serialized
    def state(self, until: int | None, min_mag: float | None, poll_seconds: int) -> dict:
        now = self.now_ms()
        bounds = self.conn.execute(
            "SELECT MIN(time) AS start, MAX(time) AS end FROM events"
        ).fetchone()
        clauses = []
        params: list = []
        if until is not None:
            clauses.append("time<=?")
            params.append(until)
        if min_mag is not None:
            clauses.append("mag IS NOT NULL AND mag>=?")
            params.append(min_mag)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.conn.execute(f"SELECT COUNT(*) AS n FROM events{where}", params).fetchone()[
            "n"
        ]
        rows = self.conn.execute(
            f"""SELECT id,lat,lon,depth_km,mag,type,place,time,updated,status,
                   source_url,source_sha256
            FROM events{where} ORDER BY time DESC, id LIMIT ?""",
            [*params, MAX_EVENTS_RETURNED],
        ).fetchall()
        events = [dict(row) for row in rows]
        weather = self._weather(until)
        sources = self.source_rows(now)
        mode = "replay" if until is not None else "current"
        return {
            "mode": mode,
            "until": until,
            "range": {"start": bounds["start"], "end": bounds["end"]},
            "events": events,
            "weather": weather,
            "sources": sources,
            "counts": {"events": total, "weather": len(weather)},
            "truncated": total > len(events),
            "poll_seconds": poll_seconds,
        }

    def _weather(self, until: int | None) -> list[dict]:
        if until is None:
            rows = self.conn.execute(
                """SELECT station,lat,lon,time,temperature_c,wind_kmh,description,
                   source_url,source_sha256
                FROM weather w WHERE time=(SELECT MAX(time) FROM weather WHERE station=w.station)
                ORDER BY station"""
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT station,lat,lon,time,temperature_c,wind_kmh,description,
                   source_url,source_sha256
                FROM weather w
                WHERE time=(SELECT MAX(time) FROM weather WHERE station=w.station AND time<=?)
                ORDER BY station""",
                (until,),
            ).fetchall()
        return [dict(row) for row in rows]

    @serialized
    def snapshots(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id,source_id,url,retrieved_at,sha256,record_count,observed_at,seeded,
                   (raw_body IS NOT NULL) AS raw_preserved
            FROM snapshots ORDER BY id DESC LIMIT 128"""
        ).fetchall()
        return [dict(row) for row in rows]

    @serialized
    def create_watch(self, fields: dict, now: int) -> dict:
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO watches
                (name,lat,lon,radius_km,min_mag,max_temperature_c,max_wind_kmh)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    fields["name"],
                    fields["lat"],
                    fields["lon"],
                    fields["radius_km"],
                    fields["min_mag"],
                    fields["max_temperature_c"],
                    fields["max_wind_kmh"],
                ),
            )
            watch_id = int(cur.lastrowid)
            self.conn.commit()
        watch = self.watch(watch_id)
        self.evaluate_watch(watch, now)
        return watch

    @serialized
    def watch(self, watch_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
        if row is None:
            raise KeyError(watch_id)
        return dict(row)

    @serialized
    def watches(self) -> list[dict]:
        return [
            dict(row) for row in self.conn.execute("SELECT * FROM watches ORDER BY id").fetchall()
        ]

    @serialized
    def delete_watch(self, watch_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
            self.conn.execute("DELETE FROM alerts WHERE watch_id=?", (watch_id,))
            self.conn.commit()
            return cur.rowcount > 0

    @serialized
    def evaluate_watch(self, watch: dict, now: int) -> None:
        sources = {row["id"]: row for row in self.source_rows(now)}
        usgs = sources.get(USGS_ID)
        if usgs and usgs["state"] == "fresh" and watch["min_mag"] is not None:
            rows = self.conn.execute(
                """SELECT id,lat,lon,mag,place,time,source_url FROM events
                WHERE type='earthquake' AND time>=? AND time<=?
                  AND (? IS NULL OR (mag IS NOT NULL AND mag>=?))""",
                (now - WATCH_RECENCY_MS, now, watch["min_mag"], watch["min_mag"]),
            ).fetchall()
            for row in rows:
                distance = haversine_km(watch["lat"], watch["lon"], row["lat"], row["lon"])
                if distance <= watch["radius_km"] and (
                    watch["min_mag"] is None
                    or (row["mag"] is not None and row["mag"] >= watch["min_mag"])
                ):
                    self._alert(
                        watch,
                        "earthquake",
                        row["id"],
                        f"{row['place'] or row['id']} within {distance:.0f} km",
                        int(row["time"]),
                        now,
                        row["source_url"],
                    )
        for station, source in sources.items():
            if not station.startswith("weather-") or source["state"] != "fresh":
                continue
            report = self.conn.execute(
                """SELECT * FROM weather WHERE station=? ORDER BY time DESC LIMIT 1""",
                (station[8:],),
            ).fetchone()
            if report is None:
                continue
            if not 0 <= now - int(report["time"]) <= WATCH_RECENCY_MS:
                continue
            distance = haversine_km(watch["lat"], watch["lon"], report["lat"], report["lon"])
            if distance > watch["radius_km"]:
                continue
            temp_hit = (
                watch["max_temperature_c"] is not None
                and report["temperature_c"] is not None
                and report["temperature_c"] >= watch["max_temperature_c"]
            )
            wind_hit = (
                watch["max_wind_kmh"] is not None
                and report["wind_kmh"] is not None
                and report["wind_kmh"] >= watch["max_wind_kmh"]
            )
            if temp_hit:
                self._alert(
                    watch,
                    "temperature",
                    f"{report['station']}:{report['time']}",
                    f"{report['station']} {report['temperature_c']} C at {distance:.1f} km",
                    int(report["time"]),
                    now,
                    report["source_url"],
                )
            if wind_hit:
                self._alert(
                    watch,
                    "wind",
                    f"{report['station']}:{report['time']}",
                    f"{report['station']} {report['wind_kmh']} km/h at {distance:.1f} km",
                    int(report["time"]),
                    now,
                    report["source_url"],
                )

    def _alert(self, watch, kind, evidence_id, message, event_time, created_at, source_url) -> None:
        self.conn.execute(
            """INSERT INTO alerts
            (watch_id,kind,evidence_id,message,event_time,created_at,acknowledged,source_url)
            VALUES (?,?,?,?,?,?,0,?)
            ON CONFLICT(watch_id,kind,evidence_id) DO NOTHING""",
            (watch["id"], kind, evidence_id, message, event_time, created_at, source_url),
        )
        self.conn.commit()

    @serialized
    def alerts(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT a.id,a.watch_id,w.name AS watch_name,a.kind,a.evidence_id,a.message,
            a.event_time,a.created_at,a.acknowledged,a.source_url
            FROM alerts a JOIN watches w ON w.id=a.watch_id ORDER BY a.id"""
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["acknowledged"] = bool(item["acknowledged"])
            result.append(item)
        return result

    @serialized
    def acknowledge(self, alert_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
            self.conn.commit()
            return cur.rowcount > 0


def monotonic_ms() -> int:
    return int(time.time() * 1000)
