document.addEventListener("DOMContentLoaded", function () {
    const mapElement = document.getElementById("complaint-map");
    const latitudeInput = document.getElementById("latitude");
    const longitudeInput = document.getElementById("longitude");
    const selectedLocation = document.getElementById("selected-location");
    const currentLocationButton = document.getElementById("use-current-location");
    const mapError = document.getElementById("map-error");
    const form = document.getElementById("citizen-report-form");
    const photoInput = document.getElementById("photo");
    const photoFileName = document.getElementById("photo-file-name");

    if (!mapElement || typeof L === "undefined") {
        if (mapError) mapError.textContent = "The map could not load. Check your internet connection and refresh the page.";
        return;
    }

    // NexaCity's current reporting coverage is the Colombo map area only.
    const defaultCenter = [6.9271, 79.8612];
    const colomboBounds = L.latLngBounds([6.87, 79.82], [6.99, 79.90]);
    const map = L.map(mapElement, {
        scrollWheelZoom: false,
        maxBounds: colomboBounds,
        maxBoundsViscosity: 1,
        minZoom: 11
    }).setView(defaultCenter, 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    let marker = null;

    function setLocation(lat, lng, zoom) {
        const safeLat = Number(lat);
        const safeLng = Number(lng);
        if (!Number.isFinite(safeLat) || !Number.isFinite(safeLng) ||
            safeLat < -90 || safeLat > 90 || safeLng < -180 || safeLng > 180) {
            if (mapError) mapError.textContent = "That location is not valid. Please select another point.";
            return false;
        }
        if (!colomboBounds.contains([safeLat, safeLng])) {
            if (mapError) mapError.textContent = "NexaCity currently accepts reports within the Colombo coverage area only. Please choose a point inside the map area.";
            return false;
        }
        latitudeInput.value = safeLat.toFixed(7);
        longitudeInput.value = safeLng.toFixed(7);
        if (!marker) {
            marker = L.marker([safeLat, safeLng], { draggable: true }).addTo(map);
            marker.on("dragend", function (event) {
                const point = event.target.getLatLng();
                if (!setLocation(point.lat, point.lng, false)) {
                    marker.setLatLng([Number(latitudeInput.value) || defaultCenter[0], Number(longitudeInput.value) || defaultCenter[1]]);
                }
            });
        } else {
            marker.setLatLng([safeLat, safeLng]);
        }
        if (zoom !== false) map.setView([safeLat, safeLng], zoom || 16);
        selectedLocation.textContent = "Selected Colombo location: " + safeLat.toFixed(5) + ", " + safeLng.toFixed(5) + " (you can drag the marker to adjust it).";
        if (mapError) mapError.textContent = "";
        return true;
    }

    map.on("click", function (event) {
        setLocation(event.latlng.lat, event.latlng.lng, false);
    });

    if (currentLocationButton) {
        currentLocationButton.addEventListener("click", function () {
            if (!navigator.geolocation) {
                if (mapError) mapError.textContent = "Your browser does not support location detection. Please select a point on the map.";
                return;
            }
            currentLocationButton.disabled = true;
            currentLocationButton.textContent = "Finding your location…";
            navigator.geolocation.getCurrentPosition(
                function (position) {
                    const accepted = setLocation(position.coords.latitude, position.coords.longitude, 17);
                    if (!accepted && mapError) {
                        mapError.textContent = "Your current location is outside NexaCity's Colombo coverage area. Select a location inside Colombo instead.";
                    }
                    currentLocationButton.disabled = false;
                    currentLocationButton.innerHTML = '<span aria-hidden="true">◎</span> Use my current location';
                },
                function (error) {
                    const messages = {
                        1: "Location permission was denied. You can still select the location manually on the map.",
                        2: "Your location is currently unavailable. Please select it on the map.",
                        3: "Finding your location took too long. Please select it on the map."
                    };
                    if (mapError) mapError.textContent = messages[error.code] || "Could not get your location. Please select it on the map.";
                    currentLocationButton.disabled = false;
                    currentLocationButton.innerHTML = '<span aria-hidden="true">◎</span> Use my current location';
                },
                { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 }
            );
        });
    }

    if (form) {
        form.addEventListener("submit", function (event) {
            const selectedLat = Number(latitudeInput.value);
            const selectedLng = Number(longitudeInput.value);
            if (!latitudeInput.value || !longitudeInput.value || !colomboBounds.contains([selectedLat, selectedLng])) {
                event.preventDefault();
                if (mapError) mapError.textContent = "Please select an issue location inside the Colombo coverage area before submitting.";
                mapElement.scrollIntoView({ behavior: "smooth", block: "center" });
                return;
            }
            const selectedPhoto = photoInput && photoInput.files && photoInput.files[0];
            if (selectedPhoto && selectedPhoto.size > 5 * 1024 * 1024) {
                event.preventDefault();
                if (mapError) mapError.textContent = "The photo must be 5 MB or smaller.";
                photoInput.focus();
            }
        });
    }

    if (photoInput && photoFileName) {
        photoInput.addEventListener("change", function () {
            const file = photoInput.files && photoInput.files[0];
            photoFileName.textContent = file ? file.name : "No file selected";
        });
    }

    // Leaflet can calculate the wrong dimensions if the map initially paints while hidden.
    window.setTimeout(function () { map.invalidateSize(); }, 150);
});
