"""
Tests for location parsing service.
"""

from app.services.location_parsing import (
    FLEXIBLE_KEYWORDS,
    is_valid_location,
    parse_location_input,
)


def test_parse_location_flexible():
    """Test parsing flexible/anywhere keywords."""
    for keyword in FLEXIBLE_KEYWORDS:
        result = parse_location_input(keyword)
        assert result["is_flexible"] is True
        assert result["city"] is None
        assert result["country"] is None
        assert result["needs_follow_up"] is True


def test_parse_location_london_uk():
    """Test parsing 'London UK' format."""
    result = parse_location_input("London UK")

    assert result["city"] == "London"
    assert result["country"] == "United Kingdom"
    assert result["is_flexible"] is False
    assert result["is_only_country"] is False
    assert result["needs_follow_up"] is False


def test_parse_location_london_uk_lowercase():
    """Test parsing 'london uk' lowercase."""
    result = parse_location_input("london uk")

    assert result["city"] == "london"
    assert result["country"] == "United Kingdom"
    assert result["is_flexible"] is False


def test_parse_location_city_only():
    """Test parsing city only (should infer country)."""
    result = parse_location_input("London")

    assert result["city"] == "London"
    assert result["country"] == "United Kingdom"  # Should infer
    assert result["is_flexible"] is False
    assert result["is_only_country"] is False


def test_parse_location_city_only_unknown():
    """Test parsing city only with unknown city."""
    result = parse_location_input("RandomCity")

    assert result["city"] == "RandomCity"
    assert result["country"] is None  # Cannot infer
    assert result["needs_follow_up"] is True  # May need to ask for country


def test_parse_location_only_country():
    """Test parsing only country."""
    result = parse_location_input("United Kingdom")

    assert result["city"] is None
    assert result["country"] == "United Kingdom"
    assert result["is_only_country"] is True
    assert result["needs_follow_up"] is True  # Need to ask for city


def test_parse_location_only_country_uk():
    """Test parsing 'UK' abbreviation."""
    result = parse_location_input("UK")

    assert result["city"] is None
    assert result["country"] == "United Kingdom"
    assert result["is_only_country"] is True


def test_parse_location_paris_france():
    """Test parsing 'Paris France' format."""
    result = parse_location_input("Paris France")

    assert result["city"] == "Paris"
    assert result["country"] == "France"
    assert result["is_flexible"] is False


def test_parse_location_empty():
    """Test parsing empty string."""
    result = parse_location_input("")

    assert result["city"] is None
    assert result["country"] is None
    assert result["is_flexible"] is False
    assert result["needs_follow_up"] is True


def test_parse_location_too_short():
    """Test parsing very short input."""
    result = parse_location_input("A")

    assert result["city"] is None
    assert result["needs_follow_up"] is True


def test_parse_location_multi_word_city():
    """Test parsing multi-word city."""
    result = parse_location_input("New York USA")

    assert result["city"] == "New York"
    assert result["country"] == "United States"
    assert result["is_flexible"] is False


def test_is_valid_location_valid():
    """Test is_valid_location with valid inputs."""
    assert is_valid_location("London") is True
    assert is_valid_location("London UK") is True
    assert is_valid_location("United Kingdom") is True  # Valid but incomplete


def test_is_valid_location_invalid():
    """Test is_valid_location with invalid inputs."""
    assert is_valid_location("flexible") is False
    assert is_valid_location("anywhere") is False
    assert is_valid_location("") is False
    assert is_valid_location("A") is False


def test_parse_location_case_insensitive():
    """Test that parsing is case insensitive."""
    result1 = parse_location_input("LONDON UK")
    result2 = parse_location_input("london uk")

    assert result1["city"].lower() == result2["city"].lower()
    assert result1["country"] == result2["country"]


def test_parse_location_with_commas():
    """Test parsing location with commas."""
    result = parse_location_input("London, United Kingdom")

    # Should handle comma-separated format
    assert result["city"] is not None or result["country"] is not None


def test_parse_location_common_cities():
    """Test parsing common cities."""
    cities = ["Manchester", "Birmingham", "Glasgow", "Edinburgh"]

    for city in cities:
        result = parse_location_input(city)
        assert result["city"] == city
        assert result["country"] == "United Kingdom"
        assert result["is_flexible"] is False
