"""Seed default accounts for local prototype testing."""

import sqlite3

from app.models.user_model import create_user, get_user_by_username
from app.utils.password_utils import hash_password

DEFAULT_DEVELOPER_USERNAME = "developer"
DEFAULT_DEVELOPER_PASSWORD = "developer123"
DEFAULT_DEVELOPER_FULL_NAME = "System Developer"
DEFAULT_DEVELOPER_ROLE = "admin"


def seed_default_developer(conn: sqlite3.Connection) -> None:
    """Create the default Admin account if it does not already exist.

    The username/password/full_name are unchanged from earlier stages; only
    the role value is 'admin' (see Stage 3B-Correction).
    """
    if get_user_by_username(conn, DEFAULT_DEVELOPER_USERNAME) is not None:
        return

    create_user(
        conn,
        username=DEFAULT_DEVELOPER_USERNAME,
        password_hash=hash_password(DEFAULT_DEVELOPER_PASSWORD),
        full_name=DEFAULT_DEVELOPER_FULL_NAME,
        role=DEFAULT_DEVELOPER_ROLE,
    )
