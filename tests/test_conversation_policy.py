"""
Unit tests for conversation_policy pure functions (no DB, no IO).
"""

from datetime import UTC, datetime

import pytest

from app.services.conversation.conversation_policy import (
    handover_hold_cooldown_elapsed,
    is_delete_data_request_message,
    is_human_request_message,
    is_opt_back_in_message,
    is_opt_out_message,
    is_refund_request_message,
    normalize_message,
)

# --- normalize_message ---


def test_normalize_message_strips_and_uppers():
    assert normalize_message("  stop  ") == "STOP"
    assert normalize_message("Yes") == "YES"


def test_normalize_message_empty():
    assert normalize_message("") == ""
    assert normalize_message("   ") == ""


# --- is_opt_out_message ---


@pytest.mark.parametrize("text", ["STOP", "stop", "  UNSUBSCRIBE  ", "OPT OUT", "OPTOUT"])
def test_is_opt_out_message_true(text):
    assert is_opt_out_message(text) is True


@pytest.mark.parametrize("text", ["START", "CONTINUE", "hello", "refund"])
def test_is_opt_out_message_false(text):
    assert is_opt_out_message(text) is False


# --- is_opt_back_in_message ---


@pytest.mark.parametrize("text", ["START", "Resume", "  CONTINUE  ", "YES"])
def test_is_opt_back_in_message_true(text):
    assert is_opt_back_in_message(text) is True


@pytest.mark.parametrize("text", ["STOP", "no", "maybe"])
def test_is_opt_back_in_message_false(text):
    assert is_opt_back_in_message(text) is False


# --- is_human_request_message ---


@pytest.mark.parametrize(
    "text",
    ["HUMAN", "PERSON", "TALK TO SOMEONE", "REAL PERSON", "AGENT", "  agent  "],
)
def test_is_human_request_message_true(text):
    assert is_human_request_message(text) is True


def test_is_human_request_message_false():
    assert is_human_request_message("I want a tattoo") is False


# --- is_refund_request_message ---


def test_is_refund_request_message_true():
    assert is_refund_request_message("I want a REFUND") is True
    assert is_refund_request_message("refund") is True


def test_is_refund_request_message_false():
    assert is_refund_request_message("I want to book") is False


# --- is_delete_data_request_message ---


@pytest.mark.parametrize(
    "text",
    [
        "DELETE MY DATA",
        "delete data",
        "REMOVE MY DATA",
        "GDPR request",
        "  gdpr  ",
    ],
)
def test_is_delete_data_request_message_true(text):
    assert is_delete_data_request_message(text) is True


def test_is_delete_data_request_message_false():
    assert is_delete_data_request_message("delete the design") is False


# --- handover_hold_cooldown_elapsed ---


def test_handover_hold_cooldown_elapsed_never_sent():
    now = datetime(2025, 2, 20, 12, 0, 0, tzinfo=UTC)
    assert handover_hold_cooldown_elapsed(None, now, 6.0) is True


def test_handover_hold_cooldown_elapsed_just_sent():
    now = datetime(2025, 2, 20, 12, 0, 0, tzinfo=UTC)
    last = datetime(2025, 2, 20, 11, 59, 0, tzinfo=UTC)
    assert handover_hold_cooldown_elapsed(last, now, 6.0) is False


def test_handover_hold_cooldown_elapsed_exactly_6h_ago():
    now = datetime(2025, 2, 20, 12, 0, 0, tzinfo=UTC)
    last = datetime(2025, 2, 20, 6, 0, 0, tzinfo=UTC)
    assert handover_hold_cooldown_elapsed(last, now, 6.0) is True


def test_handover_hold_cooldown_elapsed_over_6h_ago():
    now = datetime(2025, 2, 20, 12, 0, 0, tzinfo=UTC)
    last = datetime(2025, 2, 20, 5, 0, 0, tzinfo=UTC)
    assert handover_hold_cooldown_elapsed(last, now, 6.0) is True
