"""Admin-only duplicate-suggestion and human-review integration for CivicFix."""

import mysql.connector
from flask import abort, current_app, flash, redirect, request, url_for

from ai_duplicate_engine import geographic_bounding_box, score_candidates
from db import get_db_connection


CANDIDATES_SQL = """
    SELECT c.complaint_id, c.reference_code, c.description, c.status,
           l.latitude, l.longitude, cat.category_name
    FROM complaints c
    JOIN locations l ON l.location_id = c.location_id
    LEFT JOIN categories cat ON cat.category_id = c.category_id
    WHERE c.complaint_id != %s
      AND l.latitude BETWEEN %s AND %s
      AND l.longitude BETWEEN %s AND %s
    ORDER BY c.created_at DESC, c.complaint_id DESC
    LIMIT 500
"""


def _get_suggestions(cursor, report):
    if report.get('latitude') is None or report.get('longitude') is None:
        return []
    lo_lat, hi_lat, lo_lon, hi_lon = geographic_bounding_box(
        report['latitude'], report['longitude'])
    cursor.execute(CANDIDATES_SQL, (report['complaint_id'],
                                   lo_lat, hi_lat, lo_lon, hi_lon))
    return score_candidates(report, cursor.fetchall())


def register_duplicate_routes(admin_bp, admin_required):
    @admin_bp.context_processor
    def duplicate_panel_context():
        def civicfix_duplicates(report):
            """Render real candidates on the drawer and full detail page."""
            if report.get('latitude') is None or report.get('longitude') is None:
                return {'state': 'missing_coordinates', 'matches': []}
            connection = None
            cursor = None
            try:
                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)
                matches = _get_suggestions(cursor, report)
                cursor.execute("""
                    SELECT complaint_low_id, complaint_high_id, decision, reviewed_at
                    FROM ai_duplicate_reviews
                    WHERE complaint_low_id = %s OR complaint_high_id = %s
                """, (report['complaint_id'], report['complaint_id']))
                reviews = {}
                for record in cursor.fetchall():
                    other_id = (record['complaint_high_id']
                                if record['complaint_low_id'] == report['complaint_id']
                                else record['complaint_low_id'])
                    reviews[other_id] = record['decision']
                for item in matches:
                    item['decision'] = reviews.get(item['complaint_id'])
                return {'state': 'ready', 'matches': matches}
            except mysql.connector.Error:
                current_app.logger.exception('Unable to find duplicate reports')
                return {'state': 'database_unavailable', 'matches': []}
            except Exception:
                current_app.logger.exception('Duplicate matching engine unavailable')
                return {'state': 'engine_unavailable', 'matches': []}
            finally:
                if cursor is not None:
                    cursor.close()
                if connection is not None:
                    connection.close()
        return {'civicfix_duplicates': civicfix_duplicates}

    @admin_bp.route('/reports/<int:complaint_id>/duplicate-review', methods=['POST'])
    @admin_required
    def review_duplicate(user, complaint_id):
        """Human review only; no automatic incident merge or team reassignment."""
        try:
            other_id = int(request.form.get('other_complaint_id', ''))
        except (TypeError, ValueError):
            other_id = 0
        decision = request.form.get('decision', '')
        if other_id <= 0 or other_id == complaint_id or decision not in ('same', 'different'):
            flash('Select a valid candidate and review decision.', 'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT c.complaint_id, c.reference_code, c.description,
                       l.latitude, l.longitude
                FROM complaints c JOIN locations l ON l.location_id = c.location_id
                WHERE c.complaint_id IN (%s, %s)
                ORDER BY c.complaint_id FOR UPDATE
            """, (complaint_id, other_id))
            rows = {row['complaint_id']: row for row in cursor.fetchall()}
            if len(rows) != 2:
                connection.rollback()
                abort(404)
            # Check candidate eligibility using the SAME geographically
            # filtered corpus and ranking as the panel (not just two texts).
            left, right = rows[complaint_id], rows[other_id]
            suggestions = _get_suggestions(cursor, left)
            if not any(match['complaint_id'] == other_id for match in suggestions):
                connection.rollback()
                flash('This report is not in the current nearby-match shortlist.', 'error')
                return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

            low, high = sorted((complaint_id, other_id))
            cursor.execute("""
                INSERT INTO ai_duplicate_reviews
                    (complaint_low_id, complaint_high_id, decision, reviewed_by)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    decision = VALUES(decision),
                    reviewed_by = VALUES(reviewed_by),
                    reviewed_at = CURRENT_TIMESTAMP
            """, (low, high, decision, user['user_id']))
            action = 'same issue' if decision == 'same' else 'different issues'
            cursor.execute("""
                INSERT INTO admin_audit_events
                    (actor_id, action, target_type, target_id, detail)
                VALUES (%s, %s, %s, %s, %s)
            """, (user['user_id'], 'Duplicate review saved', 'report', complaint_id,
                  f'Officer marked reports {left["reference_code"]} and '
                  f'{right["reference_code"]} as {action}.'))
            connection.commit()
            flash(f'Duplicate review saved: {action}. No incidents or teams were merged.',
                  'success')
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            current_app.logger.exception('Unable to save duplicate review')
            flash('Could not save review. Check the Phase 5 Part 2 database migration.',
                  'error')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))
