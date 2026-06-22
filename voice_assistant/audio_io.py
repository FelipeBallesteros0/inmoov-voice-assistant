from __future__ import annotations

import audioop
import os
import shlex
import shutil
import subprocess
import time
import wave
from collections import deque
from pathlib import Path
from threading import Event

from .config import AppConfig


class AudioError(RuntimeError):
    pass


def _format_command(template: str, **values: object) -> list[str]:
    return shlex.split(template.format(**values))


def _default_record_command() -> str | None:
    if shutil.which("arecord"):
        return "arecord -q -D {mic_device} -f S16_LE -c {channels} -r {rate} -t raw"
    if shutil.which("pw-record"):
        return "pw-record --target {mic_device} --rate {rate} --channels {channels} --format s16 -"
    if shutil.which("parec"):
        return "parec --device={mic_device} --rate={rate} --channels={channels} --format=s16le"
    return None


def _default_play_command() -> str | None:
    if shutil.which("aplay"):
        return "aplay -q -D {speaker_device} {path}"
    if shutil.which("pw-play"):
        return "pw-play --target {speaker_device} {path}"
    if shutil.which("paplay"):
        return "paplay --device={speaker_device} {path}"
    return None


class CommandAudioIO:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.record_template = config.record_pcm_cmd or _default_record_command()
        self.play_template = config.play_wav_cmd or _default_play_command()

    def record_until_silence(
        self,
        output_path: Path,
        stop_event: Event | None = None,
    ) -> Path | None:
        if not self.record_template:
            raise AudioError(
                "No hay backend de captura configurado. Define RECORD_PCM_CMD."
            )
        command = _format_command(
            self.record_template,
            rate=self.config.sample_rate,
            channels=self.config.channels,
            bits=self.config.sample_width_bytes * 8,
            mic_device=self.config.mic_device,
        )
        frame_size = (
            self.config.sample_rate
            * self.config.channels
            * self.config.sample_width_bytes
            * self.config.frame_ms
            // 1000
        )
        max_frames = max(1, self.config.max_record_ms // self.config.frame_ms)
        min_speech_frames = max(1, self.config.min_speech_ms // self.config.frame_ms)
        silence_frames = max(1, self.config.silence_ms // self.config.frame_ms)
        pre_roll_frames = max(1, 300 // self.config.frame_ms)
        pre_roll = deque(maxlen=pre_roll_frames)

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        captured = bytearray()
        speech_started = False
        speech_frames = 0
        quiet_frames = 0

        try:
            for _ in range(max_frames):
                if stop_event and stop_event.is_set():
                    return None
                chunk = proc.stdout.read(frame_size)
                if not chunk:
                    break
                if len(chunk) < frame_size:
                    chunk = chunk.ljust(frame_size, b"\x00")
                vad_chunk = self._prepare_for_vad(chunk)
                rms = audioop.rms(vad_chunk, self.config.sample_width_bytes)
                is_voice = rms >= self.config.vad_threshold
                if not speech_started:
                    pre_roll.append(chunk)
                    if is_voice:
                        speech_started = True
                        for buffered in pre_roll:
                            captured.extend(buffered)
                        speech_frames += 1
                        quiet_frames = 0
                    continue
                captured.extend(chunk)
                if is_voice:
                    speech_frames += 1
                    quiet_frames = 0
                else:
                    quiet_frames += 1
                    if speech_frames >= min_speech_frames and quiet_frames >= silence_frames:
                        break
            if not speech_started or speech_frames < min_speech_frames:
                return None
            pcm_data = self._prepare_for_stt(bytes(captured))
            self._write_wav(output_path, pcm_data)
            return output_path
        finally:
            self._terminate_process(proc)

    def play_wav(self, wav_path: Path, stop_event: Event | None = None) -> None:
        if not self.play_template:
            raise AudioError(
                "No hay backend de reproduccion configurado. Define PLAY_WAV_CMD."
            )
        command = _format_command(
            self.play_template,
            path=str(wav_path),
            speaker_device=self.config.speaker_device,
            rate=self.config.sample_rate,
            channels=self.config.channels,
        )
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            while proc.poll() is None:
                if stop_event and stop_event.is_set():
                    self._terminate_process(proc)
                    break
                time.sleep(0.1)
            if proc.returncode not in (0, None):
                stderr = proc.stderr.read().decode("utf-8", "replace").strip()
                raise AudioError(
                    f"El comando de reproduccion fallo ({proc.returncode}): {stderr}"
                )
        finally:
            self._terminate_process(proc)

    def _write_wav(self, output_path: Path, pcm_data: bytes) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1 if self.config.channels == 2 else self.config.channels)
            handle.setsampwidth(self.config.sample_width_bytes)
            handle.setframerate(16000 if self.config.sample_rate != 16000 else self.config.sample_rate)
            handle.writeframes(pcm_data)

    def _prepare_for_vad(self, pcm_data: bytes) -> bytes:
        if self.config.audio_gain == 1:
            return pcm_data
        return audioop.mul(
            pcm_data,
            self.config.sample_width_bytes,
            self.config.audio_gain,
        )

    def _prepare_for_stt(self, pcm_data: bytes) -> bytes:
        pcm_data = self._prepare_for_vad(pcm_data)
        if self.config.channels == 2:
            pcm_data = audioop.tomono(
                pcm_data,
                self.config.sample_width_bytes,
                0.5,
                0.5,
            )
        elif self.config.channels != 1:
            raise AudioError("Solo se admiten 1 o 2 canales de captura.")
        if self.config.sample_rate != 16000:
            pcm_data, _ = audioop.ratecv(
                pcm_data,
                self.config.sample_width_bytes,
                1,
                self.config.sample_rate,
                16000,
                None,
            )
        return pcm_data

    @staticmethod
    def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
