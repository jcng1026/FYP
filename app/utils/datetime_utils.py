"""Helpers for displaying stored ISO timestamps in a readable format."""

from datetime import datetime

DISPLAY_FORMAT = "%d %b %Y, %I:%M %p"


def format_timestamp(value: str) -> str:
    """Format an ISO 8601 timestamp for display, e.g. '08 Jul 2026, 09:21 PM'.

    Falls back to returning the original value unchanged if it cannot be parsed.
    """
    if not value:
        return value

    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value

    return parsed.strftime(DISPLAY_FORMAT)
