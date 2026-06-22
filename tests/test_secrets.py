import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voice_assistant.config import AppConfig
from voice_assistant.secrets import (
    SecretError,
    discover_usb_api_key_file,
    resolve_api_key,
    write_local_api_key,
)


class SecretsTest(unittest.TestCase):
    def test_imports_from_usb_and_copies_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            usb = root / "media" / "USB16GB"
            usb.mkdir(parents=True)
            (usb / "api_key.txt").write_text("\n sk-test-key \nsecond\n", encoding="utf-8")

            env = {
                "USB_SEARCH_ROOTS": str(root / "media"),
                "LOCAL_API_KEY_PATH": str(root / "local" / "key.txt"),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env()
                secret = resolve_api_key(config)

            self.assertEqual(secret.source, "usb_import")
            self.assertEqual(secret.api_key, "sk-test-key")
            self.assertEqual(
                config.local_api_key_path.read_text(encoding="utf-8").strip(),
                "sk-test-key",
            )

    def test_prefers_local_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_path = root / "state" / "key.txt"
            write_local_api_key(local_path, "sk-local")
            env = {"LOCAL_API_KEY_PATH": str(local_path)}
            with mock.patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env()
                secret = resolve_api_key(config)
            self.assertEqual(secret.source, "local_file")
            self.assertEqual(secret.api_key, "sk-local")

    def test_discover_returns_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "USB_SEARCH_ROOTS": tmpdir,
                "LOCAL_API_KEY_PATH": str(Path(tmpdir) / "missing" / "key.txt"),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env()
                self.assertIsNone(discover_usb_api_key_file(config))
                with self.assertRaises(SecretError):
                    resolve_api_key(config)


if __name__ == "__main__":
    unittest.main()
