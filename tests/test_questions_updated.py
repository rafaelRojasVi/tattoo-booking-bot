"""
Tests for updated question set matching v1.4 proposal.
"""

from app.services.conversation.questions import (
    CONSULTATION_QUESTIONS,
    get_question_by_index,
    get_total_questions,
    is_last_question,
)


def test_questions_include_location():
    """Test that questions include location_city and location_country."""
    question_keys = [q.key for q in CONSULTATION_QUESTIONS]

    assert "location_city" in question_keys
    assert "location_country" in question_keys


def test_questions_include_dimensions():
    """Test that questions include dimensions (Phase 1 replaces size_category)."""
    question_keys = [q.key for q in CONSULTATION_QUESTIONS]

    assert "dimensions" in question_keys

    # Find the dimensions question
    dims_q = next((q for q in CONSULTATION_QUESTIONS if q.key == "dimensions"), None)
    assert dims_q is not None
    assert "size" in dims_q.text.lower() or "dimension" in dims_q.text.lower()


def test_style_is_optional():
    """Test that style question is optional."""
    style_q = next((q for q in CONSULTATION_QUESTIONS if q.key == "style"), None)
    assert style_q is not None
    assert style_q.required is False


def test_dimensions_is_required():
    """Test that dimensions question is required (Phase 1)."""
    dims_q = next((q for q in CONSULTATION_QUESTIONS if q.key == "dimensions"), None)
    assert dims_q is not None
    # Dimensions is required in Phase 1
    assert dims_q.required is True


def test_question_order():
    """Test that questions are in expected order (Phase 1)."""
    # First should be idea
    assert CONSULTATION_QUESTIONS[0].key == "idea"

    # Should have placement early
    placement_idx = next(i for i, q in enumerate(CONSULTATION_QUESTIONS) if q.key == "placement")
    assert placement_idx < 5  # Should be early in the flow

    # Location should come after dimensions (Phase 1 uses dimensions, not size_category)
    location_city_idx = next(
        i for i, q in enumerate(CONSULTATION_QUESTIONS) if q.key == "location_city"
    )
    dimensions_idx = next(i for i, q in enumerate(CONSULTATION_QUESTIONS) if q.key == "dimensions")
    assert location_city_idx > dimensions_idx


def test_get_question_by_index():
    """Test get_question_by_index helper."""
    q0 = get_question_by_index(0)
    assert q0 is not None
    assert q0.key == "idea"

    # Last question
    last_idx = get_total_questions() - 1
    last_q = get_question_by_index(last_idx)
    assert last_q is not None

    # Out of bounds
    out_of_bounds = get_question_by_index(999)
    assert out_of_bounds is None


def test_is_last_question():
    """Test is_last_question helper."""
    total = get_total_questions()

    # Last question index (0-based)
    assert is_last_question(total - 1) is True
    # Beyond last question
    assert is_last_question(total) is False
    # First question
    assert is_last_question(0) is False
    # Second to last question
    assert is_last_question(total - 2) is False
    # Negative index
    assert is_last_question(-1) is False
