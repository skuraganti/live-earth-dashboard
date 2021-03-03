"""Acquire four original publisher JSON snapshots; run with python -m scripts.acquire."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.fetch import fetch_url
from app.parse import parse_source

SOURCES = (
    ("usgs", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"),
    ("weather-KSFO", "https://api.weather.gov/stations/KSFO/observations?limit=48"),
    ("weather-KSEA", "https://api.weather.gov/stations/KSEA/observations?limit=48"),
    ("weather-KNYC", "https://api.weather.gov/stations/KNYC/observations?limit=48"),
)


def acquire(output_dir: Path, *, replace: bool = False) -> list[dict]:
    targets = [output_dir / f"{name}.json" for name, _ in SOURCES]
    manifest_path = output_dir / "manifest.json"
    if not replace and any(path.exists() for path in [*targets, manifest_path]):
        raise FileExistsError("snapshot already exists; use --replace to replace frozen inputs")

    snapshots: list[tuple[Path, bytes]] = []
    manifest: list[dict] = []
    for (name, url), path in zip(SOURCES, targets, strict=True):
        result = fetch_url(url)
        retrieved_at = datetime.now(timezone.utc).isoformat()
        payload = json.loads(result.body.decode("utf-8"))
        parsed = parse_source(name, payload)
        item = {
            "name": name,
            "url": url,
            "retrieved_at": retrieved_at,
            "bytes": len(result.body),
            "sha256": result.sha256,
            "features": len(payload["features"]),
            "status": "acquired",
        }
        if name == "usgs":
            item["generated"] = parsed["generated"]
        else:
            reports = parsed["weather"]
            item["latest_observation"] = (
                datetime.fromtimestamp(
                    max(r["time"] for r in reports) / 1000, timezone.utc
                ).isoformat()
                if reports else None
            )
        snapshots.append((path, result.body))
        manifest.append(item)

    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "wb" if replace else "xb"
    for path, body in snapshots:
        with path.open(mode) as output:
            output.write(body)
    with manifest_path.open("w" if replace else "x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--replace", action="store_true", help="replace existing frozen snapshots")
    args = parser.parse_args()
    for item in acquire(args.output_dir, replace=args.replace):
        print(f"{item['name']}: {item['features']} records, sha256 {item['sha256']}")


if __name__ == "__main__":
    main()
