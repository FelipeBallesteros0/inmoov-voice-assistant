from __future__ import annotations

import os
import select
import struct
from dataclasses import dataclass
from threading import Event


JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = struct.calcsize("IhBB")


class GamepadError(RuntimeError):
    pass


@dataclass(frozen=True)
class JoystickEvent:
    time_ms: int
    value: int
    event_type: int
    number: int

    @property
    def is_init(self) -> bool:
        return bool(self.event_type & JS_EVENT_INIT)

    @property
    def base_type(self) -> int:
        return self.event_type & ~JS_EVENT_INIT


def parse_joystick_event(data: bytes) -> JoystickEvent:
    if len(data) != JS_EVENT_SIZE:
        raise ValueError(f"Evento invalido de {len(data)} bytes")
    time_ms, value, event_type, number = struct.unpack("IhBB", data)
    return JoystickEvent(
        time_ms=time_ms,
        value=value,
        event_type=event_type,
        number=number,
    )


class JoystickButtonWatcher:
    def __init__(self, device_path: str, button_index: int) -> None:
        self.device_path = device_path
        self.button_index = button_index
        self._fd: int | None = None
        self._buffer = b""

    def open(self) -> None:
        if self._fd is not None:
            return
        try:
            self._fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            raise GamepadError(
                f"No se pudo abrir {self.device_path}. "
                "Revisa permisos del dispositivo de entrada."
            ) from exc

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            self._buffer = b""

    def wait_for_press(
        self,
        stop_event: Event | None = None,
        timeout_seconds: float = 0.2,
    ) -> bool:
        self.open()
        while True:
            if stop_event and stop_event.is_set():
                return False
            readable, _, _ = select.select([self._fd], [], [], timeout_seconds)
            if not readable:
                continue
            try:
                chunk = os.read(self._fd, JS_EVENT_SIZE * 16)
            except BlockingIOError:
                continue
            if not chunk:
                continue
            self._buffer += chunk
            while len(self._buffer) >= JS_EVENT_SIZE:
                raw_event = self._buffer[:JS_EVENT_SIZE]
                self._buffer = self._buffer[JS_EVENT_SIZE:]
                event = parse_joystick_event(raw_event)
                if event.is_init:
                    continue
                if event.base_type != JS_EVENT_BUTTON:
                    continue
                if event.number != self.button_index:
                    continue
                if event.value == 1:
                    return True


class KeyboardButtonWatcher:
    def __init__(self) -> None:
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def wait_for_press(
        self,
        stop_event: Event | None = None,
        timeout_seconds: float = 0.2,
    ) -> bool:
        if self._closed:
            return False
        print("Pulsa Enter para continuar/apagar.", flush=True)
        while True:
            if stop_event and stop_event.is_set():
                return False
            readable, _, _ = select.select([0], [], [], timeout_seconds)
            if not readable:
                continue
            input()
            return True
