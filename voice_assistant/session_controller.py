from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .alarms import pop_due_alarms
from .audio_io import AudioError, CommandAudioIO
from .config import AppConfig
from .gamepad import GamepadError, JoystickButtonWatcher, KeyboardButtonWatcher
from .openai_client import EmptyTranscriptionError, HistoryMessage, OpenAIClient, OpenAIClientError
from .secrets import ResolvedSecret, SecretError, resolve_api_key


class AppState(str, Enum):
    IDLE = "idle"
    CONVERSATION = "conversation"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    SHUTDOWN = "shutdown"


@dataclass
class AppContext:
    config: AppConfig
    logger: logging.Logger
    secret: ResolvedSecret
    audio: CommandAudioIO
    openai: OpenAIClient
    gamepad: JoystickButtonWatcher
    history: list[HistoryMessage] = field(default_factory=list)
    state: AppState = AppState.IDLE


class SessionController:
    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.shutdown_event = threading.Event()
        self.button_events: queue.Queue[float] = queue.Queue()
        self.listener_error: GamepadError | None = None
        self._button_press_count = 0
        self.listener_thread = threading.Thread(
            target=self._button_listener,
            name="gamepad-listener",
            daemon=True,
        )

    def run(self) -> int:
        self.listener_thread.start()
        self.context.logger.info("Esperando primera pulsacion del boton A.")
        while True:
            if self.shutdown_event.is_set():
                if self.listener_error is not None:
                    raise self.listener_error
                raise GamepadError("El listener del mando se detuvo antes de iniciar.")
            try:
                self.button_events.get(timeout=0.2)
                break
            except queue.Empty:
                continue
        self.context.state = AppState.CONVERSATION
        self.context.logger.info("Modo conversacion activado.")

        while not self.shutdown_event.is_set():
            if self._consume_shutdown_press():
                break
            self._announce_due_alarms()
            if self.shutdown_event.is_set():
                break

            self.context.logger.info("Esperando voz.")
            recording_path = (
                self.context.config.temp_audio_dir
                / f"input-{int(time.time() * 1000)}.wav"
            )
            spoken_audio = self.context.audio.record_until_silence(
                recording_path,
                stop_event=self.shutdown_event,
            )
            if self.shutdown_event.is_set():
                break
            if spoken_audio is None:
                continue

            try:
                self.context.state = AppState.PROCESSING
                transcript = self.context.openai.transcribe(spoken_audio)
                if self.shutdown_event.is_set():
                    break
                self.context.logger.info("Transcripcion: %s", transcript)

                reply = self.context.openai.reply(transcript, self.context.history)
                if self.shutdown_event.is_set():
                    break
                self.context.logger.info("Respuesta generada.")
                self.context.history.append(HistoryMessage(role="user", text=transcript))
                self.context.history.append(HistoryMessage(role="assistant", text=reply))
                self.context.history[:] = self.context.history[-12:]

                response_path = (
                    self.context.config.temp_audio_dir
                    / f"reply-{int(time.time() * 1000)}.wav"
                )
                self.context.openai.synthesize(reply, response_path)
                if self.shutdown_event.is_set():
                    break

                self.context.state = AppState.SPEAKING
                self.context.audio.play_wav(response_path, stop_event=self.shutdown_event)
                self.context.state = AppState.CONVERSATION
            except EmptyTranscriptionError:
                self.context.logger.info("No se detecto voz clara en el audio grabado.")
                if self.shutdown_event.is_set():
                    break
                self.context.state = AppState.CONVERSATION
                continue
            except (AudioError, OpenAIClientError) as exc:
                self.context.logger.exception("Fallo el turno de conversacion: %s", exc)
                if self.shutdown_event.is_set():
                    break
                self.context.state = AppState.CONVERSATION
                continue

        self.context.state = AppState.SHUTDOWN
        self.context.gamepad.close()
        self.context.logger.info("Programa detenido.")
        return 0

    def _button_listener(self) -> None:
        try:
            while not self.shutdown_event.is_set():
                if self.context.gamepad.wait_for_press(self.shutdown_event):
                    self._button_press_count += 1
                    self.button_events.put(time.time())
                    self.context.logger.info("Boton A detectado.")
                    if self._button_press_count > 1:
                        self.context.logger.info("Pulsacion de apagado detectada.")
                        self.shutdown_event.set()
                        break
        except GamepadError as exc:
            self.listener_error = exc
            self.context.logger.exception("No se pudo leer el mando.")
            self.shutdown_event.set()
        finally:
            self.context.gamepad.close()

    def _consume_shutdown_press(self) -> bool:
        try:
            self.button_events.get_nowait()
        except queue.Empty:
            return False
        self.context.logger.info("Segunda pulsacion detectada. Apagando.")
        self.shutdown_event.set()
        return True

    def _announce_due_alarms(self) -> None:
        try:
            due_alarms = pop_due_alarms()
        except Exception as exc:
            self.context.logger.exception("No se pudieron leer las alarmas: %s", exc)
            return

        for alarm in due_alarms:
            if self.shutdown_event.is_set():
                return
            message = str(alarm.get("message") or "Tienes una alarma pendiente.")
            self.context.logger.info("Alarma vencida: %s", message)
            response_path = (
                self.context.config.temp_audio_dir
                / f"alarm-{int(time.time() * 1000)}.wav"
            )
            try:
                self.context.state = AppState.SPEAKING
                self.context.openai.synthesize(f"Alarma: {message}", response_path)
                if self.shutdown_event.is_set():
                    return
                self.context.audio.play_wav(response_path, stop_event=self.shutdown_event)
            except (AudioError, OpenAIClientError) as exc:
                self.context.logger.exception("Fallo al reproducir alarma: %s", exc)
            finally:
                if not self.shutdown_event.is_set():
                    self.context.state = AppState.CONVERSATION


def setup_logging(config: AppConfig) -> logging.Logger:
    config.ensure_runtime_dirs()
    logger = logging.getLogger("rpi_voice_assistant")
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def build_context() -> AppContext:
    config = AppConfig.from_env()
    logger = setup_logging(config)
    secret = resolve_api_key(config)
    logger.info("API key resuelta desde: %s", secret.source)
    audio = CommandAudioIO(config)
    openai = OpenAIClient(secret.api_key, config)
    if config.gamepad_device == "keyboard":
        logger.info("Usando Enter en terminal como boton de control.")
        gamepad = KeyboardButtonWatcher()
    else:
        gamepad = JoystickButtonWatcher(
            device_path=config.gamepad_device,
            button_index=config.gamepad_a_button_index,
        )
    return AppContext(
        config=config,
        logger=logger,
        secret=secret,
        audio=audio,
        openai=openai,
        gamepad=gamepad,
    )


def run_application() -> int:
    try:
        context = build_context()
        controller = SessionController(context)
        return controller.run()
    except (AudioError, GamepadError, OpenAIClientError, SecretError) as exc:
        print(f"ERROR: {exc}")
        return 1
