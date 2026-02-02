"""
Location parsing service - handles various location input formats.

Supports:
- "London UK" format (city + country)
- "flexible/anywhere" with soft follow-up
- Only-country responses
- City-only (with country inference)
"""

import logging

logger = logging.getLogger(__name__)

# Common country names
COUNTRIES = {
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "ireland": "Ireland",
    "usa": "United States",
    "united states": "United States",
    "us": "United States",
    "canada": "Canada",
    "australia": "Australia",
    "germany": "Germany",
    "france": "France",
    "spain": "Spain",
    "italy": "Italy",
    "netherlands": "Netherlands",
    "belgium": "Belgium",
    "switzerland": "Switzerland",
    "austria": "Austria",
    "portugal": "Portugal",
    "greece": "Greece",
    "poland": "Poland",
    "sweden": "Sweden",
    "norway": "Norway",
    "denmark": "Denmark",
    "finland": "Finland",
}

# City to country mappings (common cities)
CITY_TO_COUNTRY = {
    "london": "United Kingdom",
    "manchester": "United Kingdom",
    "birmingham": "United Kingdom",
    "glasgow": "United Kingdom",
    "edinburgh": "United Kingdom",
    "liverpool": "United Kingdom",
    "bristol": "United Kingdom",
    "leeds": "United Kingdom",
    "sheffield": "United Kingdom",
    "cardiff": "United Kingdom",
    "dublin": "Ireland",
    "paris": "France",
    "berlin": "Germany",
    "madrid": "Spain",
    "rome": "Italy",
    "amsterdam": "Netherlands",
    "brussels": "Belgium",
    "zurich": "Switzerland",
    "vienna": "Austria",
    "lisbon": "Portugal",
    "athens": "Greece",
    "warsaw": "Poland",
    "stockholm": "Sweden",
    "oslo": "Norway",
    "copenhagen": "Denmark",
    "helsinki": "Finland",
    "new york": "United States",
    "los angeles": "United States",
    "chicago": "United States",
    "toronto": "Canada",
    "sydney": "Australia",
    "melbourne": "Australia",
}

# Flexible/anywhere keywords
FLEXIBLE_KEYWORDS = [
    "flexible",
    "anywhere",
    "any",
    "wherever",
    "doesn't matter",
    "doesnt matter",
    "don't care",
    "dont care",
]


def parse_location_input(location_text: str) -> dict:
    """
    Parse location input into city and country.

    Args:
        location_text: Raw location input from user

    Returns:
        dict with:
            - city: str | None
            - country: str | None
            - is_flexible: bool
            - is_only_country: bool
            - needs_follow_up: bool
    """
    if not location_text:
        return {
            "city": None,
            "country": None,
            "is_flexible": False,
            "is_only_country": False,
            "needs_follow_up": True,
        }

    location_clean = location_text.strip()
    location_lower = location_clean.lower()

    # Check for flexible keywords
    is_flexible = any(keyword in location_lower for keyword in FLEXIBLE_KEYWORDS)
    if is_flexible:
        return {
            "city": None,
            "country": None,
            "is_flexible": True,
            "is_only_country": False,
            "needs_follow_up": True,
        }

    # Check if it's too short
    if len(location_clean) < 2:
        return {
            "city": None,
            "country": None,
            "is_flexible": False,
            "is_only_country": False,
            "needs_follow_up": True,
        }

    # Try to parse "City Country" format (e.g., "London UK", "Paris France")
    # Pattern: word(s) + optional country abbreviation/country name
    parts = location_clean.split()
    if len(parts) >= 2:
        # Check if last part(s) is a country
        last_part = parts[-1].lower()
        second_last = parts[-2].lower() if len(parts) >= 2 else None

        # Check for country abbreviation or name
        country = None
        city_parts = parts

        # Check last part as country
        if last_part in COUNTRIES:
            country = COUNTRIES[last_part]
            city_parts = parts[:-1]
        # Check last two parts as country (e.g., "United Kingdom")
        elif len(parts) >= 2 and f"{second_last} {last_part}" in COUNTRIES:
            country = COUNTRIES[f"{second_last} {last_part}"]
            city_parts = parts[:-2]
        # Check for "UK", "US" abbreviations
        elif last_part in ["uk", "us", "usa"]:
            if last_part == "uk":
                country = "United Kingdom"
            elif last_part in ["us", "usa"]:
                country = "United States"
            city_parts = parts[:-1]

        if country and city_parts:
            city = " ".join(city_parts)
            return {
                "city": city,
                "country": country,
                "is_flexible": False,
                "is_only_country": False,
                "needs_follow_up": False,
            }

    # Check if it's only a country
    location_lower_full = location_lower
    if location_lower_full in COUNTRIES:
        return {
            "city": None,
            "country": COUNTRIES[location_lower_full],
            "is_flexible": False,
            "is_only_country": True,
            "needs_follow_up": True,  # Need to ask for city
        }

    # Check for multi-word country names
    for country_key, country_value in COUNTRIES.items():
        if country_key in location_lower_full and len(country_key.split()) > 1:
            # Likely only country, no city
            return {
                "city": None,
                "country": country_value,
                "is_flexible": False,
                "is_only_country": True,
                "needs_follow_up": True,
            }

    # Assume it's a city (try to infer country)
    city = location_clean
    inferred_country = None

    city_lower = location_lower
    if city_lower in CITY_TO_COUNTRY:
        inferred_country = CITY_TO_COUNTRY[city_lower]

    return {
        "city": city,
        "country": inferred_country,
        "is_flexible": False,
        "is_only_country": False,
        "needs_follow_up": inferred_country is None,  # Need follow-up if country not inferred
    }


def is_valid_location(location_text: str) -> bool:
    """
    Check if location input is valid (not flexible, not empty, has reasonable length).

    Args:
        location_text: Raw location input

    Returns:
        True if valid, False otherwise
    """
    parsed = parse_location_input(location_text)

    if parsed["is_flexible"]:
        return False

    if not parsed["city"] and not parsed["country"]:
        return False

    # If only country, it's valid but needs follow-up
    if parsed["is_only_country"]:
        return True  # Valid but incomplete

    # Need at least a city
    if not parsed["city"]:
        return False

    return True
