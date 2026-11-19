
document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("complaint-form");
    const latitudeInput = document.getElementById("latitude");
    const longitudeInput = document.getElementById("longitude");
    const locationText = document.getElementById("selected-location");
    const locateButton = document.getElementById("locate-me-btn");
    const gpsStatus = document.getElementById("gps-status");

    if (typeof L === "undefined") {
        gpsStatus.textContent = "Map could not load.";
        return;
    }

    // Initial map view: Sri Lanka
    const map = L.map("complaint-map").setView(
        [7.3, 80.7], 8
    );

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19,
            attribution:
                '&copy; OpenStreetMap contributors'
        }
    ).addTo(map);

    let issueMarker = null;
    let currentLocationMarker = null;
    let accuracyCircle = null;

    // Select the location of the actual issue
    function selectIssueLocation(lat, lng) {

        const position = L.latLng(lat, lng);

        if (issueMarker) {
            issueMarker.setLatLng(position);
        } else {
            issueMarker = L.marker(position).addTo(map);
        }

        latitudeInput.value = lat.toFixed(7);
        longitudeInput.value = lng.toFixed(7);

        locationText.textContent =
            "Selected issue location: " +
            lat.toFixed(5) + ", " + lng.toFixed(5);
    }

    // Allow manual selection
    map.on("click", function (event) {
        selectIssueLocation(
            event.latlng.lat,
            event.latlng.lng
        );
    });

    // Locate the citizen using browser location services
    locateButton.addEventListener("click", function () {

        if (!navigator.geolocation) {
            gpsStatus.textContent =
                "Your browser does not support location detection.";
            return;
        }

        locateButton.disabled = true;
        gpsStatus.textContent = "Finding your location...";

        navigator.geolocation.getCurrentPosition(

            // SUCCESS
            function (position) {

                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                const accuracy = position.coords.accuracy;

                const currentPosition = L.latLng(lat, lng);

                // Display current position as a blue dot
                if (currentLocationMarker) {
                    currentLocationMarker.setLatLng(currentPosition);
                } else {
                    currentLocationMarker = L.circleMarker(
                        currentPosition,
                        {
                            radius: 8,
                            color: "#ffffff",
                            weight: 2,
                            fillColor: "#2563eb",
                            fillOpacity: 1
                        }
                    ).addTo(map);
                }

                // Display approximate accuracy area
                if (accuracyCircle) {
                    map.removeLayer(accuracyCircle);
                }

                accuracyCircle = L.circle(
                    currentPosition,
                    {
                        radius: accuracy,
                        color: "#2563eb",
                        fillColor: "#60a5fa",
                        fillOpacity: 0.12,
                        weight: 1
                    }
                ).addTo(map);

                // Zoom to current location
                map.setView(
                    currentPosition,
                    accuracy > 1000 ? 13 : 16
                );

                // Also select it as the issue location
                selectIssueLocation(lat, lng);

                gpsStatus.textContent =
                    "Location found! Approximate accuracy: " +
                    Math.round(accuracy) +
                    " metres. Adjust the issue pin if needed.";

                locateButton.disabled = false;
            },

            // ERROR
            function (error) {

                let message = "Could not determine your location.";

                if (error.code === 1) {
                    message =
                        "Location permission denied. Please allow location access.";
                } else if (error.code === 2) {
                    message =
                        "Location unavailable. Try manual selection.";
                } else if (error.code === 3) {
                    message =
                        "Location request timed out. Please try again.";
                }

                gpsStatus.textContent = message;
                locateButton.disabled = false;
            },

            // LOCATION OPTIONS
            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 0
            }
        );
    });

    // Validate selected location before submitting
    form.addEventListener("submit", function (event) {

        if (!latitudeInput.value || !longitudeInput.value) {
            event.preventDefault();

            alert(
                "Please select the issue location on the map."
            );
        }
    });

});
