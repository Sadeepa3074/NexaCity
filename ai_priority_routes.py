"""Admin-only priority recommendation and officer-confirmed priority reviews."""
import mysql.connector
from flask import abort, current_app, flash, redirect, request, url_for

from ai_priority_engine import score_priority
from db import get_db_connection

LEVELS = ('Low', 'Moderate', 'High', 'Critical')


def _duplicate_count(cursor, complaint_id):
    cursor.execute('''
        SELECT COUNT(*) AS amount FROM ai_duplicate_reviews
        WHERE decision = 'same' AND
              (complaint_low_id = %s OR complaint_high_id = %s)
    ''', (complaint_id, complaint_id))
    return cursor.fetchone()['amount']


def register_priority_routes(admin_bp, admin_required):
    @admin_bp.context_processor
    def priority_template_context():
        def civicfix_priority(report):
            """Live calculation on each view, followed by the saved officer review."""
            connection = None
            cursor = None
            try:
                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)
                duplicates = _duplicate_count(cursor, report['complaint_id'])
                cursor.execute('''
                    SELECT r.decision, r.note, r.score_at_review,
                           r.recommended_level, r.scoring_version,
                           r.reviewed_at, u.full_name AS officer_name
                    FROM ai_priority_reviews r
                    JOIN users u ON u.user_id = r.reviewed_by
                    WHERE r.complaint_id = %s LIMIT 1
                ''', (report['complaint_id'],))
                review = cursor.fetchone()
                return {'state': 'ready',
                        'recommendation': score_priority(report, duplicates),
                        'confirmed_duplicates': duplicates,
                        'review': review}
            except mysql.connector.Error:
                current_app.logger.exception('Priority scoring database unavailable')
                return {'state': 'database_unavailable', 'recommendation': None,
                        'confirmed_duplicates': None, 'review': None}
            finally:
                if cursor is not None:
                    cursor.close()
                if connection is not None:
                    connection.close()
        return {'civicfix_priority': civicfix_priority}

    @admin_bp.route('/reports/<int:complaint_id>/priority-review', methods=['POST'])
    @admin_required
    def review_priority(user, complaint_id):
        decision = request.form.get('decision', '').strip()
        note = request.form.get('note', '').strip()
        if decision not in LEVELS or not (5 <= len(note) <= 500):
            flash('Select a priority and enter a review reason (5–500 characters).', 'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('''
                SELECT complaint_id, description, severity, status, created_at
                FROM complaints WHERE complaint_id = %s FOR UPDATE
            ''', (complaint_id,))
            report = cursor.fetchone()
            if report is None:
                connection.rollback()
                abort(404)
            if report['status'] in ('Resolved', 'Rejected'):
                connection.rollback()
                flash('Closed reports cannot receive new active-priority reviews.', 'error')
                return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

            duplicate_count = _duplicate_count(cursor, complaint_id)
            recommendation = score_priority(report, duplicate_count)
            cursor.execute('''
                INSERT INTO ai_priority_reviews
                  (complaint_id, decision, note, score_at_review,
                   recommended_level, scoring_version, reviewed_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  decision = VALUES(decision), note = VALUES(note),
                  score_at_review = VALUES(score_at_review),
                  recommended_level = VALUES(recommended_level),
                  scoring_version = VALUES(scoring_version),
                  reviewed_by = VALUES(reviewed_by), reviewed_at = CURRENT_TIMESTAMP
            ''', (complaint_id, decision, note, recommendation['score'],
                  recommendation['level'], recommendation['version'], user['user_id']))
            cursor.execute('''
                INSERT INTO admin_audit_events
                  (actor_id, action, target_type, target_id, detail)
                VALUES (%s, %s, 'report', %s, %s)
            ''', (user['user_id'], 'Priority review saved', complaint_id,
                  f'Officer chose {decision} priority; current rule suggestion '
                  f'{recommendation["level"]} ({recommendation["score"]}/100).'))
            connection.commit()
            flash('Officer priority review saved and audited. No report status or team was changed.',
                  'success')
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            current_app.logger.exception('Unable to save priority review')
            flash('Priority review could not be saved. Check the Phase 5 Part 3 migration.',
                  'error')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))
