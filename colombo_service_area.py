"""Shared Colombo coverage bounds used by NexaCity maps and report validation.

These coordinates define the prototype's Colombo reporting viewport. They are
a practical rectangular coverage area, not a legally authoritative Colombo
Municipal Council cadastral boundary. Replace with an approved municipal
GeoJSON polygon if exact ward/municipal enforcement is required.
"""

COLOMBO_SOUTH = 6.87
COLOMBO_NORTH = 6.99
COLOMBO_WEST = 79.82
COLOMBO_EAST = 79.90

COLOMBO_CENTER = (6.9271, 79.8612)


def is_within_colombo_service_area(latitude, longitude):
    """Return whether coordinates fall inside the current Colombo coverage box."""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False

    return (
        COLOMBO_SOUTH <= latitude <= COLOMBO_NORTH
        and COLOMBO_WEST <= longitude <= COLOMBO_EAST
    )
