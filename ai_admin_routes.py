"""Phase 5 Part 1: attach local ML inference and verified labeling to existing admin blueprint."""
import mysql.connector
from flask import abort, current_app, flash, redirect, request, url_for

from ai_classifier import predict_complaint
from db import get_db_connection


def register_ai_routes(admin_bp, admin_required):
    @admin_bp.context_processor
    def ai_context_provider():
        def civicfix_ai_context(report):
            prediction = predict_complaint(report['description'])
            connection = None
            cursor = None
            categories = []
            verified = None
            verified_count = 0
            try:
                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)
                cursor.execute('SELECT category_id, category_name FROM categories ORDER BY category_name')
                categories = cursor.fetchall()
                cursor.execute(
                    'SELECT category_id FROM ai_verified_labels WHERE complaint_id = %s',
                    (report['complaint_id'],)
                )
                label = cursor.fetchone()
                verified = label['category_id'] if label else None
                cursor.execute('SELECT COUNT(*) AS total FROM ai_verified_labels')
                verified_count = cursor.fetchone()['total']
            except mysql.connector.Error:
                current_app.logger.exception('Cannot retrieve AI training labels')
                # A missing migration displays a clear message instead of 500.
                return {'prediction': prediction, 'categories': [],
                        'verified': None, 'verified_count': 0, 'database_unavailable': True}
            finally:
                if cursor is not None:
                    cursor.close()
                if connection is not None:
                    connection.close()
            return {'prediction': prediction, 'categories': categories,
                    'verified': verified, 'verified_count': verified_count,
                    'database_unavailable': False}
        return {'civicfix_ai_context': civicfix_ai_context}

    @admin_bp.route('/reports/<int:complaint_id>/ai-label', methods=['POST'])
    @admin_required
    def verify_report_category(user, complaint_id):
        """Officer confirms a training label; does NOT override citizen's category."""
        try:
            category_id = int(request.form.get('category_id', ''))
        except (TypeError, ValueError):
            category_id = 0
        if category_id <= 0:
            flash('Choose a valid category to verify.', 'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('SELECT complaint_id FROM complaints WHERE complaint_id = %s FOR UPDATE',
                           (complaint_id,))
            if not cursor.fetchone():
                connection.rollback()
                abort(404)
            cursor.execute('SELECT category_name FROM categories WHERE category_id = %s',
                           (category_id,))
            category = cursor.fetchone()
            if not category:
                connection.rollback()
                flash('The selected category no longer exists.', 'error')
                return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

            cursor.execute('''
                INSERT INTO ai_verified_labels (complaint_id, category_id, verified_by)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE category_id = %s,
                                        verified_by = %s, verified_at = CURRENT_TIMESTAMP
            ''', (complaint_id, category_id, user['user_id'], category_id, user['user_id']))
            cursor.execute('''
                INSERT INTO admin_audit_events (actor_id, action, target_type, target_id, detail)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user['user_id'], 'AI training label verified', 'report', complaint_id,
                  f'Confirmed category for ML training: {category["category_name"]}.'))
            connection.commit()
            flash('Verified category saved for future model training. Retrain the model to use it.',
                  'success')
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            current_app.logger.exception('Unable to verify AI training label')
            flash('Could not save the training label. Check the database migration.', 'error')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

    # Phase 5 Part 2: location-aware duplicate suggestions and officer review.
    # Registered on the SAME admin Blueprint with its existing auth wrapper.
    from ai_duplicate_routes import register_duplicate_routes
    register_duplicate_routes(admin_bp, admin_required)

    # Phase 5 Part 3: explainable rule scoring with separate officer review.
    from ai_priority_routes import register_priority_routes
    register_priority_routes(admin_bp, admin_required)


    # Phase 5 Part 4: read-only model evaluation and human review analytics.
    from ai_insights_routes import register_insights_routes
    register_insights_routes(admin_bp, admin_required)
