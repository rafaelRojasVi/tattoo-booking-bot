"""
Late-bound dependency getters for conversation flow.

Used by conversation_booking and conversation_qualifying to avoid importing
conversation.py (which would create import cycles). Tests that patch
app.services.conversation.send_whatsapp_message still take effect because
this getter imports from conversation at call time.
"""


def get_send_whatsapp_message():
    """Return the send_whatsapp_message callable. Late-bound so test patches apply."""
    from app.services.conversation import send_whatsapp_message

    return send_whatsapp_message
