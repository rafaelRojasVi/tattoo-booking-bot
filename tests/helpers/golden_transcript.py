"""
Helpers for golden-transcript (Phase 1) end-to-end tests.

- format_transcript: build USER:/BOT: transcript from message lists
- PHASE1_HAPPY_PATH_ANSWERS: canonical answer sequence for qualifying flow
- make_capturing_send: factory for a send that appends only client-facing messages
"""


def make_capturing_send(bot_messages: list[str], wa_from: str):
    """
    Return an async send that appends to bot_messages only when message is to the lead (client).
    Use so artist notifications are not included in the transcript.
    """

    async def capturing_send(to: str, message: str, dry_run: bool = True, **kwargs):
        if to == wa_from:
            bot_messages.append(message)
        return {"id": "mock", "status": "sent"}

    return capturing_send


def format_transcript(
    user_messages: list[str],
    bot_messages: list[str],
    *,
    max_line: int | None = 200,
) -> str:
    """
    Build a transcript string: USER: ... / BOT: ... (interleaved).

    user_messages[0] is the first user message, bot_messages[0] is the first bot reply, etc.
    Lengths can differ (e.g. one extra user message at end); we pair by index and
    append any remainder.

    Args:
        max_line: Truncate lines longer than this; None = no truncation (full transcript).
    """
    lines: list[str] = []
    n = max(len(user_messages), len(bot_messages))
    for i in range(n):
        if i < len(user_messages):
            u = user_messages[i]
            u_show = (u[: max_line] + "…") if max_line is not None and len(u) > max_line else u
            u_show = u_show.replace("\n", " ")
            lines.append(f"USER: {u_show}")
        if i < len(bot_messages):
            b = bot_messages[i]
            b_show = (b[: max_line] + "…") if max_line is not None and len(b) > max_line else b
            b_show = b_show.replace("\n", " ")
            lines.append(f"BOT:  {b_show}")
    return "\n".join(lines)


def get_one_at_a_time_reprompt_templates_from_copy() -> list[str]:
    """
    Load one_at_a_time_reprompt templates from copy/YAML (audit-grade snapshot).

    Returns list of template strings with {question_text} placeholder.
    Use to assert bot message comes from copy, not hardcoded.
    """
    from pathlib import Path

    import yaml

    copy_dir = Path(__file__).resolve().parent.parent.parent / "app" / "copy"
    copy_file = copy_dir / "en_GB.yml"
    with open(copy_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    variants = data.get("one_at_a_time_reprompt")
    if not isinstance(variants, list):
        return []
    return [str(v) for v in variants]


# Phase 1 happy-path answers (order must match CONSULTATION_QUESTIONS in questions.py)
PHASE1_HAPPY_PATH_ANSWERS = [
    "A dragon tattoo on my arm",  # idea
    "Upper arm",  # placement
    "10x15cm",  # dimensions
    "Realism",  # style
    "2",  # complexity (1–3; 2 avoids handover)
    "No",  # coverup
    "no",  # reference_images
    "500",  # budget
    "London",  # location_city
    "UK",  # location_country
    "@myhandle",  # instagram_handle
    "same",  # travel_city
    "Next 2-4 weeks",  # timing (last question)
]
