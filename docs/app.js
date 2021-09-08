const $ = id => document.getElementById(id), el = (tag, text = '', parent) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; }, clear = node => node.replaceChildren();
const controls = $('controls'), workspace = $('workspace');
function field(id, label, type = 'text', value = '') { const wrap = el('label', '', controls); wrap.htmlFor = id; el('span', label, wrap); const input = el('input', '', wrap); input.id = id; input.type = type; if (value)
    input.value = value; return input; }
function panel(title, id, wide = false) { const section = el('section', '', workspace); section.className = `panel${wide ? ' wide' : ''}`; const h = el('h2', title, section); h.id = `${id}-title`; section.setAttribute('aria-labelledby', h.id); return section; }
let data, quakes = [], visible = [], selected = null;
function fmtTime(value) { return Number.isFinite(value) ? new Date(value).toLocaleString() : 'Time unavailable'; }
function numeric(value) { return typeof value === 'number' && Number.isFinite(value); }
function latestWeather(records) { const byStation = new Map(); records.forEach(item => { if (!item || typeof item.station !== 'string')
    return; const old = byStation.get(item.station); if (!old || Date.parse(item.time) > Date.parse(old.time))
    byStation.set(item.station, item); }); return [...byStation.values()].sort((a, b) => a.station.localeCompare(b.station)); }
function renderWeather() { const root = $('weather'); clear(root); for (const obs of latestWeather(data.weather)) {
    const card = el('article', '', root);
    card.className = 'disclosure';
    el('strong', obs.station, card);
    el('p', `${obs.description || 'Observation unavailable'} · ${obs.temperature?.value == null ? 'Temperature unavailable' : `${obs.temperature.value} °C`} · ${obs.wind_speed?.value == null ? 'Wind unavailable' : `${obs.wind_speed.value} km/h`}`, card);
    el('small', `Observed ${fmtTime(Date.parse(obs.time))}; null values remain unavailable.`, card);
} }
function drawMap() { const svg = $('map'); clear(svg); const ns = 'http://www.w3.org/2000/svg', makeSvg = (tag, attrs) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, String(v))); svg.append(n); return n; }; for (let lon = -180; lon <= 180; lon += 60) {
    const x = (lon + 180) * 2;
    makeSvg('line', { x1: x, y1: 0, x2: x, y2: 360, stroke: '#b4c8ce', 'stroke-width': 1 });
    const t = makeSvg('text', { x: x + 3, y: 15, fill: '#344c56', 'font-size': 11 });
    t.textContent = String(lon);
} for (let lat = -60; lat <= 60; lat += 30) {
    const y = (90 - lat) * 2;
    makeSvg('line', { x1: 0, y1: y, x2: 720, y2: y, stroke: '#b4c8ce', 'stroke-width': 1 });
    const t = makeSvg('text', { x: 4, y: y - 4, fill: '#344c56', 'font-size': 11 });
    t.textContent = String(lat);
} visible.forEach(event => { const circle = makeSvg('circle', { cx: (event.longitude + 180) * 2, cy: (90 - event.latitude) * 2, r: Math.max(4, Math.min(12, (event.magnitude || 1) * 1.35)), fill: '#ba553d', stroke: '#fff', 'stroke-width': 2, tabindex: 0, role: 'button', 'aria-label': `${event.place}, magnitude ${event.magnitude}` }); circle.addEventListener('click', () => showEvent(event)); circle.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    showEvent(event);
} }); }); }
function showEvent(event) { selected = event; const root = $('event-details'); clear(root); el('h3', event.place || 'Place unavailable', root); el('p', `Magnitude ${numeric(event.magnitude) ? event.magnitude : 'not reported'} · ${fmtTime(event.time)}`, root); el('p', `Coordinates ${event.latitude}, ${event.longitude} · depth ${numeric(event.depth_km) ? `${event.depth_km} km` : 'not reported'}`, root); const link = el('a', 'Open USGS event page', root); link.href = event.url; link.rel = 'noreferrer'; }
function renderEvents() { if (!data)
    return; $('watch-results').textContent = 'Filters changed; calculate radius matches again.'; const min = Number($('minimum-mag').value); const limit = Math.max(0, Number($('timeline').value)); const sorted = quakes.slice().sort((a, b) => a.time - b.time); const cutoff = sorted.length ? sorted[Math.floor((sorted.length - 1) * limit / 100)].time : Infinity; visible = quakes.filter(e => e.time <= cutoff && (!Number.isFinite(min) || e.magnitude >= min)).sort((a, b) => b.time - a.time); $('time-label').textContent = `Through ${fmtTime(cutoff)}`; $('event-count').textContent = `${visible.length} earthquakes match. ${data.events.length - quakes.length} non-earthquake event (landslide) excluded from the magnitude filter.`; const tbody = $('events'); clear(tbody); for (const event of visible) {
    const tr = el('tr', '', tbody);
    el('td', fmtTime(event.time), tr);
    el('td', numeric(event.magnitude) ? event.magnitude.toFixed(1) : '—', tr);
    const td = el('td', '', tr), button = el('button', event.place || 'Place unavailable', td);
    button.type = 'button';
    button.className = 'secondary';
    button.addEventListener('click', () => showEvent(event));
} if (!visible.length) {
    const tr = el('tr', '', tbody), td = el('td', 'No earthquakes match this time and magnitude.', tr);
    td.colSpan = 3;
} drawMap(); if (selected && !visible.some(e => e.id === selected.id)) {
    $('event-details').textContent = 'Selected event is outside the current filters.';
} }
function distanceKm(lat1, lon1, lat2, lon2) { const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r, a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2; return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)); }
function saveWatch() { const lat = Number($('watch-lat').value), lon = Number($('watch-lon').value), radius = Number($('watch-radius').value), out = $('watch-results'); clear(out); if (['watch-lat', 'watch-lon', 'watch-radius'].some(id => !$(id).value.trim()) || !Number.isFinite(lat) || Math.abs(lat) > 90 || !Number.isFinite(lon) || Math.abs(lon) > 180 || !Number.isFinite(radius) || radius < 1 || radius > 20000) {
    out.textContent = 'Enter valid coordinates and a radius from 1 to 20,000 km.';
    return;
} const matches = visible.map(e => ({ ...e, distance: distanceKm(lat, lon, e.latitude, e.longitude) })).filter(e => e.distance <= radius); el('p', `${matches.length} earthquakes in the frozen, currently filtered snapshot within ${radius} km. This is not an alert or hazard assessment.`, out); const list = el('ul', '', out); matches.forEach(e => el('li', `${e.place} · M${e.magnitude} · ${e.distance.toFixed(1)} km · ${fmtTime(e.time)}`, list)); }
function setup() { controls.className = 'controls'; field('minimum-mag', 'Minimum earthquake magnitude', 'number', '2.5').min = '-2'; $('minimum-mag').step = '0.1'; const range = field('timeline', 'Event-time replay', 'range', '100'); range.min = '0'; range.max = '100'; range.setAttribute('aria-describedby', 'time-label'); el('span', 'Loading', controls).id = 'time-label'; const count = panel('Captured earthquakes', 'events'), p = el('p', '', count); p.id = 'event-count'; const tableWrap = el('div', '', count); tableWrap.className = 'scroll'; const table = el('table', '', tableWrap); const cap = el('caption', 'Filtered frozen earthquakes', table); cap.className = 'visually-hidden'; const head = el('thead', '', table), row = el('tr', '', head); ['Time', 'Magnitude', 'Place / inspect'].forEach(x => { const th = el('th', x, row); th.scope = 'col'; }); el('tbody', '', table).id = 'events'; const mapPanel = panel('Quake locations · equirectangular', 'map', true), svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.id = 'map'; svg.setAttribute('viewBox', '0 0 720 360'); svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', 'Longitude and latitude earthquake locations'); svg.style.cssText = 'width:100%;background:#dce9ee;border-radius:8px'; mapPanel.append(svg);
    workspace.prepend(mapPanel); el('p', 'Longitude / latitude projected onto a rectangle; consult the accessible table for precise event details. Magnitude changes marker size.', mapPanel).className = 'muted'; const details = panel('Selected event', 'details'); el('div', 'Select an event in the table or map.', details).id = 'event-details'; const weather = panel('Latest captured station observations', 'weather'); el('div', '', weather).id = 'weather'; const watch = panel('Radius watch · snapshot only', 'watch', true), rowControls = el('div', '', watch); rowControls.className = 'controls'; for (const [id, label, value, min, max] of [['watch-lat', 'Latitude', '37.77', -90, 90], ['watch-lon', 'Longitude', '-122.42', -180, 180], ['watch-radius', 'Radius · km', '200', 1, 20000]]) {
    const wrap = el('label', label, rowControls), input = el('input', '', wrap);
    input.id = id;
    input.type = 'number';
    input.value = value;
    input.min = min;
    input.max = max;
    input.step = 'any';
} const button = el('button', 'Calculate matches', rowControls); button.type = 'button'; button.id = 'save-watch'; el('div', '', watch).id = 'watch-results'; $('minimum-mag').addEventListener('input', renderEvents); $('timeline').addEventListener('input', renderEvents); button.addEventListener('click', saveWatch); }
setup();
fetch('./demo-data.json').then(response => { if (!response.ok)
    throw Error('Fixture unavailable'); return response.json(); }).then(json => { if (!Array.isArray(json.events) || !Array.isArray(json.weather) || !Array.isArray(json.sources) || !Number.isFinite(json.generated))
    throw Error('Unexpected fixture structure'); data = json; quakes = json.events.filter(e => e.type === 'earthquake' && [e.time, e.longitude, e.latitude, e.magnitude].every(numeric) && Math.abs(e.longitude) <= 180 && Math.abs(e.latitude) <= 90); if (!quakes.length)
    throw Error('No valid earthquake observations'); const attribution = $('source-attribution'); clear(attribution); json.sources.forEach((source, index) => { if (index)
    attribution.append(document.createTextNode(' · ')); const link = el('a', source.name, attribution); link.href = source.url; link.target = '_blank'; link.rel = 'noreferrer'; el('span', ` · SHA-256 ${source.sha256}`, attribution); }); const age = Math.max(0, Date.now() - json.generated); $('status').textContent = `Frozen snapshot · source age ${Math.floor(age / 3600000)} h ${Math.floor(age % 3600000 / 60000)} min · ${json.events.length} records, including ${json.events.length - quakes.length} non-earthquake event. No live refresh.`; renderWeather(); renderEvents(); }).catch(error => { $('status').textContent = `Cannot load frozen snapshot: ${error.message}. Reload to try again.`; $('status').className = 'status error'; });
function labelScrollableContent() {
    document.querySelectorAll('.scroll, pre').forEach(node => {
        node.tabIndex = 0;
        if (!node.hasAttribute('role'))
            node.setAttribute('role', 'region');
        if (!node.hasAttribute('aria-label'))
            node.setAttribute('aria-label', `${node.closest('section')?.querySelector('h2')?.textContent || 'Recorded'} scrollable content`);
    });
}
new MutationObserver(labelScrollableContent).observe(document.getElementById('main'), { childList: true, subtree: true });
labelScrollableContent();
