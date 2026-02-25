"""
Import guard: key modules must import without ImportError.

Fast, simple test to catch regressions in import cycles.
"""


def test_import_main():
    import app.main  # noqa: F401

    assert app.main.app is not None


def test_import_webhooks():
    import app.api.webhooks  # noqa: F401


def test_import_conversation():
    import app.services.conversation  # noqa: F401


def test_import_conversation_booking():
    import app.services.conversation.conversation_booking  # noqa: F401


def test_import_conversation_qualifying():
    import app.services.conversation.conversation_qualifying  # noqa: F401


def test_import_template_registry():
    import app.services.messaging.template_registry  # noqa: F401


def test_import_template_check():
    import app.services.messaging.template_check  # noqa: F401
