"""
Tests for the one-at-a-time (multi-answer bundle) guard.

Call-site verification: looks_like_multi_answer_bundle has ONE production call site:
- app/services/conversation.py L719: in _handle_qualifying_lead, passes current_question_key=current_question.key
- All paths (resume, repair, media ack, 24h template) return before the bundle guard or go through this path.
- current_question is always set when the guard is reached (return early if None).

The guard triggers ONE_AT_A_TIME_REPROMPT when:
1. looks_like_multi_answer_bundle(text) returns True (2+ signals: dimension, budget, style, @)
2. AND the message is NOT a valid single answer for the current question (dimensions/budget/location_city)

Normal tattoo descriptions with commas (e.g. "dragon, flowers, black and grey") have 0–1 signals
and do NOT trigger the guard.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.bundle_guard import (
    looks_like_multi_answer_bundle,
    looks_like_wrong_field_single_answer,
)
from app.services.conversation import (
    STATUS_QUALIFYING,
    handle_inbound_message,
)
from app.services.leads import get_or_create_lead
from tests.helpers.golden_transcript import format_transcript, make_capturing_send

# Answers to reach each step (used by multiple tests)
_ANSWERS_TO_REF = [
    "A dragon on my arm",
    "Upper arm",
    "10x15cm",
    "Realism",
    "2",
    "No",
]
_ANSWERS_TO_REFERENCE_IMAGES = _ANSWERS_TO_REF
_ANSWERS_TO_IG = _ANSWERS_TO_REF + ["no", "500", "London", "UK"]
_ANSWERS_TO_INSTAGRAM_HANDLE = _ANSWERS_TO_IG


# --- Unit tests for the heuristic ---


def test_looks_like_multi_answer_bundle_requires_two_signals():
    """Bundle guard requires 2+ signals; single signal does not fire."""
    # 1 signal only (style: realism) - no dimension, budget, @
    assert looks_like_multi_answer_bundle("realism") is False
    # 1 signal only (budget) - parse_budget fires, no dimension/style/@
    assert looks_like_multi_answer_bundle("500") is False
    # 2+ signals: style + dimensions (+ budget parses from "10")
    assert looks_like_multi_answer_bundle("realism 10x15") is True
    # 2 signals: budget + style
    assert looks_like_multi_answer_bundle("500 realism") is True


def test_normal_idea_with_commas_does_not_trigger_bundle_guard():
    """Normal tattoo descriptions with commas have 0–1 signals."""
    assert looks_like_multi_answer_bundle("dragon, flowers, black and grey") is False
    assert looks_like_multi_answer_bundle("sleeve, roses, traditional style") is False
    assert looks_like_multi_answer_bundle("small heart on my wrist") is False


def test_multi_step_signals_trigger_bundle_guard():
    """Messages with 2+ step signals (dimension, budget, style, @) trigger guard."""
    assert looks_like_multi_answer_bundle("Upper arm, realism, 10x15, budget 500") is True
    assert looks_like_multi_answer_bundle("Upper arm, realism, about 10x15, budget 500") is True


def test_bundle_guard_does_not_count_dimensions_as_budget_signal():
    """Dimension strings (10x15, 10x15cm) must not double-count as budget — 1 signal only."""
    assert looks_like_multi_answer_bundle("10x15cm") is False
    assert looks_like_multi_answer_bundle("10x15") is False
    assert looks_like_multi_answer_bundle("Upper arm, about 10x15cm") is False


def test_bundle_guard_threshold_boundary():
    """Budget threshold: 49 vs 50, with and without currency/keyword."""
    # Without keyword: < £50 not counted
    assert looks_like_multi_answer_bundle("49") is False
    assert looks_like_multi_answer_bundle("50") is False  # 1 signal only
    # With keyword: counted regardless of amount
    assert looks_like_multi_answer_bundle("49 budget") is False  # 1 signal
    assert looks_like_multi_answer_bundle("£49") is False  # 1 signal
    assert looks_like_multi_answer_bundle("£50") is False  # 1 signal
    # 2+ signals needed
    assert looks_like_multi_answer_bundle("50 realism") is True  # budget + style
    assert looks_like_multi_answer_bundle("£49 realism") is True  # budget + style


def test_idea_step_allows_numbers_in_description():
    """'2 dragons fighting' has numbers but is valid idea description — must NOT trigger wrong-field."""
    assert looks_like_wrong_field_single_answer("2 dragons fighting", "idea") is False


def test_placement_step_allows_measurement_phrases():
    """'10cm above wrist' has dimension-like phrase but is valid placement — must NOT trigger wrong-field."""
    assert looks_like_wrong_field_single_answer("10cm above wrist", "placement") is False


@pytest.mark.asyncio
async def test_idea_step_allows_numbers_in_description_integration(db):
    """At idea step: '2 dragons fighting' accepted, advances to placement."""
    bot_messages: list[str] = []
    wa_from = "447700123481"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

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
        await handle_inbound_message(db, lead, "Hi", dry_run=True)
        db.refresh(lead)
        n_bot = len(bot_messages)
        await handle_inbound_message(db, lead, "2 dragons fighting", dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(["Hi", "2 dragons fighting"], bot_messages, max_line=None)
        assert len(bot_messages) - n_bot == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 1, (
            f"'2 dragons fighting' must advance to placement; got step {lead.current_step}.\n\n{transcript}"
        )


@pytest.mark.asyncio
async def test_placement_step_allows_measurement_phrases_integration(db):
    """At placement step: '10cm above wrist' accepted, advances to dimensions."""
    bot_messages: list[str] = []
    wa_from = "447700123482"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

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
        await handle_inbound_message(db, lead, "Hi", dry_run=True)
        db.refresh(lead)
        await handle_inbound_message(db, lead, "2 dragons fighting", dry_run=True)
        db.refresh(lead)
        n_bot = len(bot_messages)
        await handle_inbound_message(db, lead, "10cm above wrist", dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(
            ["Hi", "2 dragons fighting", "10cm above wrist"], bot_messages, max_line=None
        )
        assert len(bot_messages) - n_bot == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 2, (
            f"'10cm above wrist' must advance to dimensions; got step {lead.current_step}.\n\n{transcript}"
        )


def test_bundle_guard_10x15cm_currency_returns_true_at_generic_step():
    """At generic step, '10x15cm £500' has dimension + budget → bundle=True."""
    assert looks_like_multi_answer_bundle("10x15cm £500") is True


@pytest.mark.asyncio
async def test_idea_step_rejects_budget_only_and_reprompts_idea(db):
    """At idea step: '500' or '£400' is budget-only -> reprompt idea, do not advance."""
    bot_messages: list[str] = []
    wa_from = "447700123476"
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
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 0

        user_messages.append("500")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 0, (
            f"Budget-only at idea should not advance; got step {lead.current_step}.\n\n{transcript}"
        )
        assert "What tattoo" in (bot_messages[-1] or ""), (
            f"Should reprompt idea question.\n\n{transcript}"
        )


@pytest.mark.asyncio
async def test_idea_step_rejects_dimensions_only_and_reprompts_idea(db):
    """At idea step: '10x15cm' is dimensions-only -> reprompt idea, do not advance."""
    bot_messages: list[str] = []
    wa_from = "447700123477"
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
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 0

        user_messages.append("10x15cm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 0, (
            f"Dimensions-only at idea should not advance; got step {lead.current_step}.\n\n{transcript}"
        )
        assert "What tattoo" in (bot_messages[-1] or ""), (
            f"Should reprompt idea question.\n\n{transcript}"
        )


@pytest.mark.asyncio
async def test_placement_step_rejects_dimensions_only_and_reprompts_placement(db):
    """At placement step: '10x15cm' is dimensions-only -> reprompt placement, do not advance."""
    bot_messages: list[str] = []
    wa_from = "447700123478"
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
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        user_messages.append("A dragon on my arm")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 1

        user_messages.append("10x15cm")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 1, (
            f"Dimensions-only at placement should not advance; got step {lead.current_step}.\n\n{transcript}"
        )
        assert (
            "body" in (bot_messages[-1] or "").lower()
            or "placement" in (bot_messages[-1] or "").lower()
        ), f"Should reprompt placement question.\n\n{transcript}"


@pytest.mark.asyncio
async def test_budget_step_accepts_budget_only(db):
    """At budget step: '500' is valid -> advance to location_city."""
    bot_messages: list[str] = []
    wa_from = "447700123479"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    answers_to_budget = _ANSWERS_TO_REFERENCE_IMAGES + ["no"]  # through reference_images
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
        user_messages: list[str] = ["Hi"] + list(answers_to_budget)
        for msg in user_messages:
            await handle_inbound_message(db, lead, msg, dry_run=True)
            db.refresh(lead)
        assert lead.current_step == 7

        user_messages.append("500")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, f"Exactly one bot reply.\n\n{transcript}"
        assert lead.current_step == 8, (
            f"Budget-only at budget step should advance; got step {lead.current_step}.\n\n{transcript}"
        )


# Parametrized: valid single answers must never get blocked
_VALID_SINGLE_ANSWER_CASES = [
    # (question_key, valid_answer, answers_before to reach that step)
    ("dimensions", "10x15cm", ["Hi", "A dragon on my arm", "Upper arm"]),
    ("budget", "500", ["Hi"] + _ANSWERS_TO_REFERENCE_IMAGES + ["no"]),
    ("location_city", "London", ["Hi"] + _ANSWERS_TO_REFERENCE_IMAGES + ["no", "500"]),
    ("reference_images", "no", ["Hi"] + _ANSWERS_TO_REFERENCE_IMAGES[:6]),
    ("instagram_handle", "@myhandle", ["Hi"] + _ANSWERS_TO_INSTAGRAM_HANDLE),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("question_key,valid_answer,answers_before", _VALID_SINGLE_ANSWER_CASES)
async def test_valid_single_answers_never_blocked(db, question_key, valid_answer, answers_before):
    """
    Valid single answers for dimensions, budget, location_city, instagram_handle, reference_images
    must advance (never reprompt). Max one outbound per inbound; step advances by <= 1.
    """
    from app.services.questions import CONSULTATION_QUESTIONS

    step_for_key = next(i for i, q in enumerate(CONSULTATION_QUESTIONS) if q.key == question_key)
    expected_step_after = step_for_key + 1

    bot_messages: list[str] = []
    wa_from = "447700123480"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    previous_step: int = -1  # Before first message

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
        for ans in answers_before:
            user_messages.append(ans)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)
            transcript = format_transcript(user_messages, bot_messages, max_line=None)
            assert len(bot_messages) - n_bot_before <= 1, (
                f"Max one outbound per inbound.\n\n{transcript}"
            )
            if lead.current_step != previous_step:
                assert lead.current_step == previous_step + 1, (
                    f"Step advances by at most 1: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
                )
            previous_step = lead.current_step

        assert lead.current_step == step_for_key, (
            f"Expected step {step_for_key} ({question_key}), got {lead.current_step}"
        )

        user_messages.append(valid_answer)
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one outbound for valid answer.\n\n{transcript}"
        )
        assert lead.current_step == expected_step_after, (
            f"Valid {question_key} answer should advance to step {expected_step_after}; "
            f"got {lead.current_step}.\n\n{transcript}"
        )
        assert "one question at a time" not in (bot_messages[-1] or "").lower(), (
            f"Valid answer must not trigger reprompt.\n\n{transcript}"
        )


# --- Integration tests (full conversation flow) ---


@pytest.mark.asyncio
async def test_one_at_a_time_does_not_trigger_for_normal_idea_with_commas(db):
    """
    User at step 0: "dragon, flowers, black and grey" -> accepted, advance to placement.

    Normal idea descriptions with commas have 0–1 bundle signals; guard does NOT fire.
    """
    bot_messages: list[str] = []
    wa_from = "447700123470"
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
        # 1) Hi -> welcome + Q0 (idea)
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 0
        assert lead.status == STATUS_QUALIFYING

        # 2) Normal idea with commas -> should advance to placement (step 1)
        user_messages.append("dragon, flowers, black and grey")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)

        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected.\n\n{transcript}"
        )
        assert lead.current_step == 1, (
            f"Expected step 1 (placement) after normal idea; got {lead.current_step}. "
            f"One-at-a-time should NOT trigger for 'dragon, flowers, black and grey'.\n\n{transcript}"
        )
        assert lead.status == STATUS_QUALIFYING, (
            f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
        )
        # Bot should ask placement, not one-at-a-time reprompt
        last_bot = bot_messages[-1]
        assert "one question at a time" not in last_bot.lower(), (
            f"One-at-a-time reprompt should NOT appear for normal idea. Got: {last_bot}\n\n{transcript}"
        )
        assert (
            "body" in last_bot.lower()
            or "placement" in last_bot.lower()
            or "arm" in last_bot.lower()
        ), f"Expected placement question; got: {last_bot}\n\n{transcript}"

    transcript = format_transcript(user_messages, bot_messages, max_line=None)
    assert lead.current_step == 1, f"Final step should be 1.\n\n{transcript}"


@pytest.mark.asyncio
async def test_one_at_a_time_triggers_only_when_message_contains_multiple_step_signals(db):
    """
    User at step 0: "Upper arm, realism, 10x15, budget 500" -> trigger reprompt, do NOT advance.

    Message has 2+ bundle signals (dimension, budget, style) so guard fires.
    """
    bot_messages: list[str] = []
    wa_from = "447700123471"
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
        # 1) Hi -> welcome + Q0 (idea)
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        assert lead.current_step == 0
        assert lead.status == STATUS_QUALIFYING

        # 2) Bundle with multiple step signals -> one-at-a-time reprompt, step unchanged
        user_messages.append("Upper arm, realism, 10x15, budget 500")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)

        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected (one-at-a-time reprompt).\n\n{transcript}"
        )
        assert lead.current_step == 0, (
            f"Expected step 0 unchanged; got {lead.current_step}. "
            f"One-at-a-time should trigger and NOT advance.\n\n{transcript}"
        )
        assert lead.status == STATUS_QUALIFYING, (
            f"Expected status QUALIFYING, got {lead.status}.\n\n{transcript}"
        )
        last_bot = bot_messages[-1]
        assert "one" in last_bot.lower() and (
            "question" in last_bot.lower() or "step" in last_bot.lower()
        ), f"Expected one-at-a-time reprompt content; got: {last_bot}\n\n{transcript}"
        assert "What tattoo do you want" in last_bot or "tattoo" in last_bot, (
            f"Reprompt should include current question; got: {last_bot}\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages, max_line=None)
    assert lead.current_step == 0, f"Final step should remain 0.\n\n{transcript}"


@pytest.mark.asyncio
async def test_reference_images_step_allows_ig_handle_and_style_text(db):
    """
    At reference_images step: "Realism like @someartist" should be accepted and advance to budget.

    @+style at reference_images is one coherent answer (style reference with handle).
    """
    bot_messages: list[str] = []
    wa_from = "447700123472"
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
        # 1) Hi -> welcome + Q0
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        previous_step = 0
        assert lead.current_step == 0

        # 2) Advance to reference_images (step 6)
        for ans in _ANSWERS_TO_REFERENCE_IMAGES:
            user_messages.append(ans)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)
            transcript = format_transcript(user_messages, bot_messages, max_line=None)
            assert len(bot_messages) - n_bot_before == 1, (
                f"Exactly one bot reply per inbound.\n\n{transcript}"
            )
            assert lead.current_step == previous_step + 1, (
                f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
            )
            previous_step = lead.current_step

        assert lead.current_step == 6, (
            f"Expected step 6 (reference_images), got {lead.current_step}"
        )

        # 3) "Realism like @someartist" -> should advance to budget (step 7)
        user_messages.append("Realism like @someartist")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected.\n\n{transcript}"
        )
        assert lead.current_step == 7, (
            f"Expected step 7 (budget) after reference_images answer; got {lead.current_step}. "
            f"Guard should NOT fire for 'Realism like @someartist' at reference_images.\n\n{transcript}"
        )
        assert "one question at a time" not in (bot_messages[-1] or "").lower(), (
            f"One-at-a-time reprompt should NOT appear.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages, max_line=None)
    assert lead.current_step == 7, f"Final step should be 7.\n\n{transcript}"


@pytest.mark.asyncio
async def test_dimensions_step_accepts_10x15cm_currency_and_advances(db):
    """
    At dimensions step: "10x15cm £500" is valid dimensions (parse_dimensions works).
    Guard skipped via _is_valid_single_answer; advances to style.
    """
    bot_messages: list[str] = []
    wa_from = "447700123474"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    # Advance to dimensions (step 2): Hi, idea, placement
    _answers_to_dimensions = ["A dragon on my arm", "Upper arm"]

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
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        for ans in _answers_to_dimensions:
            user_messages.append(ans)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)
            transcript = format_transcript(user_messages, bot_messages, max_line=None)
            assert len(bot_messages) - n_bot_before == 1, (
                f"Exactly one bot reply per inbound.\n\n{transcript}"
            )

        assert lead.current_step == 2, f"Expected step 2 (dimensions), got {lead.current_step}"

        # "10x15cm £500" -> valid dimensions, advance to style (step 3)
        user_messages.append("10x15cm £500")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected.\n\n{transcript}"
        )
        assert lead.current_step == 3, (
            f"Expected step 3 (style) after dimensions; got {lead.current_step}. "
            f"Valid dimensions should be accepted despite £500 in message.\n\n{transcript}"
        )
        assert "one question at a time" not in (bot_messages[-1] or "").lower(), (
            f"One-at-a-time reprompt should NOT appear.\n\n{transcript}"
        )


@pytest.mark.asyncio
async def test_reference_images_accepts_ig_url_with_style_words(db):
    """
    At reference_images step: "Realism like instagram.com/someartist" accepted, advances to budget.
    IG URL (no @) + style = 1 signal at reference_images; guard does not fire.
    """
    bot_messages: list[str] = []
    wa_from = "447700123475"
    capturing_send = make_capturing_send(bot_messages, wa_from)

    lead = get_or_create_lead(db, wa_from=wa_from)
    db.commit()
    db.refresh(lead)

    user_messages: list[str] = []
    previous_step = 0

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
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)

        for ans in _ANSWERS_TO_REFERENCE_IMAGES:
            user_messages.append(ans)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)
            transcript = format_transcript(user_messages, bot_messages, max_line=None)
            assert len(bot_messages) - n_bot_before == 1, (
                f"Exactly one bot reply per inbound.\n\n{transcript}"
            )
            assert lead.current_step == previous_step + 1, (
                f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
            )
            previous_step = lead.current_step

        assert lead.current_step == 6

        user_messages.append("Realism like instagram.com/someartist")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected.\n\n{transcript}"
        )
        assert lead.current_step == 7, (
            f"Expected step 7 (budget); got {lead.current_step}. "
            f"IG URL + style should be accepted at reference_images.\n\n{transcript}"
        )


@pytest.mark.asyncio
async def test_instagram_handle_step_accepts_handle_even_with_style_word(db):
    """
    At instagram_handle step: "@myhandle realism" should accept handle and advance.

    @+style at instagram_handle is one coherent answer.
    """
    bot_messages: list[str] = []
    wa_from = "447700123473"
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
        # 1) Hi -> welcome + Q0
        user_messages.append("Hi")
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        previous_step = 0

        # 2) Advance to instagram_handle (step 10)
        for ans in _ANSWERS_TO_INSTAGRAM_HANDLE:
            user_messages.append(ans)
            n_bot_before = len(bot_messages)
            await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
            db.refresh(lead)
            transcript = format_transcript(user_messages, bot_messages, max_line=None)
            assert len(bot_messages) - n_bot_before == 1, (
                f"Exactly one bot reply per inbound.\n\n{transcript}"
            )
            assert lead.current_step == previous_step + 1, (
                f"Step monotonicity: expected {previous_step + 1}, got {lead.current_step}.\n\n{transcript}"
            )
            previous_step = lead.current_step

        assert lead.current_step == 10, (
            f"Expected step 10 (instagram_handle), got {lead.current_step}"
        )

        # 3) "@myhandle realism" -> should advance to travel_city (step 11)
        user_messages.append("@myhandle realism")
        n_bot_before = len(bot_messages)
        await handle_inbound_message(db, lead, user_messages[-1], dry_run=True)
        db.refresh(lead)
        transcript = format_transcript(user_messages, bot_messages, max_line=None)
        assert len(bot_messages) - n_bot_before == 1, (
            f"Exactly one bot reply expected.\n\n{transcript}"
        )
        assert lead.current_step == 11, (
            f"Expected step 11 (travel_city) after instagram_handle; got {lead.current_step}. "
            f"Guard should NOT fire for '@myhandle realism' at instagram_handle.\n\n{transcript}"
        )
        assert "one question at a time" not in (bot_messages[-1] or "").lower(), (
            f"One-at-a-time reprompt should NOT appear.\n\n{transcript}"
        )

    transcript = format_transcript(user_messages, bot_messages, max_line=None)
    assert lead.current_step == 11, f"Final step should be 11.\n\n{transcript}"
