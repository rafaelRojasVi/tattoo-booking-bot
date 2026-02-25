"""
Question configuration for the consultation flow.
"""

from dataclasses import dataclass


@dataclass
class Question:
    """Represents a single question in the consultation flow."""

    key: str
    text: str
    required: bool = True
    validation_hint: str | None = None


# Phase 1 Consultation questions (exact match to spec)
CONSULTATION_QUESTIONS = [
    Question(
        key="idea",
        text="What tattoo do you want? Please describe it in detail.",
        required=True,
    ),
    Question(
        key="placement",
        text="Where on your body would you like this tattoo?\n\nCommon placements: arm, forearm, leg, thigh, back, chest, ribs, wrist, ankle, etc.\n\nPlease specify the exact placement.",
        required=True,
    ),
    Question(
        key="dimensions",
        text="What's the approximate size? Please give dimensions in cm (e.g., 8×12cm) or inches (e.g., 3×5 inches).\n\nIf you're not sure, give your best estimate.",
        required=True,
    ),
    Question(
        key="style",
        text="Any specific style? (e.g., fine line, realism, traditional, watercolor, geometric, etc.)\n\nIf you're not sure, just type 'not sure'.",
        required=False,
    ),
    Question(
        key="complexity",
        text="How would you describe the complexity/detail level?\n\n1) Simple linework\n2) Medium detail\n3) High detail / realism\n\nPlease reply with: 1, 2, or 3",
        required=True,
        validation_hint="Please reply with: 1, 2, or 3",
    ),
    Question(
        key="coverup",
        text="Is this a cover-up, rework, or touch-up? (Yes/No)",
        required=True,
    ),
    Question(
        key="reference_images",
        text="Do you have reference images? If yes, please send them now (images, IG links, or anything else). If not, just type 'no'.",
        required=False,
    ),
    Question(
        key="budget",
        text="What's your budget amount for this tattoo? (Please give a number, e.g., 500, 1000, 2000)",
        required=True,
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
        key="instagram_handle",
        text="What's your Instagram handle? (Optional - helps us see your style preferences)",
        required=False,
    ),
    Question(
        key="travel_city",
        text="If you'd like to book in a different city than where you're located, which city? (If same, just type 'same' or 'none')",
        required=False,
    ),
    Question(
        key="timing",
        text="What's your preferred timing window?\n\n• Next 2-4 weeks\n• 1-2 months\n• Flexible\n\nPlease choose one.",
        required=True,
    ),
]


def get_question_by_index(index: int) -> Question | None:
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
