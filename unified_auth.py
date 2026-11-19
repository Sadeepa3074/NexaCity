"""NexaCity's shared password and Google OpenID Connect authentication.

Existing email/password authentication remains supported. Google sign-in is
citizen-only. A Google identity is linked to an existing citizen account only
from an authenticated session after the citizen re-enters their current
NexaCity password.
"""

import os
import re
import time

import mysql.connector
from authlib.integrations.flask_client import OAuth
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from db import get_db_connection

unified_auth_bp = Blueprint("unified_auth", __name__)
oauth = OAuth()
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_LINK_WINDOW_SECONDS = 10 * 60


def _google_client():
    return current_app.extensions.get("nexacity_google_client")


def _google_redirect_uri():
    configured_uri = current_app.config.get("GOOGLE_REDIRECT_URI") or os.getenv(
        "GOOGLE_REDIRECT_URI", ""
    ).strip()
    return configured_uri or url_for(
        "unified_auth.google_callback", _external=True
    )


def _verified_google_profile(token):
    """Return only the identity claims Authlib verified from Google's ID token."""
    claims = token.get("userinfo") or {}
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    name = str(claims.get("name") or "").strip()
    email_verified = claims.get("email_verified")
    verified = email_verified is True or str(email_verified).lower() == "true"

    if not subject or len(subject) > 255:
        raise ValueError("Google did not provide a valid account identifier.")
    if not verified or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Google must provide a verified email address.")

    if not name:
        name = email.split("@", 1)[0]

    return {
        "subject": subject,
        "email": email,
        "name": name[:100],
    }


def _start_citizen_session(user_id):
    # Clear any admin/citizen identity before establishing the Google session.
    session.clear()
    session["user_id"] = user_id
    session["auth_method"] = "google"
    session.permanent = True
    return redirect("/citizen/dashboard")


def _finish_google_sign_in(profile):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # The stable Google subject, not the changeable email, identifies a
        # returning Google account.
        cursor.execute(
            """
            SELECT u.user_id, u.role
            FROM user_identities AS i
            JOIN users AS u ON u.user_id = i.user_id
            WHERE i.provider = 'google' AND i.provider_subject = %s
            LIMIT 1
            """,
            (profile["subject"],),
        )
        linked_account = cursor.fetchone()

        if linked_account:
            if linked_account["role"] != "citizen":
                flash(
                    "Google sign-in is available for citizen accounts only. "
                    "Administrators must use their issued credentials.",
                    "error",
                )
                return redirect(url_for("unified_auth.sign_in"))
            user_id = linked_account["user_id"]
            return _start_citizen_session(user_id)

        cursor.execute(
            "SELECT user_id, role, password_hash FROM users WHERE email = %s LIMIT 1",
            (profile["email"],),
        )
        existing_account = cursor.fetchone()

        if existing_account:
            if existing_account["role"] == "admin":
                flash(
                    "Google sign-in cannot be used for administrator accounts. "
                    "Please use your issued administrator credentials.",
                    "error",
                )
            else:
                flash(
                    "A NexaCity account already uses this email. Sign in with "
                    "your existing password first, then connect Google in "
                    "Account Settings.",
                    "error",
                )
            return redirect(url_for("unified_auth.sign_in"))

        # Google-only citizens have no local password. The migration makes
        # password_hash nullable; users can add a password later in Settings.
        cursor.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role)
            VALUES (%s, %s, NULL, 'citizen')
            """,
            (profile["name"], profile["email"]),
        )
        user_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO user_identities
                (user_id, provider, provider_subject, provider_email)
            VALUES (%s, 'google', %s, %s)
            """,
            (user_id, profile["subject"], profile["email"]),
        )
        connection.commit()
        return _start_citizen_session(user_id)

    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        current_app.logger.info(
            "Google account creation collided with an existing account."
        )
        flash(
            "This email may already have a NexaCity account. Sign in with "
            "your existing password and connect Google from Account Settings.",
            "error",
        )
        return redirect(url_for("unified_auth.sign_in"))
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception("Database error during Google sign-in.")
        flash("Google sign-in is temporarily unavailable. Please try again.", "error")
        return redirect(url_for("unified_auth.sign_in"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _finish_google_link(profile):
    user_id = session.get("user_id")
    pending_user_id = session.get("google_link_user_id")
    started_at = session.get("google_link_started_at", 0)

    # The link flow is short-lived and bound to the exact password-authenticated
    # citizen session that initiated it.
    if (
        not user_id
        or not pending_user_id
        or int(user_id) != int(pending_user_id)
        or not isinstance(started_at, (int, float))
        or time.time() - started_at > GOOGLE_LINK_WINDOW_SECONDS
    ):
        session.pop("google_link_user_id", None)
        session.pop("google_link_started_at", None)
        flash("Your Google-link request expired. Please try again from Account Settings.", "error")
        return redirect(url_for("unified_auth.sign_in"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, role FROM users WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        account = cursor.fetchone()
        if not account or account["role"] != "citizen":
            flash("Only citizen accounts can connect Google.", "error")
            return redirect(url_for("unified_auth.sign_in"))

        cursor.execute(
            """
            SELECT user_id FROM user_identities
            WHERE provider = 'google' AND provider_subject = %s
            LIMIT 1
            """,
            (profile["subject"],),
        )
        existing_identity = cursor.fetchone()

        if existing_identity:
            if int(existing_identity["user_id"]) == int(user_id):
                flash("This Google account is already connected.", "success")
            else:
                flash(
                    "This Google account is already connected to another NexaCity account.",
                    "error",
                )
            return redirect(url_for("citizen_settings"))

        # Do not let linking bypass an existing NexaCity account's ownership.
        cursor.execute(
            "SELECT user_id FROM users WHERE email = %s LIMIT 1",
            (profile["email"],),
        )
        email_owner = cursor.fetchone()
        if email_owner and int(email_owner["user_id"]) != int(user_id):
            flash(
                "That Google email belongs to a different NexaCity account. "
                "Use a Google account whose email is not assigned to another account.",
                "error",
            )
            return redirect(url_for("citizen_settings"))

        cursor.execute(
            """
            INSERT INTO user_identities
                (user_id, provider, provider_subject, provider_email)
            VALUES (%s, 'google', %s, %s)
            """,
            (user_id, profile["subject"], profile["email"]),
        )
        connection.commit()
        session.pop("google_link_user_id", None)
        session.pop("google_link_started_at", None)
        session["auth_method"] = "password_and_google"
        flash("Google has been securely connected to your NexaCity account.", "success")
        return redirect(url_for("citizen_settings"))

    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        flash(
            "This Google account could not be connected because it is already linked. "
            "Please check your account settings.",
            "error",
        )
        return redirect(url_for("citizen_settings"))
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception("Database error while linking Google identity.")
        flash("We couldn't connect Google right now. Please try again.", "error")
        return redirect(url_for("citizen_settings"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@unified_auth_bp.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    """Authenticate a citizen or administrator using the existing password flow."""
    if request.method == "GET":
        return render_template("unified_login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Please enter your email and password.", "error")
        return redirect(url_for("unified_auth.sign_in"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, password_hash, role FROM users "
            "WHERE email = %s LIMIT 1",
            (email,),
        )
        account = cursor.fetchone()
    except mysql.connector.Error:
        flash("Sign-in is temporarily unavailable. Please try again.", "error")
        return redirect(url_for("unified_auth.sign_in"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    if (
        account is None
        or not account.get("password_hash")
        or not check_password_hash(account["password_hash"], password)
        or account["role"] not in ("admin", "citizen")
    ):
        flash("Invalid email or password.", "error")
        return redirect(url_for("unified_auth.sign_in"))

    session.clear()
    session["user_id"] = account["user_id"]
    session["auth_method"] = "password"
    session.permanent = True

    if account["role"] == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect("/citizen/dashboard")


@unified_auth_bp.route("/auth/google", methods=["GET"])
def google_sign_in():
    """Start Google sign-in or citizen registration."""
    google = _google_client()
    if google is None:
        flash("Google sign-in has not been configured yet.", "error")
        return redirect(url_for("unified_auth.sign_in"))

    session.pop("google_link_user_id", None)
    session.pop("google_link_started_at", None)
    session["google_oauth_flow"] = "sign_in"
    return google.authorize_redirect(
        _google_redirect_uri(), prompt="select_account"
    )


@unified_auth_bp.route("/auth/google/link", methods=["POST"])
def google_link_start():
    """Require the citizen's current password before starting account linking."""
    google = _google_client()
    if google is None:
        flash("Google sign-in has not been configured yet.", "error")
        return redirect(url_for("citizen_settings"))

    user_id = session.get("user_id")
    password = request.form.get("current_password", "")
    if not user_id or not password:
        flash("Enter your current NexaCity password to connect Google.", "error")
        return redirect(url_for("citizen_settings"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT password_hash, role FROM users WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        account = cursor.fetchone()
    except mysql.connector.Error:
        flash("We couldn't verify your password right now. Please try again.", "error")
        return redirect(url_for("citizen_settings"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    if (
        not account
        or account["role"] != "citizen"
        or not account.get("password_hash")
        or not check_password_hash(account["password_hash"], password)
    ):
        flash("Your current NexaCity password is incorrect.", "error")
        return redirect(url_for("citizen_settings"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT identity_id FROM user_identities "
            "WHERE user_id = %s AND provider = 'google' LIMIT 1",
            (user_id,),
        )
        linked = cursor.fetchone()
    except mysql.connector.Error:
        flash("We couldn't check your connected accounts. Please try again.", "error")
        return redirect(url_for("citizen_settings"))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    if linked:
        flash("A Google account is already connected to this NexaCity account.", "success")
        return redirect(url_for("citizen_settings"))

    session["google_oauth_flow"] = "link"
    session["google_link_user_id"] = int(user_id)
    session["google_link_started_at"] = time.time()
    return google.authorize_redirect(
        _google_redirect_uri(), prompt="select_account"
    )


@unified_auth_bp.route("/auth/google/callback", methods=["GET"])
def google_callback():
    """Validate Google's OIDC response and either sign in or link an identity."""
    google = _google_client()
    if google is None:
        flash("Google sign-in is not configured. Please use your password.", "error")
        return redirect(url_for("unified_auth.sign_in"))

    flow = session.get("google_oauth_flow", "sign_in")
    try:
        token = google.authorize_access_token()
        profile = _verified_google_profile(token)
    except Exception:
        current_app.logger.exception("Google OAuth/OpenID Connect callback failed.")
        session.pop("google_oauth_flow", None)
        session.pop("google_link_user_id", None)
        session.pop("google_link_started_at", None)
        destination = (
            url_for("citizen_settings") if flow == "link"
            else url_for("unified_auth.sign_in")
        )
        flash("Google verification was unsuccessful. Please try again.", "error")
        return redirect(destination)

    session.pop("google_oauth_flow", None)
    if flow == "link":
        return _finish_google_link(profile)

    session.pop("google_link_user_id", None)
    session.pop("google_link_started_at", None)
    return _finish_google_sign_in(profile)


def _redirect_legacy_login_pages():
    """Keep existing links working, without presenting duplicate sign-in forms."""
    if request.path.rstrip("/") in ("/login", "/admin/login"):
        return redirect(url_for("unified_auth.sign_in"), code=303)
    return None


def install_unified_auth(app):
    """Register shared auth and configure Google only when credentials exist."""
    app.register_blueprint(unified_auth_bp)

    client_id = app.config.get("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = app.config.get("GOOGLE_CLIENT_SECRET") or os.getenv(
        "GOOGLE_CLIENT_SECRET", ""
    ).strip()

    if client_id and client_secret:
        oauth.init_app(app)
        oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=GOOGLE_DISCOVERY_URL,
            client_kwargs={"scope": "openid email profile"},
        )
        app.extensions["nexacity_google_client"] = oauth.create_client("google")
    else:
        app.extensions["nexacity_google_client"] = None

    @app.context_processor
    def inject_google_auth_availability():
        return {
            "google_auth_enabled": bool(
                current_app.extensions.get("nexacity_google_client")
            )
        }

    app.before_request(_redirect_legacy_login_pages)
