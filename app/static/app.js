'use strict';
const $ = id => document.getElementById(id);
const ui = {cutoff: null, minMag: 2.5, range: null, request: 0, evidenceRequest: 0, playing: null, events: [], watches: []};
const time = value => { if (value === null || value === undefined || value === '') return 'Not available'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? 'Invalid source timestamp' : date.toISOString().replace('T', ' ').slice(0, 19) + ' UTC'; };
const numeric = (value, places = 1) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(places) : 'Missing';
const element = (tag, text, className) => { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result; };
function notice(message, error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; $('notice').hidden = false; }
function button(text, action) { const result = element('button', text); result.type = 'button'; result.addEventListener('click', action); return result; }
function sourceLink(url) { const allowed = /^https:\/\/(earthquake\.usgs\.gov|api\.weather\.gov)\//; if (!allowed.test(url || '')) return element('span', 'Original source URL unavailable'); const link = element('a', 'Original publisher evidence'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link; }
async function api(path, method = 'GET', data) {
  const options = {method}; if (data !== undefined) { options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(data); }
  const response = await fetch('/api' + path, options); const body = await response.json();
  const reason = typeof body.error === 'string' ? body.error : body.detail; // this API returns {error}
  if (!response.ok) throw new Error(typeof reason === 'string' ? reason : 'Local request failed (' + response.status + ').');
  return body;
}
let map, earthquakes, stations, watchRings;
try {
  map = L.map('map', {worldCopyJump: true, minZoom: 1, maxZoom: 12}).setView([22, 0], 2);
  map.attributionControl.setPrefix('Leaflet 1.9.4 · BSD-2-Clause');
  map.attributionControl.addAttribution('USGS / NOAA NWS observations · Made with Natural Earth');
  earthquakes = L.layerGroup().addTo(map); stations = L.layerGroup().addTo(map); watchRings = L.layerGroup().addTo(map);
  fetch('/static/vendor/land.geojson').then(response => { if (!response.ok) throw Error('Local basemap missing'); return response.json(); }).then(data => L.geoJSON(data, {style: {color: '#a0b9be', weight: 0.7, fillColor: '#f1f4e9', fillOpacity: 1}, interactive: false}).addTo(map).bringToBack()).catch(error => notice(error.message + '; observation tables remain available.', true));
  map.on('click', event => { $('latitude').value = event.latlng.lat.toFixed(4); $('longitude').value = ((((event.latlng.lng + 180) % 360) + 360) % 360 - 180).toFixed(4); notice('Coordinates selected locally. Save a watch to evaluate nearby evidence.'); });
} catch (error) { notice('Map could not initialize. ' + error.message, true); }
function popup(title, lines, url) { const box = element('div'); box.append(element('h3', title)); for (const line of lines) box.append(element('p', line)); box.append(sourceLink(url)); return box; }
function renderSources(sources) {
  $('sources').replaceChildren();
  for (const source of sources) {
    const card = element('article', undefined, 'source ' + source.state); card.append(element('h3', source.id), element('strong', source.state), element('small', 'Provider: ' + time(source.observed_at)), element('small', 'Last retrieval: ' + time(source.last_success)), element('small', 'Age: ' + (source.age_seconds === null || source.age_seconds === undefined ? 'unknown' : Math.round(source.age_seconds / 60) + ' min')));
    if (source.error) card.append(element('small', 'Latest attempt: ' + source.error)); $('sources').append(card);
  }
  const fresh = sources.filter(source => source.state === 'fresh').length;
  $('connection').textContent = `${fresh}/${sources.length} sources fresh · current captured status`;
}
function renderState(data) {
  ui.range = data.range; ui.events = data.events || [];
  if (ui.range && ui.range.end > ui.range.start) $('timeline').disabled = false;
  $('mode').textContent = ui.cutoff === null ? 'CURRENT CAPTURE' : 'EVENT-TIME REPLAY';
  $('selected-time').textContent = time(ui.cutoff === null ? data.range?.end : ui.cutoff);
  $('playback-label').textContent = ui.cutoff === null ? 'Current captured catalog' : 'Replay cutoff: ' + time(ui.cutoff);
  renderSources(data.sources || []);
  earthquakes?.clearLayers(); stations?.clearLayers();
  $('events').replaceChildren();
  for (const event of [...ui.events].sort((a, b) => b.time - a.time)) {
    const content = popup(event.place || event.id, ['Type: ' + event.type, 'Magnitude: ' + numeric(event.mag), 'Origin: ' + time(event.time), 'Depth: ' + numeric(event.depth_km) + ' km', 'Review: ' + (event.status || 'not supplied')], event.source_url);
    let marker;
    if (map && Number.isFinite(event.lat) && Number.isFinite(event.lon)) marker = L.circleMarker([event.lat, event.lon], {radius: Math.max(4, Math.min(14, (event.mag || 2.5) * 1.8)), color: '#8e3219', weight: 1, fillColor: '#bd4f2b', fillOpacity: .75}).bindPopup(content).addTo(earthquakes);
    const row = element('tr'), place = element('td'); place.append(element('strong', event.place || event.id), element('small', (event.type || 'unknown') + ' · ' + (event.status || 'Review status not supplied')));
    row.append(element('td', time(event.time)), place, element('td', numeric(event.mag)), element('td', numeric(event.depth_km) + ' km'));
    const locate = element('td'); locate.append(button('Show', () => { if (map && marker) { map.setView([event.lat, event.lon], 6, {animate: false}); marker.openPopup(); $('map').scrollIntoView({block: 'center'}); } })); row.append(locate); $('events').append(row);
  }
  if (!ui.events.length) { const row = element('tr'), cell = element('td', 'No captured events meet the cutoff and magnitude filter.'); cell.colSpan = 5; row.append(cell); $('events').append(row); }
  $('event-count').textContent = ui.events.length + ' SHOWN' + (data.truncated ? ' · SOURCE RESULT CAPPED' : '');
  $('weather').replaceChildren();
  for (const report of data.weather || []) {
    const card = element('article', undefined, 'weather-card'); card.append(element('h3', report.station), element('p', report.description || 'Description not supplied'));
    const values = element('div', undefined, 'weather-values'); values.append(element('span', numeric(report.temperature_c) + ' °C'), element('span', numeric(report.wind_kmh) + ' km/h')); card.append(values, element('small', 'Observed: ' + time(report.time)), element('br'), sourceLink(report.source_url)); $('weather').append(card);
    if (map && Number.isFinite(report.lat) && Number.isFinite(report.lon)) L.circleMarker([report.lat, report.lon], {radius: 7, color: '#174f86', weight: 2, fillColor: '#5a99c8', fillOpacity: .9}).bindPopup(popup(report.station, [time(report.time), numeric(report.temperature_c) + ' °C · ' + numeric(report.wind_kmh) + ' km/h', report.description || 'No description'], report.source_url)).addTo(stations);
  }
  if (!(data.weather || []).length) $('weather').append(element('p', 'No captured station report at or before this cutoff. Weather coverage is shorter than the earthquake catalog.', 'muted'));
}
async function loadState() {
  // "All reported" (-2) sends no magnitude filter, so events with a null magnitude stay listed.
  const sequence = ++ui.request, params = new URLSearchParams(); if (ui.minMag > -2) params.set('min_mag', ui.minMag); if (ui.cutoff !== null) params.set('until', Math.round(ui.cutoff));
  const data = await api('/state?' + params); if (sequence !== ui.request) return; renderState(data);
}
function fitEvents() { if (!map) return; if (ui.events.length) map.fitBounds(ui.events.map(event => [event.lat, event.lon]), {padding: [25, 25], maxZoom: 6, animate: false}); else map.setView([22, 0], 2); }
async function loadLocalEvidence() {
  const sequence = ++ui.evidenceRequest;
  const [watches, alerts, snapshots] = await Promise.all([api('/watches'), api('/alerts'), api('/snapshots')]);
  if (sequence !== ui.evidenceRequest) return;
  ui.watches = watches;
  watchRings?.clearLayers(); $('watches').replaceChildren(); $('alerts').replaceChildren(); $('snapshots').replaceChildren();
  for (const watch of watches) {
    const row = element('div', undefined, 'record'); row.append(element('strong', watch.name), element('small', `${watch.lat}, ${watch.lon} · ${watch.radius_km} km · M≥${watch.min_mag}`));
    row.append(button('Remove watch', async () => { try { await api('/watches/' + watch.id, 'DELETE'); await loadLocalEvidence(); notice('Local watch removed.'); } catch (error) { notice(error.message, true); } })); $('watches').append(row);
    if (map) L.circle([watch.lat, watch.lon], {radius: watch.radius_km * 1000, color: '#006b71', weight: 2, fillOpacity: .04}).bindPopup(element('strong', watch.name)).addTo(watchRings);
  }
  if (!watches.length) $('watches').append(element('p', 'No saved watches. The default coordinates are a public city reference, not your location.', 'muted'));
  for (const alert of alerts) {
    const row = element('div', undefined, 'record' + (alert.acknowledged ? ' ack' : '')); row.append(element('strong', alert.watch_name + ' · ' + alert.kind), element('p', alert.message), element('small', 'Observed: ' + time(alert.event_time) + ' · evidence ' + alert.evidence_id), sourceLink(alert.source_url));
    if (!alert.acknowledged) row.append(button('Acknowledge', async () => { try { await api('/alerts/' + alert.id + '/ack', 'POST'); await loadLocalEvidence(); } catch (error) { notice(error.message, true); } })); else row.append(element('small', 'Acknowledged locally'));
    $('alerts').append(row);
  }
  if (!alerts.length) $('alerts').append(element('p', 'No recent fresh observation matches. Old, missing or stale evidence must not create a new live alert.', 'muted'));
  for (const snapshot of snapshots.slice(0, 12)) { const row = element('div', undefined, 'record'); row.append(element('strong', snapshot.source_id || snapshot.source || snapshot.id), element('small', 'Captured: ' + time(snapshot.fetched_at || snapshot.retrieved_at)), element('small', 'SHA-256: ' + (snapshot.sha256 || 'not supplied')), sourceLink(snapshot.url || snapshot.source_url)); $('snapshots').append(row); }
  if (!snapshots.length) $('snapshots').append(element('p', 'No snapshot metadata yet.', 'muted'));
}
function pause() { if (ui.playing) clearInterval(ui.playing); ui.playing = null; $('play').textContent = 'Play history'; $('play').setAttribute('aria-pressed', 'false'); }
function cutoffFromSlider() { if (!ui.range) return; ui.cutoff = ui.range.start + (ui.range.end - ui.range.start) * Number($('timeline').value) / 1000; loadState().catch(error => { pause(); notice(error.message, true); }); }
$('timeline').max = '1000'; $('timeline').value = '1000';
$('timeline').addEventListener('input', () => { pause(); cutoffFromSlider(); });
$('play').addEventListener('click', () => {
  if (ui.playing) { pause(); return; } if (!ui.range) return;
  $('play').textContent = 'Pause history'; $('play').setAttribute('aria-pressed', 'true'); if (Number($('timeline').value) >= 1000) $('timeline').value = '0'; cutoffFromSlider();
  ui.playing = setInterval(() => { const value = Math.min(1000, Number($('timeline').value) + 20); $('timeline').value = String(value); cutoffFromSlider(); if (value === 1000) pause(); }, 700);
});
$('current').addEventListener('click', () => { pause(); ui.cutoff = null; $('timeline').value = '1000'; loadState().catch(error => notice(error.message, true)); });
$('magnitude').addEventListener('change', () => { ui.minMag = Number($('magnitude').value); loadState().catch(error => notice(error.message, true)); });
$('fit').addEventListener('click', fitEvents);
$('refresh').addEventListener('click', async () => {
  $('refresh').disabled = true; notice('Retrieving bounded original-publisher snapshots…');
  try { await api('/refresh', 'POST'); await Promise.all([loadState(), loadLocalEvidence()]); notice('Refresh attempt completed. Source cards show actual freshness and any provider errors.'); } catch (error) { notice(error.message, true); await loadState().catch(() => {}); } finally { $('refresh').disabled = false; }
});
$('watch-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  const optional = id => $(id).value.trim() === '' ? null : Number($(id).value);
  const watch = {name: $('watch-name').value, lat: Number($('latitude').value), lon: Number($('longitude').value), radius_km: Number($('radius').value), min_mag: Number($('watch-mag').value), max_temperature_c: optional('temperature'), max_wind_kmh: optional('wind')};
  try { await api('/watches', 'POST', watch); await loadLocalEvidence(); notice('Local watch saved; recent fresh evidence evaluated. Replay requests do not create alerts.'); } catch (error) { notice(error.message, true); } finally { submit.disabled = false; }
});
Promise.all([loadState(), loadLocalEvidence()]).catch(error => notice('Local observations unavailable: ' + error.message, true));
// Also reload watches/alerts: the background poller can create alerts between page loads.
setInterval(() => { if (document.visibilityState === 'visible' && ui.cutoff === null) Promise.all([loadState(), loadLocalEvidence()]).catch(error => notice('Notebook status could not refresh: ' + error.message, true)); }, 30000);
