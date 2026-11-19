"""Phase 5 Part 4: CivicFix admin-only AI Insights & Evaluation dashboard.

Read-only. No training, data rewriting, scheduling or model decisions occur
on web requests. All statistics are backed by MySQL or local training metadata.
"""
import csv
from io import StringIO

import mysql.connector
from flask import current_app, make_response, render_template, url_for

from db import get_db_connection
from ai_classifier import MODEL_PATH, _open_model
from ai_insights_service import (
    MAX_QUEUE_SCAN, assemble_operational_metrics,
    compare_predictions, model_display_metadata,
)


def _load_model():
    if not MODEL_PATH.is_file():
        return {'state': 'not_trained'}, None
    try:
        bundle = _open_model(str(MODEL_PATH), MODEL_PATH.stat().st_mtime_ns)
        pipeline = bundle['pipeline']
        metadata = model_display_metadata(bundle['metadata'])
        if not hasattr(pipeline, 'predict_proba'):
            raise TypeError('Model does not support probability estimates')
        return metadata, pipeline
    except Exception:
        current_app.logger.exception('CivicFix local classifier failed to load')
        return {'state': 'unavailable'}, None


def _load_operational_data():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(status NOT IN ('Resolved','Rejected')),0) AS active
            FROM complaints
        """)
        totals = cursor.fetchone() or {}
        cursor.execute('SELECT COUNT(*) AS amount FROM ai_verified_labels')
        verified_count = (cursor.fetchone() or {}).get('amount', 0)
        cursor.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(decision='same'),0) AS same_issue,
                   COALESCE(SUM(decision='different'),0) AS different_issue
            FROM ai_duplicate_reviews
        """)
        duplicates = cursor.fetchone() or {}
        cursor.execute("""
            SELECT COUNT(*) AS reviewed,
                   COALESCE(SUM(decision = recommended_level),0) AS agreed
            FROM ai_priority_reviews
        """)
        priorities = cursor.fetchone() or {}
        cursor.execute("""
            SELECT cat.category_name, COUNT(*) AS amount
            FROM ai_verified_labels v
            JOIN categories cat ON cat.category_id = v.category_id
            GROUP BY cat.category_id, cat.category_name
            ORDER BY amount DESC, cat.category_name ASC
        """)
        verified_categories = cursor.fetchall()
        cursor.execute("""
            SELECT decision AS level, COUNT(*) AS amount
            FROM ai_priority_reviews
            GROUP BY decision
        """)
        raw_priority_levels = cursor.fetchall()
        level_counts = {str(r['level']): int(r['amount']) for r in raw_priority_levels}
        levels = [{'level': level, 'amount': level_counts.get(level, 0)}
                  for level in ('Critical', 'High', 'Moderate', 'Low')]
        cursor.execute("""
            SELECT c.complaint_id, c.reference_code, c.description,
                   c.status, c.severity, c.created_at,
                   cat.category_name, loc.area_name
            FROM complaints c
            LEFT JOIN categories cat ON cat.category_id = c.category_id
            JOIN locations loc ON loc.location_id = c.location_id
            WHERE c.status NOT IN ('Resolved', 'Rejected')
              AND CHAR_LENGTH(c.description) >= 10
            ORDER BY c.created_at DESC, c.complaint_id DESC
            LIMIT %s
        """, (MAX_QUEUE_SCAN,))
        recent_open = cursor.fetchall()
        return (assemble_operational_metrics(totals, verified_count,
                                             duplicates, priorities,
                                             verified_categories),
                recent_open, levels)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _build_dashboard():
    model, pipeline = _load_model()
    operational, recent, levels = _load_operational_data()
    predictions = None
    if pipeline is not None:
        try:
            predictions = compare_predictions(pipeline, recent)
        except Exception:
            current_app.logger.exception('Classifier batch inference unavailable')
            predictions = None
            model = {**model, 'inference_unavailable': True}
    return model, operational, predictions, levels


def _csv_safe(value):
    """Prevent spreadsheet formula execution from citizen-controlled text fields."""
    field = str(value if value is not None else '')
    if field.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + field
    return field


def register_insights_routes(admin_bp, admin_required):
    @admin_bp.route('/ai-insights')
    @admin_required
    def ai_insights(user):
        try:
            model, operational, predictions, levels = _build_dashboard()
            return render_template('admin_ai_insights.html', user=user,
                                   model=model, op=operational,
                                   predictions=predictions,
                                   priority_levels=levels, db_error=False)
        except mysql.connector.Error:
            current_app.logger.exception('AI Insights data unavailable')
            model, _ = _load_model()
            return render_template('admin_ai_insights.html', user=user,
                                   model=model, op=None,
                                   predictions=None, priority_levels=[], db_error=True), 503

    @admin_bp.route('/ai-insights/export')
    @admin_required
    def ai_insights_export(user):
        """Export only recent mismatches. Excludes citizens' PII and descriptions."""
        model, pipeline = _load_model()
        if pipeline is None:
            return ('Train a local model before exporting the review queue.', 409,
                    {'Content-Type': 'text/plain; charset=utf-8'})
        try:
            _, reports, _ = _load_operational_data()
            compared = compare_predictions(pipeline, reports, max_display=MAX_QUEUE_SCAN)
        except mysql.connector.Error:
            current_app.logger.exception('Unable to export AI review queue')
            return ('AI review export is temporarily unavailable.', 503,
                    {'Content-Type': 'text/plain; charset=utf-8'})
        except Exception:
            current_app.logger.exception('Unable to evaluate AI review queue')
            return ('AI review export is temporarily unavailable.', 503,
                    {'Content-Type': 'text/plain; charset=utf-8'})
        buff = StringIO(newline='')
        writer = csv.writer(buff)
        writer.writerow(['reference', 'citizen_category', 'model_category',
                         'model_estimate_percent', 'status', 'area',
                         'model_training_source', 'review_url'])
        for item in compared['queue']:
            writer.writerow([
                _csv_safe(item['reference_code']), _csv_safe(item['citizen_category']),
                _csv_safe(item['ai_category']), item['estimate'],
                _csv_safe(item['status']), _csv_safe(item['area_name']), model['source'],
                url_for('admin.report_detail', complaint_id=item['complaint_id']),
            ])
        response = make_response('\ufeff' + buff.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = (
            'attachment; filename="civicfix-ai-category-review.csv"'
        )
        response.headers['Cache-Control'] = 'no-store'
        return response
