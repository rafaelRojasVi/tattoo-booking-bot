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
    max_line: int = 200,
) -> str:
    """
    Build a transcript string: USER: ... / BOT: ... (interleaved).

    user_messages[0] is the first user message, bot_messages[0] is the first bot reply, etc.
    Lengths can differ (e.g. one extra user message at end); we pair by index and
    append any remainder.
    """
    lines: list[str] = []
    n = max(len(user_messages), len(bot_messages))
    for i in range(n):
        if i < len(user_messages):
            u = user_messages[i]
            u_show = (u[: max_line] + "…") if len(u) > max_line else u
            u_show = u_show.replace("\n", " ")
            lines.append(f"USER: {u_show}")
        if i < len(bot_messages):
            b = bot_messages[i]
            b_show = (b[: max_line] + "…") if len(b) > max_line else b
            b_show = b_show.replace("\n", " ")
            lines.append(f"BOT:  {b_show}")
    return "\n".join(lines)


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
