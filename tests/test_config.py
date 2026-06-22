import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voice_assistant.config import AppConfig


class ConfigTest(unittest.TestCase):
    def test_defaults_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("pathlib.Path.home", return_value=home):
                    config = AppConfig.from_env()
        self.assertEqual(config.gamepad_device, "/dev/input/js0")
        self.assertEqual(config.usb_label, "USB16GB")
        self.assertEqual(
            config.local_api_key_path,
            home / ".config" / "rpi_voice_assistant" / "openai_api_key.txt",
        )

    def test_parses_custom_roots(self) -> None:
        env = {"USB_SEARCH_ROOTS": "/tmp/a:/tmp/b", "AUDIO_SAMPLE_RATE": "22050"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.sample_rate, 22050)
        self.assertEqual(config.usb_search_roots, (Path("/tmp/a"), Path("/tmp/b")))


if __name__ == "__main__":
    unittest.main()
