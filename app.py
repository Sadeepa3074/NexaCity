
import os
import re
from pathlib import Path
from datetime import timedelta
from functools import wraps
import math
import secrets

from flask import send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from photo_utils import save_complaint_photo

import mysql.connector
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session, abort
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from db import get_db_connection
from colombo_service_area import is_within_colombo_service_area

# Load configuration. Set CIVICFIX_ENV_FILE to use a separate local/cloud
# environment file. Existing process environment variables take precedence.
base_dir = Path(__file__).resolve().parent
env_file = os.getenv("CIVICFIX_ENV_FILE", ".env")
env_path = Path(env_file)
if not env_path.is_absolute():
    env_path = base_dir / env_path
load_dotenv(env_path, override=False)

app = Flask(__name__)

# Limit total request size to 6 MB
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

# Store uploaded photos outside the public static folder
UPLOAD_DIR = Path(app.instance_path) / "complaint_photos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(error):
    flash("Upload too large. Choose a photo under 5 MB.", "error")
    return redirect(url_for("submit_complaint"))

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY is missing from .env")

app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower()
    in {"1", "true", "yes"}
)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

CSRFProtect(app)


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    connection = get_db_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT category_name FROM categories "
            "ORDER BY category_id"
        )

        categories = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template(
        "index.html",
        categories=categories
    )


# ---------------- REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        # Validate inputs
        if not full_name or len(full_name) > 100:
            flash("Enter a valid full name.", "error")
            return redirect(url_for("register"))

        if (len(email) > 190 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+", email
        )):
            flash("Enter a valid email address.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash(
                "Password must contain at least 8 characters.",
                "error"
            )
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        # Hash password before storing
        password_hash = generate_password_hash(password)

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor()

            query = """
                INSERT INTO users
                (full_name, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (full_name, email, password_hash, "citizen")
            )

            connection.commit()

            flash(
                "Account created successfully!",
                "success"
            )
            return redirect(url_for("login"))

        except mysql.connector.IntegrityError:
            flash(
                "This email is already registered.",
                "error"
            )

        except mysql.connector.Error:
            flash(
                "A database error occurred. Try again.",
                "error"
            )

        finally:
            if cursor is not None:
                cursor.close()

            if connection is not None:
                connection.close()

        return redirect(url_for("register"))

    return render_template("register.html")

# ---------------- CITIZEN LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("citizen_dashboard"))

        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Please enter your email and password.", "error")
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, full_name, email,
                   password_hash, role
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

    except mysql.connector.Error:
        flash("Login is temporarily unavailable.", "error")
        return redirect(url_for("login"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()

    # Compare submitted password with stored hash
    if (
        not user
        or not user.get("password_hash")
        or not check_password_hash(user["password_hash"], password)
    ):
        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    # Only citizens can access this portal
    if user["role"] != "citizen":
        flash("This login is for citizen accounts.", "error")
        return redirect(url_for("login"))

    # Clear any previous session before signing in
    session.clear()

    session["user_id"] = user["user_id"]
    session["auth_method"] = "password"
    session.permanent = True

    return redirect(url_for("citizen_dashboard"))

# ---------------- CITIZEN ACCESS PROTECTION ----------------

def citizen_required(view):

    @wraps(view)
    def protected_view(*args, **kwargs):

        user_id = session.get("user_id")

        if user_id is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT user_id, full_name, email, role, created_at
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            user = cursor.fetchone()

        finally:
            if cursor is not None:
                cursor.close()

            if connection is not None:
                connection.close()

        if user is None:
            session.clear()
            flash("Please log in again.", "error")
            return redirect(url_for("login"))

        if user["role"] != "citizen":
            abort(403)

        return view(user, *args, **kwargs)

    return protected_view


# ---------------- CITIZEN DASHBOARD ----------------

@app.route("/citizen/dashboard")
@citizen_required
def citizen_dashboard(user):

    connection = get_db_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # Fetch complaint statistics for this citizen
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(
                    SUM(status IN (
                        'Submitted',
                        'Under Review',
                        'Assigned',
                        'In Progress'
                    )), 0
                ) AS active,
                COALESCE(
                    SUM(status = 'Resolved'), 0
                ) AS resolved
            FROM complaints
            WHERE user_id = %s
            """,
            (user["user_id"],)
        )

        stats = cursor.fetchone()

        # Fetch the citizen's five latest complaints
        cursor.execute(
            """
            SELECT
                c.complaint_id,
                c.reference_code,
                c.description,
                c.image_path,
                c.status,
                c.created_at,
                c.updated_at,
                cat.category_name
            FROM complaints AS c
            LEFT JOIN categories AS cat
                ON c.category_id = cat.category_id
            WHERE c.user_id = %s
            ORDER BY c.created_at DESC, c.complaint_id DESC
            LIMIT 5
            """,
            (user["user_id"],)
        )

        recent_complaints = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template(
        "citizen_dashboard.html",
        user=user,
        stats=stats,
        recent_complaints=recent_complaints
    )


# ---------------- CITIZEN PROFILE ----------------

@app.route("/citizen/profile")
@citizen_required
def citizen_profile(user):
    """Display the signed-in citizen's account information."""
    return render_template("citizen_profile.html", user=user)


# ---------------- CITIZEN ACCOUNT SETTINGS ----------------

@app.route("/citizen/settings", methods=["GET", "POST"])
@citizen_required
def citizen_settings(user):
    """Allow a citizen to update their name, email and password."""

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT password_hash FROM users WHERE user_id = %s AND role = 'citizen' LIMIT 1",
            (user["user_id"],),
        )
        account_security = cursor.fetchone()
        if account_security is None:
            session.clear()
            flash("Please sign in again to continue.", "error")
            return redirect(url_for("login"))

        cursor.execute(
            "SELECT identity_id FROM user_identities "
            "WHERE user_id = %s AND provider = 'google' LIMIT 1",
            (user["user_id"],),
        )
        google_identity = cursor.fetchone()
    except mysql.connector.Error:
        flash("We couldn't load your account settings. Please try again.", "error")
        return redirect(url_for("citizen_dashboard"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    has_password = bool(account_security.get("password_hash"))
    google_linked = google_identity is not None

    if request.method == "GET":
        return render_template(
            "citizen_settings.html",
            user=user,
            has_password=has_password,
            google_linked=google_linked,
        )

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not full_name or len(full_name) > 100:
        flash("Enter a valid name (up to 100 characters).", "error")
        return redirect(url_for("citizen_settings"))

    if len(email) > 190 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("citizen_settings"))

    if has_password and not current_password:
        flash("Enter your current password to save account changes.", "error")
        return redirect(url_for("citizen_settings"))

    if not has_password and session.get("auth_method") != "google":
        flash("Please sign in with your connected Google account to manage these settings.", "error")
        return redirect(url_for("login"))

    if new_password:
        if len(new_password) < 8:
            flash("Your new password must contain at least 8 characters.", "error")
            return redirect(url_for("citizen_settings"))
        if new_password != confirm_password:
            flash("The new passwords do not match.", "error")
            return redirect(url_for("citizen_settings"))
    elif confirm_password:
        flash("Enter a new password before confirming it.", "error")
        return redirect(url_for("citizen_settings"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT password_hash FROM users WHERE user_id = %s AND role = 'citizen' LIMIT 1",
            (user["user_id"],)
        )
        account = cursor.fetchone()

        if account is None:
            session.clear()
            flash("Please sign in again to continue.", "error")
            return redirect(url_for("login"))

        stored_password_hash = account.get("password_hash")
        if stored_password_hash:
            if not current_password or not check_password_hash(stored_password_hash, current_password):
                flash("Your current password is incorrect. No changes were saved.", "error")
                return redirect(url_for("citizen_settings"))
        elif session.get("auth_method") != "google":
            flash("Please sign in with Google again before changing account settings.", "error")
            return redirect(url_for("login"))

        password_hash = stored_password_hash
        if new_password:
            password_hash = generate_password_hash(new_password)

        cursor.execute(
            """
            UPDATE users
            SET full_name = %s,
                email = %s,
                password_hash = %s
            WHERE user_id = %s AND role = 'citizen'
            """,
            (full_name, email, password_hash, user["user_id"])
        )
        connection.commit()
        flash("Your account details have been updated successfully.", "success")
        return redirect(url_for("citizen_profile"))

    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        flash("That email address is already used by another account.", "error")
        return redirect(url_for("citizen_settings"))

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        flash("We couldn't update your account right now. Please try again.", "error")
        return redirect(url_for("citizen_settings"))

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# ---------------- LOGOUT ----------------

@app.route("/logout", methods=["POST"])
def logout():

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("login"))


# ---------------- COMPLAINT SUBMISSION ----------------

@app.route("/citizen/report", methods=["GET", "POST"])
@citizen_required
def submit_complaint(user):

    if request.method == "GET":
        connection = get_db_connection()
        cursor = None

        try:
            cursor = connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT category_id, category_name
                FROM categories
                ORDER BY category_id
            """)

            categories = cursor.fetchall()

        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

        return render_template(
            "submit_complaint.html",
            categories=categories,
            user=user
        )

    # Read form data
    description = request.form.get(
        "description", ""
    ).strip()

    address = request.form.get(
        "address", ""
    ).strip()

    area = request.form.get(
        "area", ""
    ).strip()

    severity = request.form.get(
        "severity", "Medium"
    )

    # Validate text fields
    if not 10 <= len(description) <= 3000:
        flash(
            "Description must contain 10 to 3000 characters.",
            "error"
        )
        return redirect(url_for("submit_complaint"))

    if not 5 <= len(address) <= 255:
        flash(
            "Enter a valid address or landmark.",
            "error"
        )
        return redirect(url_for("submit_complaint"))

    if len(area) > 100:
        flash("Area name is too long.", "error")
        return redirect(url_for("submit_complaint"))

    if severity not in ("Low", "Medium", "High"):
        flash("Invalid severity level.", "error")
        return redirect(url_for("submit_complaint"))

    # Validate category and map coordinates
    try:
        category_id = int(request.form.get("category_id", ""))
        latitude = float(request.form.get("latitude", ""))
        longitude = float(request.form.get("longitude", ""))

        if category_id <= 0:
            raise ValueError

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ValueError

    except (ValueError, TypeError):
        flash(
            "Choose a category and select a location on the map.",
            "error"
        )
        return redirect(url_for("submit_complaint"))

    if not is_within_colombo_service_area(latitude, longitude):
        flash(
            "NexaCity currently accepts reports within its Colombo coverage area only. "
            "Please select a point inside the Colombo map area.",
            "error"
        )
        return redirect(url_for("submit_complaint"))

    uploaded_photo = request.files.get("photo")

    connection = None
    cursor = None
    saved_photo = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Confirm category exists in MySQL
        cursor.execute(
            "SELECT category_id FROM categories "
            "WHERE category_id = %s",
            (category_id,)
        )

        if cursor.fetchone() is None:
            raise ValueError("Invalid complaint category.")

        # Save optional photo
        if uploaded_photo and uploaded_photo.filename:
            saved_photo = save_complaint_photo(
                uploaded_photo,
                UPLOAD_DIR
            )

        # Generate a unique complaint reference
        reference_code = (
            "CF-" + secrets.token_hex(8).upper()
        )

        # Store the location
        cursor.execute(
            """
            INSERT INTO locations
                (address_text, area_name,
                 latitude, longitude)
            VALUES (%s, %s, %s, %s)
            """,
            (address, area or None, latitude, longitude)
        )

        location_id = cursor.lastrowid

        # Store the complaint
        cursor.execute(
            """
            INSERT INTO complaints
                (reference_code, user_id,
                 category_id, location_id,
                 description, image_path,
                 severity, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                reference_code,
                user["user_id"],
                category_id,
                location_id,
                description,
                saved_photo,
                severity,
                "Submitted"
            )
        )

        complaint_id = cursor.lastrowid

        # Record initial complaint status
        cursor.execute(
            """
            INSERT INTO status_history
                (complaint_id, changed_by,
                 old_status, new_status, note)
            VALUES (%s, %s, NULL, %s, %s)
            """,
            (
                complaint_id,
                user["user_id"],
                "Submitted",
                "Complaint submitted by citizen."
            )
        )

        # Save all three database changes together
        connection.commit()

        flash(
            f"Complaint {reference_code} submitted successfully!",
            "success"
        )

        return redirect(url_for("citizen_dashboard"))

    except (ValueError, mysql.connector.Error, OSError) as error:

        if connection is not None and connection.is_connected():
            connection.rollback()

        # Remove uploaded photo if database saving failed
        if saved_photo:
            (UPLOAD_DIR / saved_photo).unlink(
                missing_ok=True
            )

        if isinstance(error, ValueError):
            flash(str(error), "error")
        else:
            app.logger.exception(
                "Complaint submission failed"
            )
            flash(
                "Could not save complaint. Please try again.",
                "error"
            )

        return redirect(url_for("submit_complaint"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# ---------------- PRIVATE COMPLAINT PHOTO ----------------

@app.route(
    "/citizen/complaints/<int:complaint_id>/photo"
)
@citizen_required
def complaint_photo(user, complaint_id):

    connection = get_db_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT image_path
            FROM complaints
            WHERE complaint_id = %s AND user_id = %s
            """,
            (complaint_id, user["user_id"])
        )

        record = cursor.fetchone()

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    if not record or not record["image_path"]:
        abort(404)

    return send_from_directory(
        UPLOAD_DIR,
        record["image_path"],
        mimetype="image/jpeg"
    )


# ---------------- COMPLAINT HISTORY ----------------

COMPLAINT_STATUSES = [
    "Submitted",
    "Under Review",
    "Assigned",
    "In Progress",
    "Resolved",
    "Rejected"
]


@app.route("/citizen/complaints")
@citizen_required
def my_complaints(user):
    """Show a citizen's own reports with searchable status filters and pagination."""
    selected_status = request.args.get("status", "All")
    if selected_status not in ["All"] + COMPLAINT_STATUSES:
        selected_status = "All"

    search_term = request.args.get("q", "").strip()[:100]
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page_size = 10

    connection = get_db_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # Summary cards always describe all of this citizen's reports,
        # independent of the active search or status filter.
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(status IN (
                    'Submitted', 'Under Review', 'Assigned', 'In Progress'
                )), 0) AS active,
                COALESCE(SUM(status = 'Resolved'), 0) AS resolved
            FROM complaints
            WHERE user_id = %s
            """,
            (user["user_id"],)
        )
        report_stats = cursor.fetchone() or {
            "total": 0, "active": 0, "resolved": 0
        }

        # Build only parameterized filters. The joins are shared by the
        # count and result queries so category/location searches stay aligned.
        joins = """
            FROM complaints AS c
            LEFT JOIN categories AS cat
                ON c.category_id = cat.category_id
            JOIN locations AS loc
                ON c.location_id = loc.location_id
        """
        where_parts = ["c.user_id = %s"]
        params = [user["user_id"]]

        if selected_status != "All":
            where_parts.append("c.status = %s")
            params.append(selected_status)

        if search_term:
            where_parts.append("""(
                c.reference_code LIKE %s
                OR c.description LIKE %s
                OR COALESCE(cat.category_name, '') LIKE %s
                OR COALESCE(loc.area_name, '') LIKE %s
                OR loc.address_text LIKE %s
            )""")
            pattern = f"%{search_term}%"
            params.extend([pattern] * 5)

        where_sql = " WHERE " + " AND ".join(where_parts)

        cursor.execute(
            "SELECT COUNT(*) AS total " + joins + where_sql,
            tuple(params)
        )
        total = cursor.fetchone()["total"]

        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        cursor.execute(
            """
            SELECT
                c.complaint_id,
                c.reference_code,
                c.description,
                c.severity,
                c.status,
                c.created_at,
                c.updated_at,
                cat.category_name,
                loc.address_text,
                loc.area_name
            """ + joins + where_sql + """
            ORDER BY c.created_at DESC, c.complaint_id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [page_size, offset])
        )
        complaints = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return render_template(
        "my_complaints.html",
        user=user,
        complaints=complaints,
        selected_status=selected_status,
        search_term=search_term,
        statuses=COMPLAINT_STATUSES,
        report_stats=report_stats,
        total=total,
        page=page,
        total_pages=total_pages
    )


# ---------------- INDIVIDUAL COMPLAINT ----------------

@app.route("/citizen/complaints/<int:complaint_id>")
@citizen_required
def complaint_detail(user, complaint_id):

    connection = get_db_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # Fetch report, ensuring the citizen owns it
        cursor.execute(
            """
            SELECT
                c.complaint_id,
                c.reference_code,
                c.description,
                c.severity,
                c.status,
                c.image_path,
                c.created_at,
                c.updated_at,
                cat.category_name,
                loc.address_text,
                loc.area_name,
                loc.latitude,
                loc.longitude
            FROM complaints AS c
            LEFT JOIN categories AS cat
                ON c.category_id = cat.category_id
            JOIN locations AS loc
                ON c.location_id = loc.location_id
            WHERE c.complaint_id = %s
              AND c.user_id = %s
            """,
            (complaint_id, user["user_id"])
        )

        complaint = cursor.fetchone()

        if complaint is None:
            abort(404)

        # Retrieve actual saved status history
        cursor.execute(
            """
            SELECT
                old_status,
                new_status,
                note,
                changed_at
            FROM status_history
            WHERE complaint_id = %s
            ORDER BY changed_at ASC, history_id ASC
            """,
            (complaint_id,)
        )

        status_history = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return render_template(
        "complaint_detail.html",
        user=user,
        complaint=complaint,
        status_history=status_history
    )

from admin_routes import admin_bp
app.register_blueprint(admin_bp)

from unified_auth import install_unified_auth
install_unified_auth(app)

if __name__ == "__main__":
    app.run(debug=True)