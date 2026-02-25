"""
Minimal artist config seam for future per-artist business rules.

Returns a static default config; no new external calls. Env or DB can be wired later.
"""

from typing import Any

DEFAULT_ARTIST_ID = "default"


def get_artist_config(artist_id: str) -> dict[str, Any]:
    """
    Return config for an artist. For now a single default; later can be per-artist (env/DB).

    Expected shape (extensible):
        - timezone: str (e.g. "Europe/London")
        - min_spend_pence: int | None
        - ... other per-artist overrides
    """
    if not artist_id:
        artist_id = DEFAULT_ARTIST_ID
    # Static default; no external calls
    return {
        "artist_id": artist_id,
        "timezone": "Europe/London",
        "min_spend_pence": None,
    }
