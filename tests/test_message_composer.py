"""
Tests for message composer - variant selection and rendering.
"""

import pytest

from app.services.message_composer import MessageComposer, render_message, reset_cache


def _write_copy(copy_file, content: str) -> None:
    """Write temp YAML with UTF-8 so £ and other chars load correctly."""
    copy_file.write_text(content, encoding="utf-8")


@pytest.fixture
def copy_file(tmp_path):
    """Create a temporary copy file for testing."""
    copy_dir = tmp_path / "copy"
    copy_dir.mkdir()
    return copy_dir / "en_GB.yml"


def test_message_composer_loads_yaml(copy_file, monkeypatch):
    """Test that MessageComposer loads YAML correctly."""
    copy_file.write_text(
        """
test_welcome:
  - "Hello {name}!"
  - "Hi {name}!"
"""
    )
    # Mock the copy directory before creating composer
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        assert "test_welcome" in composer._copy_data
        assert len(composer._copy_data["test_welcome"]) == 2
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_selects_variant_deterministically(copy_file, monkeypatch):
    """Test that same lead_id always gets same variant."""
    copy_file.write_text(
        """
test_message:
  - "Variant 1"
  - "Variant 2"
  - "Variant 3"
"""
    )
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        # Same lead_id should get same variant
        variant1 = composer._select_variant("test_message", lead_id=123)
        variant2 = composer._select_variant("test_message", lead_id=123)
        assert variant1 == variant2

        # Different lead_id might get different variant
        variant3 = composer._select_variant("test_message", lead_id=456)
        # Could be same or different, but 123 should always be same
        assert variant1 == variant2
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_renders_template(copy_file, monkeypatch):
    """Test template rendering with variables."""
    _write_copy(
        copy_file,
        """
test_template:
  - "Hello {name}! Your budget is £{budget}."
""",
    )
    import app.services.message_composer as mc

    reset_cache()
    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        result = composer.render("test_template", lead_id=123, name="Alice", budget=500)
        assert result == "Hello Alice! Your budget is £500."
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_missing_key_returns_placeholder(copy_file, monkeypatch):
    """Test that missing keys return placeholder."""
    copy_file.write_text("other_key: 'test'")
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        result = composer.render("missing_key", lead_id=123)
        assert "[MISSING: missing_key]" in result
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_empty_variants_returns_placeholder(copy_file, monkeypatch):
    """Test that empty variant list returns placeholder."""
    copy_file.write_text("empty_key: []")
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        result = composer.render("empty_key", lead_id=123)
        # Empty list should return empty string
        assert result == ""
    finally:
        mc.COPY_DIR = original_dir


def test_render_message_convenience_function(copy_file, monkeypatch):
    """Test the convenience render_message function."""
    copy_file.write_text(
        """
test:
  - "Hello {name}!"
"""
    )
    # Mock the copy directory
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        result = render_message("test", lead_id=123, name="Bob")
        assert result == "Hello Bob!"
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_single_variant_not_list(copy_file, monkeypatch):
    """Test that single variant (not a list) works."""
    copy_file.write_text(
        """
test_single:
  "Just one variant"
"""
    )
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        result = composer.render("test_single", lead_id=123)
        assert result == "Just one variant"
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_variant_distribution(copy_file, monkeypatch):
    """Test that variants are distributed across different lead_ids."""
    copy_file.write_text(
        """
test_distribution:
  - "Variant 1"
  - "Variant 2"
  - "Variant 3"
"""
    )
    import app.services.message_composer as mc

    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        # Test multiple lead_ids to see distribution
        variants = set()
        for lead_id in range(100):
            variant = composer._select_variant("test_distribution", lead_id=lead_id)
            variants.add(variant)

        # Should get at least 2 different variants from 100 lead_ids
        assert len(variants) >= 2
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_real_copy_file():
    """Test that real copy file loads and renders correctly."""
    composer = MessageComposer(locale="en_GB")

    # Test a few real keys
    result = composer.render("welcome", lead_id=123, question_text="Test question?")
    assert "question" in result.lower() or "details" in result.lower()

    result = composer.render("pending_approval", lead_id=456)
    assert len(result) > 0
    assert "[MISSING" not in result


def test_message_composer_handles_missing_template_variable(copy_file, monkeypatch):
    """Test that missing template variables don't crash."""
    _write_copy(
        copy_file,
        """
test_missing_var:
  - "Hello {name}! Budget: £{budget}."
""",
    )
    import app.services.message_composer as mc

    reset_cache()
    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        # Missing 'budget' variable - Python format() fails on first missing key
        # So it returns template unchanged (no variables replaced)
        result = composer.render("test_missing_var", lead_id=123, name="Alice")
        # Template returned as-is when format() fails
        assert "{name}" in result or "name" in result.lower()
        assert "{budget}" in result or "budget" in result.lower()
    finally:
        mc.COPY_DIR = original_dir


def test_message_composer_float_formatting(copy_file, monkeypatch):
    """Test that float formatting works in templates."""
    _write_copy(
        copy_file,
        """
test_price:
  - "Amount: £{amount:.2f}"
""",
    )
    import app.services.message_composer as mc

    reset_cache()
    original_dir = mc.COPY_DIR
    mc.COPY_DIR = copy_file.parent

    try:
        composer = MessageComposer(locale="en_GB")
        result = composer.render("test_price", lead_id=123, amount=150.5)
        assert "150.50" in result
    finally:
        mc.COPY_DIR = original_dir
