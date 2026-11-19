/* CivicFix Part 5 — Leaflet map with real, authorized report coordinates. */
document.addEventListener('DOMContentLoaded', function () {
  'use strict';
  const el = document.getElementById('admin-hotspots-map');
  const dataElement = document.getElementById('civicfix-hotspots-data');
  const statusElement = document.getElementById('map-feedback');
  if (!el || !dataElement) return;
  if (typeof L === 'undefined') {
    el.textContent = 'Unable to load Leaflet. Check internet access or browser blocking.';
    return;
  }
  let reports;
  try { reports = JSON.parse(dataElement.textContent); }
  catch (error) { el.textContent = 'Map data could not be loaded.'; return; }
  reports = reports.filter(item => Number.isFinite(item.lat) && Number.isFinite(item.lng)
    && Math.abs(item.lat) <= 90 && Math.abs(item.lng) <= 180);

  const colomboBounds = L.latLngBounds([6.87, 79.82], [6.99, 79.90]);
  const map = L.map(el, { scrollWheelZoom: false, maxBounds: colomboBounds, maxBoundsViscosity: 1, minZoom: 11 }).setView([6.9271, 79.8612], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  const pinLayer = L.layerGroup();
  const clusterLayer = L.layerGroup();
  const allCoords = [];
  const areaCoords = new Map();
  const colors = { High: '#e94c54', Medium: '#f19b24', Low: '#2F7655' };

  function popupForReport(item) {
    const root = document.createElement('div');
    root.className = 'map-popup-wrap';
    const title = document.createElement('strong');
    title.textContent = item.reference;
    const summary = document.createElement('p');
    summary.textContent = item.description;
    const meta = document.createElement('small');
    meta.textContent = `${item.category} · ${item.status} · ${item.area}`;
    const link = document.createElement('a');
    link.href = item.detail_url;
    link.textContent = 'Review this report →';
    link.setAttribute('data-cf-drawer-link', '');
    root.append(title, summary, meta, document.createElement('br'), link);
    return root;
  }

  // The actual reported locations, not fictional hotspots.
  for (const item of reports) {
    const ll = [item.lat, item.lng];
    allCoords.push(ll);
    const areaKey = (item.area || '').toLowerCase().trim();
    if (!areaCoords.has(areaKey)) areaCoords.set(areaKey, []);
    areaCoords.get(areaKey).push(ll);
    L.circleMarker(ll, {
      radius: 8, color: '#fff', weight: 2,
      fillColor: colors[item.severity] || '#2F7655', fillOpacity: 0.95
    }).bindPopup(popupForReport(item)).addTo(pinLayer);
  }

  // Grid-based spatial concentration: ~2 km cell in latitude; longitude
  // distance varies by latitude. No AI or predictive claim is made.
  const cellSize = 0.02;
  const cells = new Map();
  for (const item of reports) {
    const key = `${Math.floor(item.lat / cellSize)}:${Math.floor(item.lng / cellSize)}`;
    if (!cells.has(key)) cells.set(key, { list: [], latSum: 0, lngSum: 0 });
    const cell = cells.get(key);
    cell.list.push(item);
    cell.latSum += item.lat;
    cell.lngSum += item.lng;
  }
  for (const cell of cells.values()) {
    const n = cell.list.length;
    const center = [cell.latSum / n, cell.lngSum / n];
    if (n === 1) {
      const item = cell.list[0];
      L.circleMarker(center, {
        radius: 9, color: '#fff', weight: 2,
        fillColor: colors[item.severity] || '#2F7655', fillOpacity: .96
      }).bindPopup(popupForReport(item)).addTo(clusterLayer);
    } else {
      const size = Math.min(48, 30 + Math.log2(n) * 6);
      const icon = L.divIcon({
        className: 'map-cluster-icon',
        html: String(n), iconSize: [size, size], iconAnchor: [size / 2, size / 2]
      });
      const marker = L.marker(center, { icon }).addTo(clusterLayer);
      const popup = document.createElement('div');
      popup.className = 'map-popup-wrap';
      const heading = document.createElement('strong');
      heading.textContent = `${n} reports in this map grid area`;
      const note = document.createElement('p');
      note.textContent = 'Reports may describe different issues or the same incident.';
      const list = document.createElement('ul');
      for (const item of cell.list.slice(0, 8)) {
        const li = document.createElement('li');
        const link = document.createElement('a');
        link.href = item.detail_url;
        link.textContent = `${item.reference} · ${item.category}`;
        link.setAttribute('data-cf-drawer-link', '');
        li.append(link); list.append(li);
      }
      popup.append(heading, note, list);
      if (n > 8) {
        const more = document.createElement('small');
        more.textContent = `Showing 8 of ${n}; zoom in or select Report pins to inspect more.`;
        popup.append(more);
      }
      marker.bindPopup(popup);
    }
  }

  let activeMode = 'clusters';
  function showMode(mode) {
    activeMode = mode;
    map.removeLayer(pinLayer);
    map.removeLayer(clusterLayer);
    (mode === 'pins' ? pinLayer : clusterLayer).addTo(map);
    document.querySelectorAll('[data-map-mode]').forEach(button => {
      const isSelected = button.dataset.mapMode === mode;
      button.classList.toggle('active', isSelected);
      button.setAttribute('aria-pressed', String(isSelected));
    });
  }
  document.querySelectorAll('[data-map-mode]').forEach(button => {
    button.addEventListener('click', () => showMode(button.dataset.mapMode));
  });
  showMode(activeMode);

  if (allCoords.length > 1) {
    map.fitBounds(allCoords, { padding: [35, 35], maxZoom: 15 });
  } else if (allCoords.length === 1) {
    map.setView(allCoords[0], 15);
  }
  document.querySelectorAll('.map-area-item').forEach(button => {
    button.addEventListener('click', () => {
      const lat = Number(button.dataset.lat), lng = Number(button.dataset.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const coords = areaCoords.get((button.dataset.name || '').toLowerCase().trim());
      if (coords && coords.length > 0) map.fitBounds(coords, { padding: [40, 40], maxZoom: 15 });
      else map.setView([lat, lng], 13);
      statusElement.textContent = `Focused on ${button.dataset.name}. Map points represent reported locations.`;
    });
  });
  window.setTimeout(() => map.invalidateSize(), 150);
});
