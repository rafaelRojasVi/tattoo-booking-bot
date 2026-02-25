"""
Tour service - handles tour schedule and city matching for Phase 1.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class TourStop:
    """Represents a tour stop with city and dates."""

    city: str
    country: str
    start_date: datetime
    end_date: datetime
    notes: str | None = None


# Tour schedule - loaded from config/env or JSON file
# Phase 1: This can be a simple list, later can be loaded from database or external API
_tour_schedule: list[TourStop] = []


def load_tour_schedule(schedule_data: list[dict] | None = None) -> None:
    """
    Load tour schedule from data.

    Args:
        schedule_data: List of dicts with city, country, start_date, end_date
                      If None, tries to load from config/env
    """
    global _tour_schedule
    _tour_schedule = []

    if schedule_data:
        for stop in schedule_data:
            try:
                start = datetime.fromisoformat(stop["start_date"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(stop["end_date"].replace("Z", "+00:00"))
                _tour_schedule.append(
                    TourStop(
                        city=stop["city"],
                        country=stop.get("country", ""),
                        start_date=start,
                        end_date=end,
                        notes=stop.get("notes"),
                    )
                )
            except Exception as e:
                logger.error(f"Error loading tour stop: {e}")

    # Sort by start date
    _tour_schedule.sort(key=lambda x: x.start_date)
    logger.info(f"Loaded {len(_tour_schedule)} tour stops")


def is_city_on_tour(city: str, country: str | None = None) -> bool:
    """
    Check if a city is on the current tour schedule.

    Args:
        city: City name (case-insensitive)
        country: Optional country name for disambiguation

    Returns:
        True if city is on tour
    """
    city_upper = city.upper().strip()

    now = datetime.now(UTC)

    for stop in _tour_schedule:
        # Check if stop is in the future or current
        if stop.end_date < now:
            continue  # Past tour stop

        if stop.city.upper() == city_upper:
            if country:
                # If country provided, check match
                if stop.country.upper() == country.upper().strip():
                    return True
            else:
                return True

    return False


def closest_upcoming_city(
    requested_city: str, requested_country: str | None = None
) -> TourStop | None:
    """
    Find the closest upcoming tour city to the requested city.

    Args:
        requested_city: City requested by client
        requested_country: Optional country for disambiguation

    Returns:
        TourStop if found, None otherwise
    """
    now = datetime.now(UTC)

    # Filter to upcoming stops only
    upcoming = [stop for stop in _tour_schedule if stop.start_date >= now]

    if not upcoming:
        return None

    # For Phase 1, return the next scheduled stop (simple approach)
    # Later can add distance/geography matching
    return upcoming[0]


def format_tour_offer(tour_stop: TourStop, requested_city: str | None = None) -> str:
    """
    Format a tour offer message for the client.

    Args:
        tour_stop: Tour stop to offer
        requested_city: Optional requested city name for waitlist message

    Returns:
        Formatted message string
    """
    start_str = tour_stop.start_date.strftime("%B %d, %Y")
    end_str = tour_stop.end_date.strftime("%B %d, %Y")

    if tour_stop.start_date.date() == tour_stop.end_date.date():
        date_str = start_str
    else:
        date_str = f"{start_str} - {end_str}"

    waitlist_text = f"for {requested_city}" if requested_city else "for your requested city"

    message = (
        f"📍 I'll be in *{tour_stop.city}* on {date_str}.\n\n"
        f"Would you like to book for that location instead?\n\n"
        f"Reply 'yes' to continue with {tour_stop.city}, or 'no' to be waitlisted {waitlist_text}."
    )

    return message


def get_tour_schedule() -> list[TourStop]:
    """Get current tour schedule."""
    return _tour_schedule.copy()
