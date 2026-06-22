from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or value == "" else int(value)


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return default if not value else Path(value).expanduser()


@dataclass(frozen=True)
class AppConfig:
    runtime_dir: Path
    temp_audio_dir: Path
    log_file: Path
    local_api_key_path: Path
    usb_search_roots: tuple[Path, ...]
    usb_label: str
    api_key_filename: str
    gamepad_device: str
    gamepad_a_button_index: int
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frame_ms: int
    vad_threshold: int
    audio_gain: int
    min_speech_ms: int
    silence_ms: int
    max_record_ms: int
    record_pcm_cmd: str | None
    play_wav_cmd: str | None
    mic_device: str
    speaker_device: str
    stt_model: str
    chat_model: str
    tts_model: str
    tts_voice: str
    tts_instructions: str
    language: str
    system_prompt: str
    request_timeout_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        home = Path.home()
        runtime_dir = _env_path(
            "RVA_RUNTIME_DIR",
            home / ".local" / "state" / "rpi_voice_assistant",
        )
        temp_audio_dir = runtime_dir / "audio"
        log_file = runtime_dir / "assistant.log"
        local_api_key_path = _env_path(
            "LOCAL_API_KEY_PATH",
            home / ".config" / "rpi_voice_assistant" / "openai_api_key.txt",
        )
        usb_roots = os.getenv("USB_SEARCH_ROOTS")
        if usb_roots:
            roots = tuple(
                Path(part).expanduser()
                for part in usb_roots.split(":")
                if part.strip()
            )
        else:
            roots = (
                Path("/media"),
                Path("/mnt"),
                Path("/run/media"),
                Path("/run/mount"),
                Path("/writable"),
            )
        system_prompt = os.getenv(
            "OPENAI_SYSTEM_PROMPT",
            (
                "Eres un asistente de voz para una Raspberry Pi. "
                "Responde en espanol, de forma breve, clara y natural. "
                "Usa herramientas cuando necesites la hora, fecha, calculos, notas, alarmas locales, mover servos o ejecutar rutinas seguras del robot InMoov. "
                "Para varios movimientos de servo, esperas o repeticiones, usa una secuencia de servo. Para el robot InMoov completo, usa solo rutinas de robot disponibles; no inventes servos individuales ni angulos libres. Si el usuario pide una sola mano sin indicar izquierda o derecha, pregunta que mano; no ejecutes ambas manos. Para dedos individuales del robot, usa move_robot_finger: levantar o abrir equivale a open, cerrar o bajar equivale a closed. Para ordenes complejas con varias acciones del robot, usa run_robot_sequence en una sola llamada y no hagas una llamada por cada dedo o rutina. "
                "Para alarmas con hora relativa o incompleta, primero obten la fecha y hora actual "
                "y programa una fecha/hora futura. "
                "No digas que no puedes si una herramienta disponible resuelve la solicitud. "
                "No uses markdown ni listas a menos que la consulta lo exija."
            ),
        )
        return cls(
            runtime_dir=runtime_dir,
            temp_audio_dir=temp_audio_dir,
            log_file=log_file,
            local_api_key_path=local_api_key_path,
            usb_search_roots=roots,
            usb_label=os.getenv("USB_LABEL", "USB16GB"),
            api_key_filename=os.getenv("API_KEY_FILENAME", "api_key.txt"),
            gamepad_device=os.getenv("GAMEPAD_DEVICE", "/dev/input/js0"),
            gamepad_a_button_index=_env_int("GAMEPAD_A_BUTTON_INDEX", 0),
            sample_rate=_env_int("AUDIO_SAMPLE_RATE", 16000),
            channels=_env_int("AUDIO_CHANNELS", 1),
            sample_width_bytes=_env_int("AUDIO_SAMPLE_WIDTH_BYTES", 2),
            frame_ms=_env_int("AUDIO_FRAME_MS", 30),
            vad_threshold=_env_int("VAD_THRESHOLD", 700),
            audio_gain=_env_int("AUDIO_GAIN", 1),
            min_speech_ms=_env_int("MIN_SPEECH_MS", 300),
            silence_ms=_env_int("SILENCE_MS", 1200),
            max_record_ms=_env_int("MAX_RECORD_MS", 15000),
            record_pcm_cmd=os.getenv("RECORD_PCM_CMD"),
            play_wav_cmd=os.getenv("PLAY_WAV_CMD"),
            mic_device=os.getenv("MIC_DEVICE", "default"),
            speaker_device=os.getenv("SPEAKER_DEVICE", "default"),
            stt_model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"),
            chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-5.5"),
            tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=os.getenv("OPENAI_TTS_VOICE", "coral"),
            tts_instructions=os.getenv(
                "OPENAI_TTS_INSTRUCTIONS",
                "Habla en espanol con un tono natural y cercano.",
            ),
            language=os.getenv("OPENAI_LANGUAGE", "es"),
            system_prompt=system_prompt,
            request_timeout_seconds=_env_int("OPENAI_REQUEST_TIMEOUT_SECONDS", 90),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def ensure_runtime_dirs(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.temp_audio_dir.mkdir(parents=True, exist_ok=True)
        self.local_api_key_path.parent.mkdir(parents=True, exist_ok=True)
