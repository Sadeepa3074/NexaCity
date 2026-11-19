"""Pure presentation and evaluation helpers for CivicFix AI Insights.

No fabricated data, automatic status changes, or claims of ground-truth accuracy.
The classifier's recorded holdout metrics are distinct from officer-review agreement.
"""

MAX_QUEUE_SCAN = 120
MAX_QUEUE_DISPLAY = 12


def percent(part, whole):
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


def model_display_metadata(raw):
    """Sanitize metadata from a trusted, locally trained model for display.

    Supports models trained before Phase 5 Part 4 (no confusion matrix yet).
    """
    if not isinstance(raw, dict):
        return {'state': 'unavailable'}
    source = raw.get('source')
    labels = raw.get('labels_order') or []
    matrix = raw.get('confusion_matrix')
    detailed = raw.get('per_class_metrics') or []
    valid_matrix = (bool(labels) and isinstance(matrix, list)
                    and len(matrix) == len(labels)
                    and all(isinstance(row, list) and len(row) == len(labels)
                            for row in matrix))
    return {
        'state': 'ready',
        'source': source if source in ('demo', 'verified') else 'unknown',
        'is_demo': source == 'demo',
        'trained_at': raw.get('trained_at') or 'Unknown',
        'training_count': int(raw.get('training_count') or 0),
        'test_count': int(raw.get('test_count') or 0),
        'total_examples': int(raw.get('total_examples') or 0),
        'accuracy': round(100 * float(raw['holdout_accuracy']), 1) if raw.get('holdout_accuracy') is not None else None,
        'macro_f1': round(100 * float(raw['macro_f1']), 1) if raw.get('macro_f1') is not None else None,
        'label_counts': raw.get('class_counts') or {},
        'labels_order': labels if valid_matrix else [],
        'confusion_matrix': matrix if valid_matrix else None,
        'class_metrics': [
            {'category': str(c.get('category') or '?'),
             'precision': percent(float(c.get('precision') or 0), 1),
             'recall': percent(float(c.get('recall') or 0), 1),
             'f1': percent(float(c.get('f1') or 0), 1),
             'support': int(c.get('support') or 0)}
            for c in detailed if isinstance(c, dict)
        ] if valid_matrix else [],
        'old_metadata': not valid_matrix,
    }


def compare_predictions(pipeline, reports, max_display=MAX_QUEUE_DISPLAY):
    """Batch-predict recent unresolved descriptions; never updates records.

    Returns explicitly sample-limited counts. Agreement with citizen selections
    and model probability estimates are NOT validated accuracy metrics.
    """
    outcome = {
        'sample_size': len(reports), 'compared': 0, 'matching': 0,
        'mismatching': 0, 'uncategorized': 0, 'low_estimate': 0,
        'mismatch_rate': None, 'queue': [],
    }
    if not reports:
        return outcome

    texts = [str(r.get('description') or '') for r in reports]
    probs = pipeline.predict_proba(texts)
    labels = [str(x) for x in pipeline.classes_]
    for report, vector in zip(reports, probs):
        index = int(vector.argmax())
        suggested = labels[index]
        estimate = round(float(vector[index]) * 100, 1)
        chosen = str(report.get('category_name') or '').strip()
        if estimate < 50:
            outcome['low_estimate'] += 1
        if not chosen:
            outcome['uncategorized'] += 1
            continue
        outcome['compared'] += 1
        if suggested.casefold() == chosen.casefold():
            outcome['matching'] += 1
            continue
        outcome['mismatching'] += 1
        outcome['queue'].append({
            'complaint_id': report['complaint_id'],
            'reference_code': report['reference_code'],
            'citizen_category': chosen,
            'ai_category': suggested,
            'estimate': estimate,
            'status': report.get('status') or '',
            'severity': report.get('severity') or '',
            'area_name': report.get('area_name') or 'Area not specified',
            'description_excerpt': str(report.get('description') or '')[:130],
            'created_at': report.get('created_at'),
        })
    outcome['queue'] = outcome['queue'][:max_display]
    outcome['mismatch_rate'] = percent(outcome['mismatching'], outcome['compared'])
    return outcome


def assemble_operational_metrics(totals, label_count, dup, priority, categories):
    total = int(totals.get('total') or 0)
    reviewed_priority = int(priority.get('reviewed') or 0)
    matched_priority = int(priority.get('agreed') or 0)
    return {
        'total_reports': total,
        'open_reports': int(totals.get('active') or 0),
        'verified_labels': int(label_count or 0),
        'label_coverage': percent(int(label_count or 0), total),
        'duplicate_reviews': int(dup.get('total') or 0),
        'duplicate_same': int(dup.get('same_issue') or 0),
        'duplicate_different': int(dup.get('different_issue') or 0),
        'priority_reviews': reviewed_priority,
        'priority_agreements': matched_priority,
        'priority_agreement_rate': percent(matched_priority, reviewed_priority),
        'verified_categories': [
            {'name': str(row.get('category_name') or 'Unknown'),
             'amount': int(row.get('amount') or 0)}
            for row in categories
        ],
    }
