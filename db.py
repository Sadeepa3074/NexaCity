"""CivicFix database connection helper.

Local development remains on XAMPP/MariaDB by default. Set
CIVICFIX_DB_MODE=tidb and provide TIDB_* environment variables to connect to
TiDB Cloud. TiDB connections verify the server certificate and hostname.
"""

import os
from pathlib import Path

import certifi
import mysql.connector
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.getenv("CIVICFIX_ENV_FILE", ".env"))
if not ENV_FILE.is_absolute():
    ENV_FILE = BASE_DIR / ENV_FILE
# Do not overwrite variables set by the hosting platform or the shell.
load_dotenv(dotenv_path=ENV_FILE, override=False)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing.")
    return value


def get_db_connection():
    """Return a MySQL Connector/Python connection for local MariaDB or TiDB."""
    mode = os.getenv("CIVICFIX_DB_MODE", "local").strip().lower()

    if mode in {"tidb", "cloud"}:
        host = _required_env("TIDB_HOST")
        user = _required_env("TIDB_USER")
        password = _required_env("TIDB_PASSWORD")
        database = os.getenv("TIDB_DATABASE", "civicfix_db").strip() or "civicfix_db"
        port = int(os.getenv("TIDB_PORT", "4000"))
        ca_path = os.getenv("TIDB_SSL_CA", "").strip() or certifi.where()

        return mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            use_pure=True,
            connection_timeout=20,
            ssl_ca=ca_path,
            ssl_verify_cert=True,
            ssl_verify_identity=True,
        )

    if mode != "local":
        raise RuntimeError(
            "CIVICFIX_DB_MODE must be 'local' or 'tidb'."
        )

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=_required_env("MYSQL_USER"),
        password=_required_env("MYSQL_PASSWORD"),
        database=_required_env("MYSQL_DATABASE"),
        charset="utf8mb4",
        connection_timeout=15,
    )
