"""Authentication logic for the login screen."""

import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.models.user_model import User, get_user_by_username
from app.utils.password_utils import verify_password


@dataclass
class AuthResult:
    success: bool
    user: Optional[User] = None
    error_message: str = ""


def login(conn: sqlite3.Connection, username: str, password: str) -> AuthResult:
    """Validate credentials and return the authenticated user, if any."""
    user = get_user_by_username(conn, username)
    if user is None or not verify_password(password, user.password_hash):
        return AuthResult(success=False, error_message="Invalid username or password.")

    if not user.is_active:
        return AuthResult(success=False, error_message="This account has been deactivated. Contact an administrator.")

    return AuthResult(success=True, user=user)
