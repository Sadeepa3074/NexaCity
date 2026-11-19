"""CivicFix Phase 4 Part 6: read-only municipal analytics.

No demo values, AI scores, user personal details, or schema changes.
Register once on the existing admin Blueprint.
"""

import csv
from datetime import date, timedelta
from io import StringIO

from flask import Response, render_template, request, url_for
from db import get_db_connection


SUPPORTED_WINDOWS = (7, 30, 90)


def _window_days():
    days = request.args.get('days', default=30, type=int)
    return days if days in SUPPORTED_WINDOWS else 30


def _month_start(month_offset, today):
    # month_offset=0 is current month, -5 is five months ago.
    absolute_month = today.year * 12 + today.month - 1 + month_offset
    return date(absolute_month // 12, absolute_month % 12 + 1, 1)


def _volume_rows(cursor, days, today):
    start_day = today - timedelta(days=days - 1)
    # Time window is defined by calendar dates, so today's totals update live.
    cursor.execute(
        """SELECT DATE(created_at) AS day, COUNT(*) AS amount
           FROM complaints
           WHERE created_at >= %s AND created_at < %s
           GROUP BY DATE(created_at)""",
        (start_day, today + timedelta(days=1))
    )
    submitted = {str(row['day']): int(row['amount']) for row in cursor.fetchall()}

    cursor.execute(
        """SELECT DATE(changed_at) AS day,
                  COUNT(DISTINCT complaint_id) AS amount
           FROM status_history
           WHERE new_status = 'Resolved'
             AND changed_at >= %s AND changed_at < %s
           GROUP BY DATE(changed_at)""",
        (start_day, today + timedelta(days=1))
    )
    resolved = {str(row['day']): int(row['amount']) for row in cursor.fetchall()}
    result = []
    for n in range(days):
        day = start_day + timedelta(days=n)
        key = str(day)
        result.append({
            'date': key,
            'label': day.strftime('%d %b'),
            'submitted': submitted.get(key, 0),
            'resolved': resolved.get(key, 0),
        })
    return result


def _read_analytics(cursor, days, today):
    # All-time counts are taken from current complaint statuses.
    cursor.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(status = 'Resolved'), 0) AS resolved,
                  COALESCE(SUM(status NOT IN ('Resolved','Rejected')), 0) AS open_count
           FROM complaints"""
    )
    totals = cursor.fetchone()
    total_reports = int(totals['total'])
    resolved_reports = int(totals['resolved'])

    # All-time category shares, including any unclassified reports.
    cursor.execute(
        """SELECT COALESCE(cat.category_name, 'Uncategorized') AS name,
                  COUNT(*) AS amount
           FROM complaints c
           LEFT JOIN categories cat ON c.category_id = cat.category_id
           GROUP BY COALESCE(cat.category_name, 'Uncategorized')
           ORDER BY amount DESC, name ASC"""
    )
    category_counts = [
        {
            'name': row['name'],
            'amount': int(row['amount']),
            'percentage': round(100 * int(row['amount']) / total_reports, 1)
                          if total_reports else 0,
        }
        for row in cursor.fetchall()
    ]

    # First recorded *non-Submitted* status change (not an SLA guarantee).
    cursor.execute(
        """SELECT COUNT(*) AS sample,
                  AVG(TIMESTAMPDIFF(SECOND, c.created_at, first_action.at_time)) AS avg_seconds
           FROM complaints c
           JOIN (
               SELECT complaint_id, MIN(changed_at) AS at_time
               FROM status_history
               WHERE new_status <> 'Submitted'
               GROUP BY complaint_id
           ) first_action ON first_action.complaint_id = c.complaint_id
           WHERE first_action.at_time >= c.created_at"""
    )
    action_result = cursor.fetchone()

    # First recorded resolution for complaints that remain Resolved.
    # We don't assume an absent history row has a recorded resolution time.
    cursor.execute(
        """SELECT COUNT(*) AS sample,
                  AVG(TIMESTAMPDIFF(SECOND, c.created_at, first_resolved.at_time)) AS avg_seconds
           FROM complaints c
           JOIN (
               SELECT complaint_id, MIN(changed_at) AS at_time
               FROM status_history
               WHERE new_status = 'Resolved'
               GROUP BY complaint_id
           ) first_resolved ON first_resolved.complaint_id = c.complaint_id
           WHERE c.status = 'Resolved' AND first_resolved.at_time >= c.created_at"""
    )
    resolution_result = cursor.fetchone()

    first_month = _month_start(-5, today)
    cursor.execute(
        """SELECT YEAR(first_resolved.at_time) AS resolved_year,
                  MONTH(first_resolved.at_time) AS resolved_month,
                  COUNT(*) AS sample,
                  AVG(TIMESTAMPDIFF(SECOND, c.created_at, first_resolved.at_time)) AS avg_seconds
           FROM complaints c
           JOIN (
               SELECT complaint_id, MIN(changed_at) AS at_time
               FROM status_history
               WHERE new_status = 'Resolved'
               GROUP BY complaint_id
           ) first_resolved ON first_resolved.complaint_id = c.complaint_id
           WHERE c.status = 'Resolved'
             AND first_resolved.at_time >= c.created_at
             AND first_resolved.at_time >= %s
             AND first_resolved.at_time < %s
           GROUP BY YEAR(first_resolved.at_time), MONTH(first_resolved.at_time)""",
        (first_month, today + timedelta(days=1))
    )
    monthly_values = {
        f"{int(row['resolved_year']):04d}-{int(row['resolved_month']):02d}": row
        for row in cursor.fetchall()
    }
    resolution_months = []
    for offset in range(-5, 1):
        month = _month_start(offset, today)
        key = month.strftime('%Y-%m')
        row = monthly_values.get(key)
        resolution_months.append({
            'month': key,
            'label': month.strftime('%b %Y'),
            'sample': int(row['sample']) if row else 0,
            'avg_days': round(float(row['avg_seconds']) / 86400, 2)
                        if row and row['avg_seconds'] is not None else None,
        })

    # Each incident can contain multiple citizen reports, through the bridge table.
    cursor.execute(
        """SELECT COUNT(*) AS sample, AVG(incident_reports.amount) AS avg_reports
           FROM (
               SELECT incident_id, COUNT(*) AS amount
               FROM complaint_incident
               GROUP BY incident_id
           ) incident_reports"""
    )
    incidents = cursor.fetchone()

    # Counts represent active *assignments*, not actual team dispatches.
    cursor.execute(
        """SELECT t.team_name,
                  COUNT(a.assignment_id) AS active_assignments
           FROM maintenance_teams t
           LEFT JOIN assignments a
             ON a.team_id = t.team_id AND a.ended_at IS NULL
           GROUP BY t.team_id, t.team_name
           ORDER BY active_assignments DESC, t.team_name ASC
           LIMIT 8"""
    )
    team_workload = [
        {'name': row['team_name'], 'count': int(row['active_assignments'])}
        for row in cursor.fetchall()
    ]

    volume = _volume_rows(cursor, days, today)

    return {
        'days': days,
        'totals': {
            'total': total_reports,
            'resolved': resolved_reports,
            'open': int(totals['open_count']),
            'resolved_rate': round(100 * resolved_reports / total_reports, 1)
                             if total_reports else None,
        },
        'category_counts': category_counts,
        'first_action_hours': round(float(action_result['avg_seconds']) / 3600, 1)
                              if action_result['avg_seconds'] is not None else None,
        'first_action_sample': int(action_result['sample']),
        'avg_resolution_days': round(float(resolution_result['avg_seconds']) / 86400, 1)
                               if resolution_result['avg_seconds'] is not None else None,
        'resolution_sample': int(resolution_result['sample']),
        'reports_per_incident': round(float(incidents['avg_reports']), 2)
                                if incidents['avg_reports'] is not None else None,
        'incident_sample': int(incidents['sample']),
        'resolution_months': resolution_months,
        'team_workload': team_workload,
        'volume': volume,
        'has_resolution_trend': any(r['sample'] > 0 for r in resolution_months),
        'has_volume': any(r['submitted'] or r['resolved'] for r in volume),
    }


def register_analytics_routes(admin_bp, admin_required):
    """Attach analytics routes to the already-protected admin Blueprint."""

    @admin_bp.route('/analytics')
    @admin_required
    def analytics(user):
        days = _window_days()
        connection = get_db_connection()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            analytics_data = _read_analytics(cursor, days, date.today())
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
        return render_template(
            'admin_analytics.html', user=user,
            data=analytics_data,
        )

    @admin_bp.route('/analytics/export.csv')
    @admin_required
    def analytics_export(user):
        days = _window_days()
        today = date.today()
        connection = get_db_connection()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            data = _volume_rows(cursor, days, today)
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['date', 'reports_submitted', 'reports_resolved_status_events'])
        for day in data:
            writer.writerow([day['date'], day['submitted'], day['resolved']])
        response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = (
            f'attachment; filename="civicfix-activity-{days}days-{today.isoformat()}.csv"'
        )
        response.headers['Cache-Control'] = 'no-store'
        return response
