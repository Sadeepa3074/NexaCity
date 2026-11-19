# CivicFix Part 5: read-only administrator map and report concentration analysis.
# Registered by admin_routes.py. No new tables, synthetic data, or public endpoints.
import math

from flask import render_template, request, url_for
from db import get_db_connection
from colombo_service_area import (
    COLOMBO_SOUTH, COLOMBO_NORTH, COLOMBO_WEST, COLOMBO_EAST,
)


def register_map_routes(admin_bp, admin_required):
    @admin_bp.route('/map')
    @admin_required
    def map_hotspots(user):
        # All incoming values are validated, SQL uses bound parameters.
        raw_category = request.args.get('category', 'all')
        try:
            chosen_category = int(raw_category) if raw_category != 'all' else None
            if chosen_category is not None and chosen_category <= 0:
                chosen_category = None
        except (ValueError, TypeError):
            chosen_category = None
        status_filter = request.args.get('status', 'open')
        if status_filter not in ('open', 'all', 'resolved'):
            status_filter = 'open'
        area_query = request.args.get('area', '').strip()[:80]

        where = [
            'loc.latitude IS NOT NULL', 'loc.longitude IS NOT NULL',
            'loc.latitude BETWEEN %s AND %s',
            'loc.longitude BETWEEN %s AND %s'
        ]
        params = [COLOMBO_SOUTH, COLOMBO_NORTH, COLOMBO_WEST, COLOMBO_EAST]
        if chosen_category is not None:
            where.append('c.category_id = %s')
            params.append(chosen_category)
        if status_filter == 'open':
            where.append("c.status NOT IN ('Resolved', 'Rejected')")
        elif status_filter == 'resolved':
            where.append("c.status = 'Resolved'")
        if area_query:
            # A percent sign in user input would match wildcards; escape it.
            safe_area = area_query.replace('!', '!!').replace('%', '!%').replace('_', '!_')
            where.append("(loc.area_name LIKE %s ESCAPE '!' OR loc.address_text LIKE %s ESCAPE '!')")
            params.extend([f'%{safe_area}%', f'%{safe_area}%'])

        joins = (
            ' FROM complaints c '
            'JOIN locations loc ON loc.location_id = c.location_id '
            'LEFT JOIN categories cat ON cat.category_id = c.category_id '
        )
        where_sql = ' WHERE ' + ' AND '.join(where)
        conn = get_db_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                'SELECT category_id, category_name FROM categories ORDER BY category_name'
            )
            categories = cursor.fetchall()

            cursor.execute('''SELECT COUNT(*) AS report_count,
                                   COALESCE(SUM(c.severity = 'High'), 0) AS high_count,
                                   COALESCE(SUM(c.status = 'Submitted'), 0) AS submitted_count
                            ''' + joins + where_sql, tuple(params))
            totals = cursor.fetchone()

            # Area counts use ALL matching data, not just the marker display sample.
            cursor.execute('''SELECT COALESCE(NULLIF(TRIM(loc.area_name), ''),
                                               'Area unspecified') AS area_label,
                                   COUNT(*) AS report_count,
                                   AVG(loc.latitude) AS center_lat,
                                   AVG(loc.longitude) AS center_lng
                            ''' + joins + where_sql + '''
                            GROUP BY area_label
                            ORDER BY report_count DESC, area_label ASC
                            LIMIT 8''', tuple(params))
            hotspot_areas = [
                {
                    'area': item['area_label'],
                    'count': int(item['report_count']),
                    'lat': float(item['center_lat']),
                    'lng': float(item['center_lng']),
                } for item in cursor.fetchall()
            ]

            # Cap the payload for a responsive prototype; communicate the cap.
            max_mapped = 1000
            cursor.execute('''SELECT c.complaint_id, c.reference_code,
                                   c.description, c.severity, c.status, c.created_at,
                                   loc.latitude, loc.longitude, loc.area_name,
                                   cat.category_name
                            ''' + joins + where_sql + '''
                            ORDER BY c.created_at DESC, c.complaint_id DESC
                            LIMIT %s''', tuple(params + [max_mapped]))
            map_points = []
            for row in cursor.fetchall():
                lat, lng = float(row['latitude']), float(row['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lng):
                    continue
                map_points.append({
                    'id': row['complaint_id'],
                    'reference': row['reference_code'],
                    'description': row['description'][:170],
                    'status': row['status'],
                    'severity': row['severity'],
                    'area': row['area_name'] or 'Area unspecified',
                    'category': row['category_name'] or 'Uncategorized',
                    'lat': lat, 'lng': lng,
                    'detail_url': url_for('admin.report_detail', complaint_id=row['complaint_id'])
                })
        finally:
            if cursor is not None:
                cursor.close()
            conn.close()

        return render_template(
            'admin_map.html', user=user,
            categories=categories,
            chosen_category=chosen_category,
            status_filter=status_filter,
            area_query=area_query,
            totals=totals,
            hotspot_areas=hotspot_areas,
            map_points=map_points,
            max_mapped=max_mapped,
        )
