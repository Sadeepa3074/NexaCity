// CivicFix admin overview map - all map data is supplied by Flask from MySQL.
document.addEventListener('DOMContentLoaded', () => {
  const element = document.getElementById('admin-overview-map');
  const dataNode = document.getElementById('civicfix-map-data');
  if (!element || !dataNode) return;

  if (typeof L === 'undefined') {
    element.innerHTML = '<div class="map-message">Map library unavailable. Check your internet connection.</div>';
    return;
  }

  let reports = [];
  try {
    reports = JSON.parse(dataNode.textContent);
  } catch (error) {
    element.innerHTML = '<div class="map-message">Unable to load location data.</div>';
    return;
  }

  const colomboBounds = L.latLngBounds([6.87, 79.82], [6.99, 79.90]);
  const map = L.map(element, { scrollWheelZoom: false, maxBounds: colomboBounds, maxBoundsViscosity: 1, minZoom: 11 }).setView([6.9271, 79.8612], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  const bounds = [];
  for (const report of reports) {
    if (!Number.isFinite(report.lat) || !Number.isFinite(report.lng)) continue;
    const color = report.severity === 'High' ? '#ef4444' :
                  report.severity === 'Medium' ? '#ff9c2d' : '#2F7655';
    const marker = L.circleMarker([report.lat, report.lng], {
      radius: 8, color: '#ffffff', weight: 2,
      fillColor: color, fillOpacity: 0.95
    }).addTo(map);

    // Avoid inserting complaint text into HTML; use textContent to prevent XSS.
    const popup = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = report.reference;
    const description = document.createElement('p');
    description.textContent = report.description;
    const extra = document.createElement('small');
    extra.textContent = `${report.area} · ${report.category} · ${report.status}`;
    popup.append(title, description, extra);
    marker.bindPopup(popup);
    bounds.push([report.lat, report.lng]);
  }

  if (bounds.length > 1) {
    map.fitBounds(bounds, { padding: [32, 32], maxZoom: 15 });
  } else if (bounds.length === 1) {
    map.setView(bounds[0], 15);
  }
  setTimeout(() => map.invalidateSize(), 100);
});
// Set chart bar heights using values from Flask

document.addEventListener("DOMContentLoaded", function () {

    const chartBars = document.querySelectorAll(
        ".chart-bar[data-height]"
    );

    chartBars.forEach(function (bar) {

        const height = Number(bar.dataset.height);

        if (Number.isFinite(height)) {
            bar.style.height =
                Math.max(0, Math.min(100, height)) + "%";
        }

    });

});