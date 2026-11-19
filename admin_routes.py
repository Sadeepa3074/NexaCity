"""CivicFix municipal administrator routes.

Register admin_bp once in app.py, after Flask app and CSRF are configured:
    from admin_routes import admin_bp
    app.register_blueprint(admin_bp)
"""

from datetime import date, timedelta
from functools import wraps

import mysql.connector
from flask import (
    Blueprint, abort, flash, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash

from db import get_db_connection
from colombo_service_area import (
    COLOMBO_SOUTH, COLOMBO_NORTH, COLOMBO_WEST, COLOMBO_EAST,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    """Look up the current session's role in MySQL for every admin request."""
    @wraps(view)
    def protected_view(*args, **kwargs):
        user_id = session.get("user_id")
        if user_id is None:
            flash("Please sign in as an administrator.", "error")
            return redirect(url_for("admin.login"))

        connection = get_db_connection()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT user_id, full_name, email, role FROM users "
                "WHERE user_id = %s LIMIT 1", (user_id,)
            )
            user = cursor.fetchone()
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

        if user is None:
            session.clear()
            return redirect(url_for("admin.login"))
        if user["role"] != "admin":
            abort(403)
        return view(user, *args, **kwargs)

    return protected_view


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("admin_login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        flash("Enter your email and password.", "error")
        return redirect(url_for("admin.login"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, password_hash, role FROM users "
            "WHERE email = %s LIMIT 1", (email,)
        )
        user = cursor.fetchone()
    except mysql.connector.Error:
        flash("Login is temporarily unavailable.", "error")
        return redirect(url_for("admin.login"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    if (not user or not user.get("password_hash")
            or not check_password_hash(user["password_hash"], password)
            or user["role"] != "admin"):
        flash("Invalid administrator credentials.", "error")
        return redirect(url_for("admin.login"))

    session.clear()
    session["user_id"] = user["user_id"]
    session.permanent = True
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/dashboard")
@admin_required
def dashboard(user):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        # Counts come from the real complaints table, not demo values.
        cursor.execute("""
            SELECT COUNT(*) AS total,
                COALESCE(SUM(status = 'Submitted'), 0) AS submitted,
                COALESCE(SUM(status = 'Under Review'), 0) AS under_review,
                COALESCE(SUM(status = 'Assigned'), 0) AS assigned,
                COALESCE(SUM(status = 'In Progress'), 0) AS in_progress,
                COALESCE(SUM(status = 'Resolved'), 0) AS resolved,
                COALESCE(SUM(status = 'Rejected'), 0) AS rejected
            FROM complaints
        """)
        stats = cursor.fetchone()
        open_reports = stats["total"] - stats["resolved"] - stats["rejected"]

        cursor.execute("""
            SELECT c.complaint_id, c.reference_code, c.description,
                   c.status, c.severity, c.created_at,
                   u.full_name AS citizen_name,
                   cat.category_name, loc.area_name, loc.address_text
            FROM complaints c
            JOIN users u ON c.user_id = u.user_id
            LEFT JOIN categories cat ON c.category_id = cat.category_id
            JOIN locations loc ON c.location_id = loc.location_id
            ORDER BY c.created_at DESC, c.complaint_id DESC
            LIMIT 6
        """)
        recent_complaints = cursor.fetchall()

        # Latest 250 *open* complaints that have coordinates.
        # More advanced clustering and full history will be added later.
        cursor.execute("""
            SELECT c.reference_code, c.description, c.status, c.severity,
                   loc.latitude, loc.longitude, loc.area_name,
                   cat.category_name
            FROM complaints c
            JOIN locations loc ON c.location_id = loc.location_id
            LEFT JOIN categories cat ON c.category_id = cat.category_id
            WHERE c.status NOT IN ('Resolved', 'Rejected')
              AND loc.latitude IS NOT NULL
              AND loc.longitude IS NOT NULL
              AND loc.latitude BETWEEN %s AND %s
              AND loc.longitude BETWEEN %s AND %s
            ORDER BY c.created_at DESC, c.complaint_id DESC
            LIMIT 250
        """, (COLOMBO_SOUTH, COLOMBO_NORTH, COLOMBO_WEST, COLOMBO_EAST))
        map_points = []
        for item in cursor.fetchall():
            map_points.append({
                "reference": item["reference_code"],
                "description": item["description"][:140],
                "status": item["status"],
                "severity": item["severity"],
                "area": item["area_name"] or "Location selected",
                "category": item["category_name"] or "Uncategorized",
                "lat": float(item["latitude"]),
                "lng": float(item["longitude"]),
            })

        # Actual database activity from the last 7 calendar days.
        today = date.today()
        first_day = today - timedelta(days=6)
        cursor.execute("""
            SELECT DATE(created_at) AS activity_date,
                   COUNT(*) AS amount
            FROM complaints
            WHERE created_at >= %s
            GROUP BY DATE(created_at)
        """, (first_day,))
        created_by_day = {str(row["activity_date"]): row["amount"]
                          for row in cursor.fetchall()}

        cursor.execute("""
            SELECT DATE(changed_at) AS activity_date,
                   COUNT(DISTINCT complaint_id) AS amount
            FROM status_history
            WHERE new_status = 'Resolved' AND changed_at >= %s
            GROUP BY DATE(changed_at)
        """, (first_day,))
        resolved_by_day = {str(row["activity_date"]): row["amount"]
                           for row in cursor.fetchall()}

        weekly_activity = []
        for i in range(7):
            day = first_day + timedelta(days=i)
            key = str(day)
            weekly_activity.append({
                "label": day.strftime("%a"),
                "date": day.strftime("%d %b"),
                "submitted": created_by_day.get(key, 0),
                "resolved": resolved_by_day.get(key, 0),
            })
        largest_value = max(
            1, *(max(d["submitted"], d["resolved"]) for d in weekly_activity)
        )
        for day in weekly_activity:
            day["submitted_height"] = round(100 * day["submitted"] / largest_value)
            day["resolved_height"] = round(100 * day["resolved"] / largest_value)
        has_weekly_activity = any(
            day["submitted"] or day["resolved"] for day in weekly_activity
        )

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template(
        "admin_dashboard.html",
        user=user,
        stats=stats,
        open_reports=open_reports,
        recent_complaints=recent_complaints,
        map_points=map_points,
        weekly_activity=weekly_activity,
        has_weekly_activity=has_weekly_activity,
    )


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("admin.login"))


# ---------- REPORT MANAGEMENT (PHASE 4, PART 2) ----------

REPORT_STATUSES = (
    'Submitted', 'Under Review', 'Assigned', 'In Progress', 'Resolved', 'Rejected'
)

# Assignment to a team is handled by /admin/reports/<id>/assign.
# Only that transaction can set status to Assigned.
ALLOWED_NEXT_STATUSES = {
    'Submitted': ('Under Review', 'Rejected'),
    'Under Review': ('Rejected',),
    'Assigned': ('In Progress', 'Under Review', 'Rejected'),
    'In Progress': ('Resolved', 'Under Review'),
    'Resolved': (),
    'Rejected': ('Under Review',),
}


@admin_bp.route('/reports')
@admin_required
def reports(user):
    """Paginated reports list, with server-side status and keyword filters."""
    status = request.args.get('status', 'All')
    if status not in ('All',) + REPORT_STATUSES:
        status = 'All'

    search_term = request.args.get('q', '').strip()[:100]
    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = 15

    where_parts = []
    params = []
    if status != 'All':
        where_parts.append('c.status = %s')
        params.append(status)

    if search_term:
        where_parts.append(
            '(c.reference_code LIKE %s OR c.description LIKE %s '
            'OR u.full_name LIKE %s OR l.area_name LIKE %s)'
        )
        like = f'%{search_term}%'
        params.extend([like, like, like, like])

    where_sql = (' WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        joins = (
            ' FROM complaints c '
            'JOIN users u ON c.user_id = u.user_id '
            'JOIN locations l ON c.location_id = l.location_id '
            'LEFT JOIN categories cat ON c.category_id = cat.category_id '
        )
        cursor.execute('SELECT COUNT(*) AS amount' + joins + where_sql,
                       tuple(params))
        total = cursor.fetchone()['amount']
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)

        cursor.execute(
            '''SELECT c.complaint_id, c.reference_code, c.description,
                      c.status, c.severity, c.created_at,
                      u.full_name AS citizen_name,
                      cat.category_name, l.area_name, l.address_text
            ''' + joins + where_sql +
            ' ORDER BY c.created_at DESC, c.complaint_id DESC '
            'LIMIT %s OFFSET %s',
            tuple(params + [per_page, (page - 1) * per_page])
        )
        report_rows = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template(
        'admin_reports.html',
        user=user, reports=report_rows,
        status=status, search_term=search_term, statuses=REPORT_STATUSES,
        total=total, page=page, total_pages=total_pages
    )


@admin_bp.route('/reports/<int:complaint_id>')
@admin_required
def report_detail(user, complaint_id):
    """An administrator may inspect a report and its audited status history."""
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            '''SELECT c.complaint_id, c.reference_code, c.description,
                      c.status, c.severity, c.image_path, c.created_at,
                      c.updated_at, u.full_name AS citizen_name,
                      u.email AS citizen_email, cat.category_name,
                      l.address_text, l.area_name, l.latitude, l.longitude
               FROM complaints c
               JOIN users u ON c.user_id = u.user_id
               LEFT JOIN categories cat ON c.category_id = cat.category_id
               JOIN locations l ON c.location_id = l.location_id
               WHERE c.complaint_id = %s''',
            (complaint_id,)
        )
        report = cursor.fetchone()
        if report is None:
            abort(404)

        cursor.execute(
            '''SELECT h.old_status, h.new_status, h.note, h.changed_at,
                      u.full_name AS changed_by_name
               FROM status_history h
               LEFT JOIN users u ON h.changed_by = u.user_id
               WHERE h.complaint_id = %s
               ORDER BY h.changed_at ASC, h.history_id ASC''',
            (complaint_id,)
        )
        history = cursor.fetchall()

        # Current team assignment for this complaint's incident.
        cursor.execute(
            '''SELECT a.assignment_id, a.assigned_at, a.note,
                      t.team_id, t.team_name, t.specialty
               FROM complaint_incident ci
               JOIN assignments a ON a.incident_id = ci.incident_id
               JOIN maintenance_teams t ON t.team_id = a.team_id
               WHERE ci.complaint_id = %s AND a.ended_at IS NULL
               ORDER BY a.assignment_id DESC LIMIT 1''',
            (complaint_id,)
        )
        active_assignment = cursor.fetchone()

        cursor.execute(
            '''SELECT a.assigned_at, a.ended_at, a.note,
                      t.team_name, u.full_name AS officer_name
               FROM complaint_incident ci
               JOIN assignments a ON a.incident_id = ci.incident_id
               JOIN maintenance_teams t ON t.team_id = a.team_id
               LEFT JOIN users u ON u.user_id = a.assigned_by
               WHERE ci.complaint_id = %s
               ORDER BY a.assigned_at DESC, a.assignment_id DESC''',
            (complaint_id,)
        )
        assignment_history = cursor.fetchall()

        cursor.execute(
            '''SELECT team_id, team_name, specialty
               FROM maintenance_teams WHERE is_active = 1
               ORDER BY team_name'''
        )
        available_teams = cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    # The existing full-detail page remains the fallback when JavaScript is off.
    template_name = ('admin_report_drawer_content.html'
                     if request.args.get('drawer') == '1'
                     else 'admin_report_detail.html')
    return render_template(
        template_name,
        user=user, report=report, history=history,
        allowed_next=ALLOWED_NEXT_STATUSES.get(report['status'], ()),
        active_assignment=active_assignment,
        assignment_history=assignment_history,
        available_teams=available_teams,
        can_assign=report['status'] in ('Under Review', 'Assigned', 'In Progress'),
    )


@admin_bp.route('/reports/<int:complaint_id>/status', methods=['POST'])
@admin_required
def update_report_status(user, complaint_id):
    """Atomically update a report and append a citizen-visible history event."""
    requested_status = request.form.get('new_status', '').strip()
    note = request.form.get('note', '').strip()

    if requested_status not in REPORT_STATUSES:
        flash('Choose a valid status.', 'error')
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

    if not 5 <= len(note) <= 500:
        flash('Please enter a note between 5 and 500 characters.', 'error')
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # FOR UPDATE locks the row until COMMIT so simultaneous edits cannot
        # silently overwrite the previous status between check and update.
        cursor.execute(
            'SELECT status FROM complaints WHERE complaint_id = %s FOR UPDATE',
            (complaint_id,)
        )
        report = cursor.fetchone()
        if report is None:
            connection.rollback()
            abort(404)

        old_status = report['status']
        if requested_status not in ALLOWED_NEXT_STATUSES.get(old_status, ()):
            connection.rollback()
            flash('That status change is not allowed from the current status.',
                  'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        cursor.execute(
            'UPDATE complaints SET status = %s WHERE complaint_id = %s',
            (requested_status, complaint_id)
        )

        # When an issue leaves the active-work states, close any active
        # team assignment so workload cards remain accurate.
        if requested_status not in ('Assigned', 'In Progress'):
            cursor.execute(
                '''UPDATE assignments a
                   JOIN complaint_incident ci ON a.incident_id = ci.incident_id
                   SET a.ended_at = NOW()
                   WHERE ci.complaint_id = %s AND a.ended_at IS NULL''',
                (complaint_id,)
            )

        cursor.execute(
            '''INSERT INTO status_history
               (complaint_id, changed_by, old_status, new_status, note)
               VALUES (%s, %s, %s, %s, %s)''',
            (complaint_id, user['user_id'], old_status, requested_status, note)
        )
        connection.commit()
        flash(f'Status updated to {requested_status}. The citizen can now see it.',
              'success')

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        from flask import current_app
        current_app.logger.exception('Report status update failed')
        flash('Could not save the status change. Please try again.', 'error')
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return redirect(url_for('admin.report_detail', complaint_id=complaint_id))


@admin_bp.route('/reports/<int:complaint_id>/photo')
@admin_required
def report_photo(user, complaint_id):
    """Serve the private photo only after authorization and DB lookup."""
    from pathlib import Path
    from flask import current_app, send_from_directory

    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute('SELECT image_path FROM complaints WHERE complaint_id = %s',
                       (complaint_id,))
        report = cursor.fetchone()
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    if not report or not report['image_path']:
        abort(404)

    directory = Path(current_app.instance_path) / 'complaint_photos'
    return send_from_directory(
        directory, report['image_path'], mimetype='image/jpeg'
    )


# ---------- MAINTENANCE TEAMS (PHASE 4, PART 3) ----------
# These are local prototype teams, not actual municipal departments.
# The database migration team_assignments.sql must be applied first.


def _team_values(form):
    """Validate team details submitted by an authenticated administrator."""
    name = form.get('team_name', '').strip()
    specialty = form.get('specialty', '').strip()
    try:
        members = int(form.get('member_count', ''))
    except (TypeError, ValueError):
        members = 0
    if not 3 <= len(name) <= 100:
        return None, 'Team name must contain 3–100 characters.'
    if not 3 <= len(specialty) <= 100:
        return None, 'Specialty must contain 3–100 characters.'
    if not 1 <= members <= 500:
        return None, 'Member count must be between 1 and 500.'
    return (name, specialty, members), None


@admin_bp.route('/teams')
@admin_required
def teams(user):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        # A workload is the count of *active assignment records* rather than
        # synthetic numbers. No teams are pre-populated.
        cursor.execute(
            '''SELECT t.team_id, t.team_name, t.specialty,
                      t.member_count, t.is_active,
                      COALESCE(w.open_assignments, 0) AS open_assignments,
                      COALESCE(w.in_progress, 0) AS in_progress
               FROM maintenance_teams t
               LEFT JOIN (
                   SELECT a.team_id,
                          COUNT(DISTINCT a.assignment_id) AS open_assignments,
                          COUNT(DISTINCT CASE WHEN c.status = 'In Progress'
                               THEN a.assignment_id END) AS in_progress
                   FROM assignments a
                   JOIN complaint_incident ci ON ci.incident_id = a.incident_id
                   JOIN complaints c ON c.complaint_id = ci.complaint_id
                   WHERE a.ended_at IS NULL
                     AND c.status IN ('Assigned', 'In Progress')
                   GROUP BY a.team_id
               ) w ON w.team_id = t.team_id
               ORDER BY t.is_active DESC, t.team_name ASC'''
        )
        team_rows = cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template('admin_teams.html', user=user, teams=team_rows)


@admin_bp.route('/teams/new', methods=['GET', 'POST'])
@admin_required
def new_team(user):
    if request.method == 'GET':
        return render_template('admin_team_form.html', user=user, team=None)
    values, error = _team_values(request.form)
    if error:
        flash(error, 'error')
        return redirect(url_for('admin.new_team'))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            '''INSERT INTO maintenance_teams
               (team_name, specialty, member_count, is_active)
               VALUES (%s, %s, %s, 1)''', values
        )
        team_id = cursor.lastrowid
        cursor.execute(
            '''INSERT INTO admin_audit_events
               (actor_id, action, target_type, target_id, detail)
               VALUES (%s, %s, %s, %s, %s)''',
            (user['user_id'], 'Team created', 'team', team_id,
             f'Created maintenance team: {values[0]}.')
        )
        connection.commit()
        flash('Maintenance team created.', 'success')
        return redirect(url_for('admin.teams'))
    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        flash('A team with that name already exists.', 'error')
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        from flask import current_app
        current_app.logger.exception('Unable to create maintenance team')
        flash('Could not create team. Check the database.', 'error')
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
    return redirect(url_for('admin.new_team'))


@admin_bp.route('/teams/<int:team_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_team(user, team_id):
    connection = get_db_connection()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            '''SELECT team_id, team_name, specialty, member_count, is_active
               FROM maintenance_teams WHERE team_id = %s''', (team_id,)
        )
        team = cursor.fetchone()
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
    if team is None:
        abort(404)
    if request.method == 'GET':
        return render_template('admin_team_form.html', user=user, team=team)

    values, error = _team_values(request.form)
    if error:
        flash(error, 'error')
        return redirect(url_for('admin.edit_team', team_id=team_id))
    is_active = request.form.get('is_active') == '1'

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            'SELECT team_id FROM maintenance_teams WHERE team_id = %s FOR UPDATE',
            (team_id,)
        )
        if cursor.fetchone() is None:
            connection.rollback()
            abort(404)
        if not is_active:
            # Do not silently deactivate a team that still has active work.
            cursor.execute(
                '''SELECT COUNT(*) AS amount
                   FROM assignments WHERE team_id = %s AND ended_at IS NULL''',
                (team_id,)
            )
            if cursor.fetchone()['amount']:
                connection.rollback()
                flash('Reassign or close active work before deactivating this team.',
                      'error')
                return redirect(url_for('admin.edit_team', team_id=team_id))

        cursor.execute(
            '''UPDATE maintenance_teams
               SET team_name = %s, specialty = %s, member_count = %s,
                   is_active = %s WHERE team_id = %s''',
            (*values, int(is_active), team_id)
        )
        cursor.execute(
            '''INSERT INTO admin_audit_events
               (actor_id, action, target_type, target_id, detail)
               VALUES (%s, %s, %s, %s, %s)''',
            (user['user_id'], 'Team updated', 'team', team_id,
             f'Updated team: {values[0]}; active: {"yes" if is_active else "no"}.')
        )
        connection.commit()
        flash('Team details saved.', 'success')
        return redirect(url_for('admin.teams'))
    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        flash('A team with that name already exists.', 'error')
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        from flask import current_app
        current_app.logger.exception('Unable to update maintenance team')
        flash('Could not save team details.', 'error')
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
    return redirect(url_for('admin.edit_team', team_id=team_id))


@admin_bp.route('/reports/<int:complaint_id>/assign', methods=['POST'])
@admin_required
def assign_report(user, complaint_id):
    """Assign/reassign a complaint's incident and record its status atomically."""
    try:
        team_id = int(request.form.get('team_id', ''))
    except (ValueError, TypeError):
        team_id = 0
    note = request.form.get('note', '').strip()
    if team_id <= 0 or not 5 <= len(note) <= 500:
        flash('Choose a team and enter a note of 5–500 characters.', 'error')
        return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Lock the complaint to serialize concurrent team assignments.
        cursor.execute(
            '''SELECT complaint_id, status, description, category_id
               FROM complaints WHERE complaint_id = %s FOR UPDATE''',
            (complaint_id,)
        )
        report = cursor.fetchone()
        if report is None:
            connection.rollback()
            abort(404)
        if report['status'] not in ('Under Review', 'Assigned', 'In Progress'):
            connection.rollback()
            flash('Move the complaint to Under Review before assigning it.',
                  'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        cursor.execute(
            '''SELECT team_id, team_name FROM maintenance_teams
               WHERE team_id = %s AND is_active = 1 FOR UPDATE''', (team_id,)
        )
        team = cursor.fetchone()
        if team is None:
            connection.rollback()
            flash('The selected maintenance team is not available.', 'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))

        cursor.execute(
            'SELECT incident_id FROM complaint_incident WHERE complaint_id = %s',
            (complaint_id,)
        )
        link = cursor.fetchone()
        if link:
            incident_id = link['incident_id']
        else:
            # One complaint per incident at this stage. The association table
            # allows genuine multi-report incident grouping in a future phase.
            cursor.execute(
                '''INSERT INTO incidents (title, category_id)
                   VALUES (%s, %s)''',
                (report['description'][:180], report['category_id'])
            )
            incident_id = cursor.lastrowid
            cursor.execute(
                '''INSERT INTO complaint_incident (complaint_id, incident_id)
                   VALUES (%s, %s)''', (complaint_id, incident_id)
            )

        cursor.execute(
            '''SELECT assignment_id, team_id
               FROM assignments
               WHERE incident_id = %s AND ended_at IS NULL
               ORDER BY assignment_id DESC LIMIT 1 FOR UPDATE''',
            (incident_id,)
        )
        previous = cursor.fetchone()
        if previous and previous['team_id'] == team_id:
            connection.rollback()
            flash('This report is already assigned to that team.', 'error')
            return redirect(url_for('admin.report_detail', complaint_id=complaint_id))
        if previous:
            cursor.execute(
                '''UPDATE assignments SET ended_at = NOW()
                   WHERE incident_id = %s AND ended_at IS NULL''',
                (incident_id,)
            )

        cursor.execute(
            '''INSERT INTO assignments (incident_id, team_id, assigned_by, note)
               VALUES (%s, %s, %s, %s)''',
            (incident_id, team_id, user['user_id'], note)
        )

        old_status = report['status']
        new_status = 'Assigned' if old_status == 'Under Review' else old_status
        if new_status != old_status:
            cursor.execute(
                'UPDATE complaints SET status = %s WHERE complaint_id = %s',
                (new_status, complaint_id)
            )

        action_label = 'Reassigned' if previous else 'Assigned'
        citizen_note = f'{action_label} to {team["team_name"]}. {note}'
        cursor.execute(
            '''INSERT INTO status_history
               (complaint_id, changed_by, old_status, new_status, note)
               VALUES (%s, %s, %s, %s, %s)''',
            (complaint_id, user['user_id'], old_status, new_status, citizen_note)
        )
        connection.commit()
        flash(f'Report assigned to {team["team_name"]}.', 'success')

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        from flask import current_app
        current_app.logger.exception('Maintenance team assignment failed')
        flash('Could not assign this report. Check the database.', 'error')
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
    return redirect(url_for('admin.report_detail', complaint_id=complaint_id))


# Map & Hotspots (Phase 4 Part 5). Reuse the same admin Blueprint/authentication.
from admin_map_routes import register_map_routes
register_map_routes(admin_bp, admin_required)

# Analytics (Phase 4 Part 6): keeps all existing admin routes intact.
from admin_analytics_routes import register_analytics_routes
register_analytics_routes(admin_bp, admin_required)


# Admin audit log and account settings (Phase 4 Part 7).
from admin_management_routes import register_management_routes
register_management_routes(admin_bp, admin_required)


# Phase 5 Part 1: optional trained category classifier and officer-verified labels.
from ai_admin_routes import register_ai_routes
register_ai_routes(admin_bp, admin_required)
