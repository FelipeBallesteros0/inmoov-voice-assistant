import struct
import unittest

from voice_assistant.gamepad import (
    JS_EVENT_BUTTON,
    JS_EVENT_INIT,
    parse_joystick_event,
)


class GamepadTest(unittest.TestCase):
    def test_parse_button_event(self) -> None:
        raw = struct.pack("IhBB", 123, 1, JS_EVENT_BUTTON, 0)
        event = parse_joystick_event(raw)
        self.assertEqual(event.time_ms, 123)
        self.assertEqual(event.value, 1)
        self.assertEqual(event.base_type, JS_EVENT_BUTTON)
        self.assertFalse(event.is_init)

    def test_parse_init_event(self) -> None:
        raw = struct.pack("IhBB", 456, 0, JS_EVENT_BUTTON | JS_EVENT_INIT, 0)
        event = parse_joystick_event(raw)
        self.assertTrue(event.is_init)


if __name__ == "__main__":
    unittest.main()
