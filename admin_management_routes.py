"""CivicFix Phase 4 Part 7: real audit log and admin account settings.

This module uses the existing admin_bp Blueprint and admin_required decorator.
Run database/admin_audit_events.sql before registering these routes.
"""
import re

import mysql.connector
from flask import abort, flash, redirect, render_template, request, session, url_for, current_app
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db_connection


def register_management_routes(admin_bp, admin_required):
    # Status changes and assignment notes are already in status_history.
    # New team/profile/password actions use admin_audit_events.
    # Explicit UTF-8 collation for every text field on BOTH UNION branches.
    # Older CivicFix tables can use a different utf8mb4 collation from the
    # newer admin_audit_events table, which otherwise raises MySQL error 1271.
    audit_base = """
        FROM (
            SELECT
                CONVERT(CONCAT('status-', LPAD(h.history_id, 16, '0')) USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS event_key,
                h.changed_at AS happened_at,
                CONVERT('report' USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS event_group,
                CONVERT(CASE WHEN h.old_status <=> h.new_status
                    THEN 'Assignment recorded'
                    ELSE 'Status changed' END USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS action,
                CONVERT(COALESCE(u.full_name, 'Administrator') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS actor,
                CONVERT(c.reference_code USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS subject,
                CONVERT(COALESCE(h.note, '') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS detail,
                c.complaint_id AS report_id
            FROM status_history h
            JOIN complaints c ON c.complaint_id = h.complaint_id
            JOIN users u ON u.user_id = h.changed_by AND u.role = 'admin'

            UNION ALL

            SELECT
                CONVERT(CONCAT('audit-', LPAD(a.event_id, 16, '0')) USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS event_key,
                a.created_at AS happened_at,
                CONVERT(a.target_type USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS event_group,
                CONVERT(a.action USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS action,
                CONVERT(COALESCE(u.full_name, 'Administrator') USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS actor,
                CONVERT(CASE WHEN a.target_type = 'team'
                    THEN CONCAT('Team #', a.target_id)
                    WHEN a.target_type = 'report'
                    THEN CONCAT('Report #', a.target_id)
                    ELSE 'Administrator account' END USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS subject,
                CONVERT(a.detail USING utf8mb4)
                    COLLATE utf8mb4_unicode_ci AS detail,
                CASE WHEN a.target_type = 'report' THEN a.target_id ELSE NULL END AS report_id
            FROM admin_audit_events a
            JOIN users u ON u.user_id = a.actor_id
        ) AS e
    """

    @admin_bp.route('/audit')
    @admin_required
    def audit_log(user):
        group = request.args.get('group', 'all').lower()
        if group not in ('all', 'report', 'team', 'account'):
            group = 'all'
        q = request.args.get('q', '').strip()[:80]
        page = max(1, request.args.get('page', 1, type=int) or 1)
        size = 15
        conditions = []
        args = []
        if group != 'all':
            conditions.append('e.event_group = %s')
            args.append(group)
        if q:
            conditions.append('(' + ' OR '.join(
                f'e.{field} LIKE %s' for field in ('actor','subject','action','detail')
            ) + ')')
            args.extend([f'%{q}%'] * 4)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        connection = get_db_connection()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute('SELECT COUNT(*) AS total ' + audit_base + where, tuple(args))
            total = cursor.fetchone()['total']
            total_pages = max(1, (total + size - 1) // size)
            page = min(page, total_pages)
            cursor.execute(
                'SELECT * ' + audit_base + where +
                ' ORDER BY e.happened_at DESC, e.event_key DESC LIMIT %s OFFSET %s',
                tuple(args + [size, (page - 1) * size])
            )
            events = cursor.fetchall()
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
        return render_template('admin_audit.html', user=user, events=events,
                               group=group, q=q, page=page,
                               total_pages=total_pages, total=total)

    @admin_bp.route('/settings')
    @admin_required
    def settings(user):
        connection = get_db_connection()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """SELECT user_id, full_name, email, role, created_at
                   FROM users WHERE user_id = %s""", (user['user_id'],)
            )
            account = cursor.fetchone()
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
        if account is None:
            session.clear()
            return redirect(url_for('admin.login'))
        return render_template('admin_settings.html', user=user, account=account)

    @admin_bp.route('/settings/profile', methods=['POST'])
    @admin_required
    def update_profile(user):
        name = request.form.get('full_name','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('current_password','')
        if (not 2 <= len(name) <= 100 or len(email) > 190 or
            not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
            flash('Enter a valid name and email.', 'error')
            return redirect(url_for('admin.settings'))
        if not password:
            flash('Enter your current password to save profile changes.', 'error')
            return redirect(url_for('admin.settings'))

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """SELECT full_name, email, password_hash, role
                   FROM users WHERE user_id = %s FOR UPDATE""",
                (user['user_id'],)
            )
            current = cursor.fetchone()
            if current is None or current['role'] != 'admin':
                connection.rollback()
                abort(403)
            if not check_password_hash(current['password_hash'], password):
                connection.rollback()
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('admin.settings'))
            if current['full_name'] == name and current['email'] == email:
                connection.rollback()
                flash('Nothing changed.', 'success')
                return redirect(url_for('admin.settings'))

            cursor.execute(
                'UPDATE users SET full_name = %s, email = %s WHERE user_id = %s',
                (name, email, user['user_id'])
            )
            cursor.execute(
                """INSERT INTO admin_audit_events
                   (actor_id, action, target_type, target_id, detail)
                   VALUES (%s, %s, %s, %s, %s)""",
                (user['user_id'], 'Profile updated', 'account', user['user_id'],
                 'Administrator updated their account profile.')
            )
            connection.commit()
            flash('Profile updated successfully.', 'success')
        except mysql.connector.IntegrityError:
            if connection is not None:
                connection.rollback()
            flash('That email address is already in use.', 'error')
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            current_app.logger.exception('Admin profile update failed')
            flash('Could not save profile changes.', 'error')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
        return redirect(url_for('admin.settings'))

    @admin_bp.route('/settings/password', methods=['POST'])
    @admin_required
    def change_password(user):
        old = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not old or not 12 <= len(new) <= 128 or new != confirm:
            flash('Use a new password of 12–128 characters and confirm it exactly.', 'error')
            return redirect(url_for('admin.settings'))

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                'SELECT password_hash, role FROM users WHERE user_id = %s FOR UPDATE',
                (user['user_id'],)
            )
            current = cursor.fetchone()
            if current is None or current['role'] != 'admin':
                connection.rollback()
                abort(403)
            if not check_password_hash(current['password_hash'], old):
                connection.rollback()
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('admin.settings'))
            if check_password_hash(current['password_hash'], new):
                connection.rollback()
                flash('Choose a different password from your current one.', 'error')
                return redirect(url_for('admin.settings'))

            new_hash = generate_password_hash(new)
            cursor.execute(
                'UPDATE users SET password_hash = %s WHERE user_id = %s',
                (new_hash, user['user_id'])
            )
            cursor.execute(
                """INSERT INTO admin_audit_events
                   (actor_id, action, target_type, target_id, detail)
                   VALUES (%s, %s, %s, %s, %s)""",
                (user['user_id'], 'Password changed', 'account', user['user_id'],
                 'Administrator changed their account password.')
            )
            connection.commit()
            session.clear()  # End this browser's session; other sessions are not revoked.
            flash('Password changed. Sign in again with your new password.', 'success')
            return redirect(url_for('admin.login'))
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            current_app.logger.exception('Admin password update failed')
            flash('Could not update your password.', 'error')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
        return redirect(url_for('admin.settings'))
