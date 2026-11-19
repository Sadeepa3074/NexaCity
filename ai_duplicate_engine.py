"""CivicFix Phase 5 Part 2 — explainable nearby-text match suggestions.

The text similarity is genuine TF-IDF/cosine similarity. Geography is a
Haversine distance calculation, not an AI probability. No online APIs.
Candidates NEVER trigger automated incident merging, assignment or rejection.
"""
from math import atan2, cos, radians, sin, sqrt

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MAX_DISTANCE_METERS = 750.0
MIN_TEXT_SIMILARITY = 0.30
MAX_RESULTS = 6


def distance_metres(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres, given WGS84 decimal degrees."""
    a1, b1, a2, b2 = map(float, (lat1, lon1, lat2, lon2))
    dlat = radians(a2 - a1)
    dlon = radians(b2 - b1)
    x = sin(dlat / 2) ** 2 + cos(radians(a1)) * cos(radians(a2)) * sin(dlon / 2) ** 2
    return 6371000.0 * 2.0 * atan2(sqrt(x), sqrt(max(0.0, 1.0 - x)))


def _cosine_values(texts):
    # Character n-grams are tolerant of misspellings and reordered phrases;
    # word n-grams provide a useful second perspective.
    char_matrix = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5),
                                  lowercase=True, strip_accents='unicode',
                                  sublinear_tf=True).fit_transform(texts)
    char_scores = cosine_similarity(char_matrix[0:1], char_matrix[1:]).ravel()
    try:
        word_matrix = TfidfVectorizer(analyzer='word', ngram_range=(1, 2),
                                     lowercase=True, strip_accents='unicode',
                                     sublinear_tf=True).fit_transform(texts)
        word_scores = cosine_similarity(word_matrix[0:1], word_matrix[1:]).ravel()
    except ValueError:
        # Empty vocabulary for punctuation-only text; char model still works.
        word_scores = [0.0] * (len(texts) - 1)
    return [float(0.75 * ch + 0.25 * wd) for ch, wd in zip(char_scores, word_scores)]


def score_candidates(current, nearby):
    """Return high-quality, explainable, reviewable candidate pairs.

    `nearby` must already be restricted using the SQL lat/lon bounding box.
    Results include only other distinct reports within 750m and sufficiently
    similar text, sorted by an *indicative ranking*, not a probability.
    """
    if current.get('latitude') is None or current.get('longitude') is None:
        return []
    description = ' '.join(str(current.get('description') or '').split())
    if len(description) < 12:
        return []

    checked = []
    for row in nearby:
        if int(row['complaint_id']) == int(current['complaint_id']):
            continue
        other_text = ' '.join(str(row.get('description') or '').split())
        if len(other_text) < 12 or row.get('latitude') is None or row.get('longitude') is None:
            continue
        try:
            d = distance_metres(current['latitude'], current['longitude'],
                                row['latitude'], row['longitude'])
        except (TypeError, ValueError):
            continue
        if d <= MAX_DISTANCE_METERS:
            checked.append((row, other_text, d))

    if not checked:
        return []

    try:
        similarities = _cosine_values([description] + [v[1] for v in checked])
    except ValueError:
        # Whitespace/punctuation-only descriptions can have no vector features.
        return []
    results = []
    for (row, text, distance), similarity in zip(checked, similarities):
        if similarity < MIN_TEXT_SIMILARITY:
            continue
        proximity = 1.0 - min(distance / MAX_DISTANCE_METERS, 1.0)
        rank = 0.78 * similarity + 0.22 * proximity
        results.append({
            'complaint_id': row['complaint_id'],
            'reference_code': row['reference_code'],
            'description': text[:225],
            'category_name': row.get('category_name') or 'Uncategorized',
            'status': row.get('status') or 'Unknown',
            'distance_m': int(round(distance)),
            'text_similarity': round(similarity * 100),
            'rank': rank,
            'match_label': ('Strong candidate' if similarity >= .70 and distance <= 250
                            else 'Possible match'),
            'decision': None,
        })
    results.sort(key=lambda x: (-x['rank'], -x['text_similarity'], x['distance_m'], x['complaint_id']))
    return results[:MAX_RESULTS]


def geographic_bounding_box(latitude, longitude, radius_metres=MAX_DISTANCE_METERS):
    """Fast coarse SQL prefilter; Haversine enforces the true circular radius."""
    lat = float(latitude)
    lon = float(longitude)
    lat_delta = radius_metres / 111000.0 * 1.2
    lon_delta = lat_delta / max(0.1, cos(radians(lat)))
    return (max(-90, lat-lat_delta), min(90, lat+lat_delta),
            max(-180, lon-lon_delta), min(180, lon+lon_delta))
