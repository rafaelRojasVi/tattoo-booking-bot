"""
Question configuration for the consultation flow.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Question:
    """Represents a single question in the consultation flow."""
    key: str
    text: str
    required: bool = True
    validation_hint: Optional[str] = None


# Define the consultation questions (matching v1.4 proposal)
CONSULTATION_QUESTIONS = [
    Question(
        key="idea",
        text="What tattoo do you want? Please describe it in detail.",
        required=True,
    ),
    Question(
        key="placement",
        text="Where on your body would you like this tattoo?",
        required=True,
    ),
    Question(
        key="size_category",
        text="What size category best describes your tattoo?\n\n• Small (e.g., palm-sized, small symbols)\n• Medium (e.g., forearm piece, medium designs)\n• Large (e.g., full sleeve, large back piece)\n\nPlease reply with: Small, Medium, or Large",
        required=True,
        validation_hint="Please reply with: Small, Medium, or Large",
    ),
    Question(
        key="size_measurement",
        text="(Optional) If you know the approximate size in cm or inches, please share it. Otherwise, just type 'skip'.",
        required=False,
    ),
    Question(
        key="style",
        text="Any specific style? (e.g., fine line, realism, traditional, watercolor, etc.)\n\nIf you're not sure, just type 'not sure'.",
        required=False,  # Made optional per proposal
    ),
    Question(
        key="location_city",
        text="What city are you located in?",
        required=True,
    ),
    Question(
        key="location_country",
        text="What country are you located in?",
        required=True,
    ),
    Question(
        key="budget_range",
        text="What's your budget range for this tattoo?",
        required=True,
    ),
    Question(
        key="reference_images",
        text="Do you have reference images? If yes, please send them now. If not, just type 'no'.",
        required=False,  # Optional
    ),
    Question(
        key="preferred_timing",
        text="What's your preferred timing window? (e.g., 'next month', 'in 3 months', 'flexible')",
        required=True,
    ),
]


def get_question_by_index(index: int) -> Optional[Question]:
    """Get question by its index (0-based)."""
    if 0 <= index < len(CONSULTATION_QUESTIONS):
        return CONSULTATION_QUESTIONS[index]
    return None


def get_total_questions() -> int:
    """Get total number of questions."""
    return len(CONSULTATION_QUESTIONS)


def get_required_questions_count() -> int:
    """Get count of required questions."""
    return sum(1 for q in CONSULTATION_QUESTIONS if q.required)


def is_last_question(step: int) -> bool:
    """Check if step is the last question (0-based index)."""
    return step == len(CONSULTATION_QUESTIONS) - 1
