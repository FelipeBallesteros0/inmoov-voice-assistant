import struct
import unittest
from types import SimpleNamespace

from voice_assistant.audio_io import AudioError, CommandAudioIO


def _audio_io(*, sample_rate=16000, channels=1, sample_width_bytes=2, audio_gain=1):
    audio = CommandAudioIO.__new__(CommandAudioIO)
    audio.config = SimpleNamespace(
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width_bytes,
        audio_gain=audio_gain,
    )
    return audio


class AudioIOTest(unittest.TestCase):
    def test_prepare_for_vad_applies_gain(self) -> None:
        audio = _audio_io(audio_gain=5)
        pcm_data = struct.pack("<h", 100)

        prepared = audio._prepare_for_vad(pcm_data)

        self.assertEqual(prepared, struct.pack("<h", 500))

    def test_prepare_for_stt_applies_gain_and_converts_stereo_to_mono(self) -> None:
        audio = _audio_io(channels=2, audio_gain=2)
        pcm_data = struct.pack("<hhhh", 1000, 3000, -1000, -3000)

        prepared = audio._prepare_for_stt(pcm_data)

        self.assertEqual(prepared, struct.pack("<hh", 4000, -4000))

    def test_prepare_for_stt_resamples_to_16khz(self) -> None:
        audio = _audio_io(sample_rate=8000)
        pcm_data = struct.pack("<" + "h" * 80, *range(80))

        prepared = audio._prepare_for_stt(pcm_data)

        self.assertGreater(len(prepared), len(pcm_data))
        self.assertEqual(len(prepared) % 2, 0)

    def test_prepare_for_stt_rejects_unsupported_channel_count(self) -> None:
        audio = _audio_io(channels=3)

        with self.assertRaises(AudioError):
            audio._prepare_for_stt(b"\x00" * 12)


if __name__ == "__main__":
    unittest.main()
