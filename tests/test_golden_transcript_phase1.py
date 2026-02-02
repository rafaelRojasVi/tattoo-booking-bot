"""
Golden transcript end-to-end test for Phase 1.

Runs a realistic happy-path message sequence through handle_inbound_message,
captures all bot messages in order, and asserts final status + step and invariants.

- Transcript is included in assertion messages so it prints on failure.
- Set GOLDEN_TRANSCRIPT_PRINT=1 to always print the transcript on success.
- Run with pytest -s to see any print() output (e.g. when GOLDEN_TRANSCRIPT_PRINT=1).
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversation import (
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    handle_inbound_message,
)
from app.services.leads import get_or_create_lead
from app.services.questions import get_total_questions
from tests.helpers.golden_transcript import (
    PHASE1_HAPPY_PATH_ANSWERS,
    format_transcript,
    make_capturing_send,
)


# Last question index (0-based); total questions = 13, so last index = 12
PHASE1_LAST_STEP = get_total_questions() - 1


@pytest.mark.asyncio
async def test_golden_transcript_phase1_happy_path(db):
    """
    Phase 1 golden transcript: full qualifying flow from first message to PENDING_APPROVAL.

    - Patches send_whatsapp_message to append bot messages in order.
    - Asserts final status PENDING_APPROVAL and current_step == last question index.
    - Invariants: step monotonicity (never skip), max one bot send per inbound in happy path.
    - Transcript is shown on assertion failure; set GOLDEN_TRANSCRIPT_PRINT=1 to always print.
    """
    bot_messages: list[str] = []

    async def capturing_send(to: str, message: str, dry_run: bool = True, **kwargs):
        bot_messages.append(message)
        return {"id": "mock", "status": "sent"}

    wa_from = "447700123456"
    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    previous_step: int | None = None

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Initial message -> welcome + first question
        user_messages.append("Hi, I'd like to book a tattoo")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(
            db, lead, user_messages[-1], dry_run=True
        )
        db.refresh(lead)
        assert lead.status == STATUS_QUALIFYING
        assert lead.current_step == 0
        assert len(bot_messages) - n_bot_before <= 1, (
            "Happy path: at most one bot send per inbound"
        )
        previous_step = 0

        # 2) Answer each question in order
        for i, answer in enumerate(PHASE1_HAPPY_PATH_ANSWERS):
            user_messages.append(answer)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)

            # Max one bot send per inbound
            n_after = len(bot_messages)
            assert n_after - n_bot_before <= 1, (
                f"Happy path: at most one bot send per inbound (answer {i + 1})"
            )

            # Step monotonicity: never skip (current_step == previous_step + 1, or we completed)
            if lead.status == STATUS_PENDING_APPROVAL:
                break
            assert lead.current_step == previous_step + 1, (
                f"Step monotonicity: expected step {previous_step + 1}, got {lead.current_step}"
            )
            previous_step = lead.current_step

    transcript = format_transcript(user_messages, bot_messages)

    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print("\n" + "=" * 60 + "\nGOLDEN TRANSCRIPT (Phase 1)\n" + "=" * 60)
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_PENDING_APPROVAL, (
        f"Expected status PENDING_APPROVAL, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == PHASE1_LAST_STEP, (
        f"Expected current_step {PHASE1_LAST_STEP} (last question index), got {lead.current_step}.\n\n{transcript}"
    )
    assert len(bot_messages) == len(user_messages), (
        f"Expected one bot reply per user message ({len(user_messages)} each), "
        f"got {len(bot_messages)} bot messages.\n\n{transcript}"
    )


# Dimensions question index (idea=0, placement=1, dimensions=2)
DIMENSIONS_STEP = 2
# After dimensions we advance to style (index 3)
STEP_AFTER_DIMENSIONS = 3


@pytest.mark.asyncio
async def test_golden_transcript_repair_once_flow(db):
    """
    Golden transcript: bad dimensions then corrected (repair once).

    - Advance to dimensions step, send unparseable text -> repair message (no step advance).
    - Send valid dimensions -> advance to next question.
    - Asserts: step monotonicity (no skip), max one bot send per inbound, final QUALIFYING step 3.
    """
    bot_messages: list[str] = []
    wa_from = "447700123457"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    previous_step: int | None = None

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Initial -> welcome + first question
        user_messages.append("Hi, I want a tattoo")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"repair_once_flow: at most one bot send per inbound.\n\n{transcript}"
        )
        previous_step = 0

        # 2) idea
        user_messages.append("A dragon on my arm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"repair_once_flow: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == previous_step + 1, (
            f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
        )
        previous_step = lead.current_step

        # 3) placement
        user_messages.append("Upper arm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"repair_once_flow: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == previous_step + 1, (
            f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
        )
        previous_step = lead.current_step

        # 4) dimensions: bad first -> repair (explicit repair path: 1 send)
        user_messages.append("huge")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"repair_once_flow: at most one bot send per inbound (repair path).\n\n{transcript}"
        )
        assert lead.current_step == DIMENSIONS_STEP, (
            f"Step must not advance on repair: expected {DIMENSIONS_STEP}, got {lead.current_step}.\n\n{transcript}"
        )
        previous_step = lead.current_step

        # 5) dimensions: corrected -> advance
        user_messages.append("10x15cm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"repair_once_flow: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == previous_step + 1, (
            f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages)
    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print("\n" + "=" * 60 + "\nGOLDEN TRANSCRIPT (repair_once_flow)\n" + "=" * 60)
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_QUALIFYING, (
        f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == STEP_AFTER_DIMENSIONS, (
        f"Expected current_step {STEP_AFTER_DIMENSIONS}, got {lead.current_step}.\n\n{transcript}"
    )


@pytest.mark.asyncio
async def test_golden_transcript_handover_cooldown_and_continue_flow(db):
    """
    Golden transcript: handover -> cooldown holding message -> CONTINUE resumes.

    - Qualifying, user says "human" -> handover (1 send).
    - User sends message -> holding reply once (cooldown path).
    - User says "CONTINUE" -> resume qualification (1 send), same step.
    - Asserts: step monotonicity (no skip), max one bot send per inbound, final QUALIFYING.
    """
    bot_messages: list[str] = []
    wa_from = "447700123458"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Initial -> welcome + first question (step 0)
        user_messages.append("Hi")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"handover_cooldown: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Expected step 0, got {lead.current_step}.\n\n{transcript}"
        )

        # 2) "human" -> handover (1 send)
        user_messages.append("human")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"handover_cooldown: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY, (
            f"Expected NEEDS_ARTIST_REPLY, got {lead.status}.\n\n{transcript}"
        )

        # 3) Any message -> holding (cooldown: first time so we send)
        user_messages.append("hello")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"handover_cooldown: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY, (
            f"Expected NEEDS_ARTIST_REPLY, got {lead.status}.\n\n{transcript}"
        )

        # 4) "CONTINUE" -> resume (1 send), back to QUALIFYING, same step
        user_messages.append("CONTINUE")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"handover_cooldown: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.status == STATUS_QUALIFYING, (
            f"Expected QUALIFYING after CONTINUE, got {lead.status}.\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Expected step 0 after resume, got {lead.current_step}.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages)
    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print(
            "\n" + "=" * 60 + "\nGOLDEN TRANSCRIPT (handover_cooldown_and_continue_flow)\n" + "=" * 60
        )
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_QUALIFYING, (
        f"Expected status QUALIFYING after CONTINUE, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == 0, (
        f"Expected current_step 0 after resume, got {lead.current_step}.\n\n{transcript}"
    )


@pytest.mark.asyncio
async def test_golden_transcript_media_wrong_step_ack_and_reprompt_flow(db):
    """
    Golden transcript: media at wrong step -> ack and reprompt, then text answer advances.

    - At idea step (0), user sends image with no caption -> ack + reprompt (1 send), no advance.
    - User sends text answer -> next question (1 send), step 1.
    - Asserts: step monotonicity (no skip), max one bot send per inbound, final QUALIFYING step 1.
    """
    bot_messages: list[str] = []
    wa_from = "447700123459"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Initial -> welcome + first question (step 0)
        user_messages.append("Hi")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"media_wrong_step: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Expected step 0, got {lead.current_step}.\n\n{transcript}"
        )

        # 2) Image at wrong step (no caption) -> ack + reprompt (1 send), step stays 0
        user_messages.append("[image no caption]")  # transcript label; we pass "" with has_media
        n_bot_before = len(bot_messages)
        await handle_inbound_message(
            db, lead, "", dry_run=True, has_media=True
        )
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"media_wrong_step: at most one bot send per inbound (ack+reprompt path).\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Step must not advance on media at wrong step: expected 0, got {lead.current_step}.\n\n{transcript}"
        )

        # 3) Text answer -> next question (1 send), step 1
        user_messages.append("A dragon tattoo on my arm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"media_wrong_step: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == 1, (
            f"Step monotonicity: expected 1, got {lead.current_step}.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages)
    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print(
            "\n"
            + "=" * 60
            + "\nGOLDEN TRANSCRIPT (media_wrong_step_ack_and_reprompt_flow)\n"
            + "=" * 60
        )
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_QUALIFYING, (
        f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == 1, (
        f"Expected current_step 1, got {lead.current_step}.\n\n{transcript}"
    )


# Placement step index (idea=0, placement=1)
PLACEMENT_STEP = 1


@pytest.mark.asyncio
async def test_golden_transcript_multi_answer_bundle_reprompts_and_no_advance(db):
    """
    Golden transcript: multi-answer bundle -> one-at-a-time reprompt, then single answer advances.

    - Hi -> welcome+Q0; idea answer -> Q1 (placement).
    - User sends bundle "Upper arm, realism, about 10x15, budget 500" -> one_at_a_time_reprompt
      (should contain placement question text), step unchanged (placement).
    - User sends "Upper arm" -> next question (dimensions), step advanced by 1.
    """
    bot_messages: list[str] = []
    wa_from = "447700123460"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Hi -> welcome + Q0
        user_messages.append("Hi")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"multi_answer_bundle: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Expected step 0, got {lead.current_step}.\n\n{transcript}"
        )

        # 2) idea answer -> Q1 (placement)
        user_messages.append("A dragon on my arm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"multi_answer_bundle: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == 1, (
            f"Expected step 1 (placement), got {lead.current_step}.\n\n{transcript}"
        )

        # 3) Bundle -> one_at_a_time_reprompt (placement question text), step unchanged
        user_messages.append("Upper arm, realism, about 10x15, budget 500")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"multi_answer_bundle: at most one bot send per inbound (reprompt path).\n\n{transcript}"
        )
        assert lead.current_step == PLACEMENT_STEP, (
            f"Step must not advance on bundle: expected {PLACEMENT_STEP}, got {lead.current_step}.\n\n{transcript}"
        )
        # Reprompt should contain placement question text (e.g. "body" or "placement")
        assert len(bot_messages) > 0
        last_bot = bot_messages[-1]
        assert "one" in last_bot.lower() or "question" in last_bot.lower() or "First" in last_bot, (
            f"Expected one-at-a-time reprompt content.\n\n{transcript}"
        )

        # 4) Single answer "Upper arm" -> next question (dimensions), step advanced by 1
        user_messages.append("Upper arm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) - n_bot_before <= 1, (
            f"multi_answer_bundle: at most one bot send per inbound.\n\n{transcript}"
        )
        assert lead.current_step == PLACEMENT_STEP + 1, (
            f"Step monotonicity: expected {PLACEMENT_STEP + 1}, got {lead.current_step}.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages)
    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print(
            "\n"
            + "=" * 60
            + "\nGOLDEN TRANSCRIPT (multi_answer_bundle_reprompts_and_no_advance)\n"
            + "=" * 60
        )
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_QUALIFYING, (
        f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == PLACEMENT_STEP + 1, (
        f"Expected current_step {PLACEMENT_STEP + 1} after single answer, got {lead.current_step}.\n\n{transcript}"
    )


@pytest.mark.asyncio
async def test_golden_transcript_outside_24h_template_then_resume(db):
    """
    Golden transcript: outside 24h window -> template fallback, then resume with normal send.

    - Hi -> welcome+Q0; idea answer -> Q1.
    - Simulate time jump: set last_client_message_at = now - 25h; user "yo" -> template sent,
      normal send_whatsapp_message NOT used for reply, step unchanged.
    - Patch is_within_24h back True; user "Upper arm" -> next question (dimensions), step advanced.
    """
    from datetime import UTC, datetime, timedelta

    from app.services.whatsapp_templates import TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE

    bot_messages: list[str] = []
    wa_from = "447700123461"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    # Track template send: when send_template_message is called, append marker to bot_messages
    async def capturing_template_send(to: str, template_name: str, template_params: dict, dry_run: bool = True):
        if to == wa_from:
            bot_messages.append(f"[TEMPLATE: {template_name}]")
        return {"status": "dry_run_template", "message_id": None, "to": to, "template_name": template_name}

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    real_is_within_24h = None

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=capturing_send,
        ),
        patch(
            "app.services.whatsapp_window.send_template_message",
            new_callable=AsyncMock,
            side_effect=capturing_template_send,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.tour_service.closest_upcoming_city", return_value=None),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        # 1) Hi -> welcome + Q0
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 0

        # 2) idea answer -> Q1 (placement)
        user_messages.append("A dragon on my arm")
        n_send_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 1
        assert len(bot_messages) == n_send_before + 1

        # 3) Simulate time jump: last client message 25h ago so is_within_24h returns False
        lead.last_client_message_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()
        db.refresh(lead)

        user_messages.append("yo")
        n_send_before_yo = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        # Normal send_whatsapp_message was NOT used for this reply (template path used)
        assert len(bot_messages) == n_send_before_yo + 1, (
            f"Exactly one bot output (template marker) for 'yo'.\n\n{transcript}"
        )
        assert bot_messages[-1] == f"[TEMPLATE: {TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE}]", (
            f"Template fallback marker expected.\n\n{transcript}"
        )
        assert lead.current_step == 1, (
            f"Step must not advance when outside 24h: expected 1, got {lead.current_step}.\n\n{transcript}"
        )

        # 4) Resume: set window back open (update last_client_message_at to now so next check is within)
        lead.last_client_message_at = datetime.now(UTC)
        db.commit()
        db.refresh(lead)

        user_messages.append("Upper arm")
        n_send_before_resume = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages)
        assert len(bot_messages) == n_send_before_resume + 1, (
            f"Resume: one bot send for 'Upper arm'.\n\n{transcript}"
        )
        assert lead.current_step == 2, (
            f"Step advanced after resume: expected 2, got {lead.current_step}.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages)
    if os.environ.get("GOLDEN_TRANSCRIPT_PRINT"):
        print(
            "\n"
            + "=" * 60
            + "\nGOLDEN TRANSCRIPT (outside_24h_template_then_resume)\n"
            + "=" * 60
        )
        print(transcript)
        print("=" * 60)

    assert lead.status == STATUS_QUALIFYING, (
        f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
    )
    assert lead.current_step == 2, (
        f"Expected current_step 2 after resume, got {lead.current_step}.\n\n{transcript}"
    )
    assert any("[TEMPLATE:" in m for m in bot_messages), (
        f"Template marker must appear in transcript.\n\n{transcript}"
    )
