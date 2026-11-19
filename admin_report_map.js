// CivicFix: readonly map of a submitted report's selected coordinates.
document.addEventListener('DOMContentLoaded', function () {
  const mapElement = document.getElementById('admin-report-map');
  if (!mapElement) return;
  const lat = Number(mapElement.dataset.lat);
  const lng = Number(mapElement.dataset.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng) ||
      lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    mapElement.textContent = 'This report does not have valid map coordinates.';
    return;
  }
  if (typeof L === 'undefined') {
    mapElement.textContent = 'The map library could not load. Check internet access.';
    return;
  }
  const map = L.map(mapElement, { scrollWheelZoom: false }).setView([lat, lng], 16);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.marker([lat, lng]).addTo(map).bindPopup('Reported issue location');
  setTimeout(() => map.invalidateSize(), 100);
});
