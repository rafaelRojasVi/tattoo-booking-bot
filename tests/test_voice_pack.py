"""
Test voice pack application.
"""

import tempfile
from pathlib import Path

import yaml

from app.services.tone import (
    apply_voice,
    get_call_preference_text,
    load_voice_pack,
    should_apply_voice,
)


def test_load_voice_pack_loads_default():
    """Test that voice pack loads from default path."""
    pack = load_voice_pack()
    # Should return a dict (even if empty)
    assert isinstance(pack, dict)


def test_apply_voice_skips_templates():
    """Test that templates are not modified."""
    text = "This is a template message with {{1}}"
    result = apply_voice(text, is_template=True)
    assert result == text  # Should be unchanged


def test_apply_voice_applies_spelling_replacements():
    """Test that UK spelling is applied."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        pack_data = {
            "spelling": {
                "locale": "en_GB",
                "replacements": {
                    "color": "colour",
                    "organize": "organise",
                },
            }
        }
        yaml.dump(pack_data, f)
        temp_path = Path(f.name)

    try:
        # Temporarily replace the voice pack path
        from app.services import tone

        original_path = tone.VOICE_PACK_PATH
        tone.VOICE_PACK_PATH = temp_path
        tone._voice_pack_cache = None  # Clear cache
        tone.load_voice_pack.cache_clear()

        result = apply_voice("I like the color and want to organize it", is_template=False)
        assert "colour" in result
        assert "organise" in result
    finally:
        tone.VOICE_PACK_PATH = original_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()
        temp_path.unlink()


def test_apply_voice_replaces_banned_phrases():
    """Test that banned phrases are replaced."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        pack_data = {
            "banned_phrases": ["I guarantee", "I promise"],
            "phrase_replacements": {
                "I guarantee": "I'll aim to",
                "I promise": "I'll try to",
            },
        }
        yaml.dump(pack_data, f)
        temp_path = Path(f.name)

    try:
        from app.services import tone

        original_path = tone.VOICE_PACK_PATH
        tone.VOICE_PACK_PATH = temp_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()

        result = apply_voice("I guarantee this will work. I promise!", is_template=False)
        assert "I'll aim to" in result
        assert "I'll try to" in result
        assert "I guarantee" not in result
        assert "I promise" not in result
    finally:
        tone.VOICE_PACK_PATH = original_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()
        temp_path.unlink()


def test_apply_voice_limits_emojis():
    """Test that emoji count is limited."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        pack_data = {
            "emoji": {
                "enabled": True,
                "max_per_message": 2,
            }
        }
        yaml.dump(pack_data, f)
        temp_path = Path(f.name)

    try:
        from app.services import tone

        original_path = tone.VOICE_PACK_PATH
        tone.VOICE_PACK_PATH = temp_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()

        text = "🎨 ✅ 💳 📅 👋"  # 5 emojis
        result = apply_voice(text, is_template=False)
        # Should have at most 2 emojis (exact count depends on implementation)
        emoji_count = sum(1 for c in result if ord(c) > 0x1F000)
        assert emoji_count <= 2
    finally:
        tone.VOICE_PACK_PATH = original_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()
        temp_path.unlink()


def test_apply_voice_applies_preferred_terms():
    """Test that preferred terms are applied."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        pack_data = {
            "preferred_terms": {
                "appointment": "session",
                "booking deposit": "deposit",
            }
        }
        yaml.dump(pack_data, f)
        temp_path = Path(f.name)

    try:
        from app.services import tone

        original_path = tone.VOICE_PACK_PATH
        tone.VOICE_PACK_PATH = temp_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()

        result = apply_voice(
            "Your appointment is confirmed. Please pay the booking deposit.", is_template=False
        )
        assert "session" in result
        assert "deposit" in result
        assert "appointment" not in result
        assert "booking deposit" not in result
    finally:
        tone.VOICE_PACK_PATH = original_path
        tone._voice_pack_cache = None
        tone.load_voice_pack.cache_clear()
        temp_path.unlink()


def test_get_call_preference_text():
    """Test that call preference text is retrieved."""
    text = get_call_preference_text()
    assert isinstance(text, str)
    assert len(text) > 0


def test_should_apply_voice():
    """Test that should_apply_voice returns boolean."""
    result = should_apply_voice()
    assert isinstance(result, bool)
