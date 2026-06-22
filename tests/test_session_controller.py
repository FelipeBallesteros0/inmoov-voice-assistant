import unittest
from types import SimpleNamespace
from unittest import mock

from voice_assistant.session_controller import AppState, SessionController


class _FakeGamepad:
    def __init__(self, presses: int) -> None:
        self.presses = presses
        self.closed = False

    def wait_for_press(self, stop_event):
        if self.presses <= 0:
            stop_event.set()
            return False
        self.presses -= 1
        return True

    def close(self) -> None:
        self.closed = True


def _context(gamepad):
    return SimpleNamespace(
        state=AppState.CONVERSATION,
        gamepad=gamepad,
        logger=mock.Mock(),
    )


class SessionControllerTest(unittest.TestCase):
    def test_first_button_press_does_not_request_shutdown(self) -> None:
        gamepad = _FakeGamepad(presses=1)
        controller = SessionController(_context(gamepad))

        controller._button_listener()

        self.assertTrue(gamepad.closed)
        self.assertFalse(controller.button_events.empty())
        self.assertEqual(controller._button_press_count, 1)

    def test_second_button_press_requests_shutdown(self) -> None:
        gamepad = _FakeGamepad(presses=2)
        controller = SessionController(_context(gamepad))

        controller._button_listener()

        self.assertTrue(controller.shutdown_event.is_set())
        self.assertTrue(gamepad.closed)
        self.assertEqual(controller._button_press_count, 2)


if __name__ == "__main__":
    unittest.main()
