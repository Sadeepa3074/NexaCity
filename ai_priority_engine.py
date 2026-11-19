"""CivicFix explainable priority triage (Phase 5, Part 3).

This is a VERSIONED, RULE-BASED decision-support score, not an ML classifier,
probability, emergency dispatch system, or a substitute for officer judgement.
Inputs are citizen-reported severity/description, report age and officer-reviewed
same-issue pairs. Scores DO NOT change statuses, assignments or public records.
"""
from datetime import datetime
import re

SCORING_VERSION = 'priority-rules-v1'
CLOSED_STATUSES = frozenset({'Resolved', 'Rejected'})

# Conservative phrase signals; one contribution per group, regardless of repeats.
# Matching is intentionally inspectable for coursework discussion and manual review.
HAZARD_PATTERNS = (
    (r'\bexposed\s+(?:live\s+)?wires?\b', 'exposed electrical wiring'),
    (r'\blive\s+(?:electric(?:al)?\s+)?wires?\b', 'live electrical wiring'),
    (r'\bsparking\b', 'sparking'),
    (r'\belectrocut(?:ion|ed|ing)?\b', 'electrocution risk'),
    (r'\b(?:fire|flames?)\b', 'fire or flames mentioned'),
    (r'\b(?:collapse|collapsing|collapsed)\b', 'structural collapse mentioned'),
    (r'\bsinkholes?\b', 'sinkhole mentioned'),
    (r'\b(?:injured|injury|injuries)\b', 'injury mentioned'),
    (r'\b(?:dangerous|life[- ]threatening)\b', 'danger mentioned'),
    (r'\b(?:sewage\s+(?:overflow|leak)|raw\s+sewage)\b', 'sewage hazard mentioned'),
    (r'\b(?:fallen\s+tree|tree\s+fell)\b', 'fallen tree mentioned'),
    (r'\b(?:gas\s+leak)\b', 'gas leak mentioned'),
)
SERVICE_PATTERNS = (
    (r'\b(?:blocked\s+(?:road|street|drain)|road\s+blocked)\b', 'blocked public access'),
    (r'\b(?:flooded|flooding|floodwaters?)\b', 'flooding mentioned'),
    (r'\b(?:overflowing\s+(?:drain|water)|water\s+overflow)\b', 'overflow mentioned'),
    (r'\b(?:power\s+(?:outage|cut)|no\s+electricity)\b', 'power disruption'),
    (r'\b(?:street\s*lights?\s+(?:is\s+)?(?:out|broken|not\s+working))\b', 'lighting disruption'),
    (r'\b(?:streetlight\s+(?:is\s+)?(?:out|broken|not\s+working))\b', 'lighting disruption'),
    (r'\b(?:potholes?|open\s+manhole)\b', 'road hazard / access problem'),
)
SENSITIVE_PATTERNS = (
    (r'\b(?:school|schools)\b', 'school mentioned'),
    (r'\b(?:hospital|hospitals|clinic|clinics)\b', 'health facility mentioned'),
    (r'\b(?:pedestrian\s+crossing|zebra\s+crossing)\b', 'pedestrian crossing mentioned'),
    (r'\b(?:bus\s+(?:stop|stand))\b', 'public transport stop mentioned'),
)
# Avoid elementary false positives such as "no fire" or "not dangerous".
NEGATION = re.compile(r'\b(?:no|not|without|never|isn.t|wasn.t)\b', re.I)


def _first_positive_signal(description, patterns):
    for pattern, explanation in patterns:
        match = re.search(pattern, description, flags=re.I)
        if not match:
            continue
        # Check a short phrase immediately before the match for negation.
        prefix = description[max(0, match.start() - 22):match.start()]
        tokens = prefix.split()
        if NEGATION.search(' '.join(tokens[-3:])):
            continue
        return explanation
    return None


def _level(score):
    if score >= 75:
        return 'Critical'
    if score >= 45:
        return 'High'
    if score >= 24:
        return 'Moderate'
    return 'Low'


def score_priority(report, confirmed_duplicate_count=0, now=None):
    """Return deterministic priority score and a transparent point breakdown.

    now/report.created_at should be in the same naive local timezone. Closed
    complaints return no active-queue score. Never interprets text as verified.
    """
    status = str(report.get('status') or '')
    if status in CLOSED_STATUSES:
        return {'state': 'closed', 'score': None, 'level': 'Closed',
                'components': [], 'version': SCORING_VERSION,
                'explanation': 'Closed reports are not in the active priority queue.'}

    severity = str(report.get('severity') or 'Medium').strip().title()
    severity_points = {'Low': 12, 'Medium': 26, 'High': 45}.get(severity, 26)
    components = [
        {'label': 'Citizen-reported severity: ' + (severity if severity in ('Low','Medium','High') else 'Unknown'),
         'points': severity_points, 'basis': 'Citizen selection, not independently verified'},
    ]

    description = str(report.get('description') or '')[:4000]
    hazard = _first_positive_signal(description, HAZARD_PATTERNS)
    if hazard:
        components.append({'label': 'Safety phrase: ' + hazard, 'points': 30,
                           'basis': 'Phrase found in complaint; needs officer verification'})
    service = _first_positive_signal(description, SERVICE_PATTERNS)
    if service:
        components.append({'label': 'Service disruption: ' + service, 'points': 14,
                           'basis': 'Phrase found in complaint; needs officer verification'})
    sensitive = _first_positive_signal(description, SENSITIVE_PATTERNS)
    if sensitive:
        components.append({'label': 'Sensitive location mention: ' + sensitive, 'points': 10,
                           'basis': 'Text mention only; not independently mapped/verified'})

    when = now or datetime.now()
    created = report.get('created_at')
    hours = 0
    if isinstance(created, datetime):
        # Defensive: avoid timezone mismatch if a datetime with tz is supplied.
        if created.tzinfo is not None and when.tzinfo is None:
            when = datetime.now(created.tzinfo)
        elif created.tzinfo is None and when.tzinfo is not None:
            when = when.replace(tzinfo=None)
        hours = max(0, (when - created).total_seconds() / 3600)
    if hours >= 72:
        components.append({'label': 'Awaiting attention for at least 72 hours',
                           'points': 12, 'basis': 'Time since complaint submission'})
    elif hours >= 24:
        components.append({'label': 'Awaiting attention for at least 24 hours',
                           'points': 6, 'basis': 'Time since complaint submission'})

    count = max(0, int(confirmed_duplicate_count or 0))
    if count:
        points = min(12, count * 6)
        components.append({'label': str(count) + ' officer-confirmed same-issue pair(s)',
                           'points': points, 'basis': 'Saved administrator duplicate-review decisions'})

    uncapped = sum(item['points'] for item in components)
    score = min(100, uncapped)
    return {'state': 'ready', 'score': score, 'level': _level(score),
            'components': components, 'version': SCORING_VERSION,
            'capped': uncapped > 100,
            'explanation': 'Advisory rule-based ranking only; not a probability or verified emergency assessment.'}
