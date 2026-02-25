"""Tests for artist config seam and default artist_id on Lead."""

from app.db.models import Lead
from app.services.artist_config import DEFAULT_ARTIST_ID, get_artist_config


def test_get_artist_config_default_returns_expected_shape():
    config = get_artist_config("default")
    assert config["artist_id"] == "default"
    assert "timezone" in config
    assert config["timezone"] == "Europe/London"
    assert "min_spend_pence" in config
    assert config["min_spend_pence"] is None


def test_get_artist_config_empty_uses_default():
    config = get_artist_config("")
    assert config["artist_id"] == DEFAULT_ARTIST_ID


def test_new_lead_has_default_artist_id(db):
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    assert lead.artist_id == "default"
