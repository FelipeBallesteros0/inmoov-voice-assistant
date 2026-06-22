from __future__ import annotations

import os
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

ROBOT_ROUTINES = (
    "demo",
    "rest",
    "open_left_hand",
    "close_left_hand",
    "open_right_hand",
    "close_right_hand",
    "open_hands",
    "close_hands",
    "head_center",
    "head_left",
    "head_right",
    "head_nod",
    "arms_open",
    "arms_rest",
)
ROBOT_HANDS = ("left", "right")
ROBOT_FINGERS = ("thumb", "index", "middle", "ring", "pinky")
ROBOT_FINGER_POSITIONS = ("open", "closed")
ROBOT_SEQUENCE_ACTION_TYPES = ("finger", "routine")
ROBOT_SEQUENCE_NONE = "none"
MAX_ROBOT_SEQUENCE_ACTIONS = 20

_HAND_ALIASES = {
    "left": "left",
    "izquierda": "left",
    "izquierdo": "left",
    "right": "right",
    "derecha": "right",
    "derecho": "right",
}
_FINGER_ALIASES = {
    "thumb": "thumb",
    "pulgar": "thumb",
    "index": "index",
    "indice": "index",
    "middle": "middle",
    "medio": "middle",
    "ring": "ring",
    "anular": "ring",
    "pinky": "pinky",
    "menique": "pinky",
}
_ACTION_TYPE_ALIASES = {
    "finger": "finger",
    "dedo": "finger",
    "routine": "routine",
    "rutina": "routine",
}
_POSITION_ALIASES = {
    "open": "open",
    "opened": "open",
    "up": "open",
    "arriba": "open",
    "abrir": "open",
    "abre": "open",
    "abierto": "open",
    "levanta": "open",
    "levantar": "open",
    "levantado": "open",
    "closed": "closed",
    "close": "closed",
    "down": "closed",
    "abajo": "closed",
    "baja": "closed",
    "bajar": "closed",
    "cerrar": "closed",
    "cierra": "closed",
    "cerrado": "closed",
}

DEFAULT_PORT_CANDIDATES = (
    "/dev/ttyUSB0",
    "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
    "/dev/serial/by-id/usb-Arduino__www.arduino.cc__0042-if00",
    "/dev/ttyACM0",
)
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT_SECONDS = 180.0


class RobotError(RuntimeError):
    pass


@dataclass(frozen=True)
class RobotCommandResult:
    ok: bool
    command: str
    port: str
    response: str


def run_robot_routine(routine_name: str) -> RobotCommandResult:
    routine = _normalize_routine(routine_name)
    return _send_robot_command(f"ROBOT ROUTINE {routine}", expected_prefix=f"OK ROUTINE {routine}")


def get_robot_status() -> RobotCommandResult:
    return _send_robot_command("ROBOT STATUS", expected_prefix="OK STATUS")


def move_robot_finger(hand: str, finger: str, position: str) -> RobotCommandResult:
    command, expected = _finger_command(hand, finger, position)
    return _send_robot_command(command, expected_prefix=expected)


def run_robot_sequence(actions: list[dict[str, Any]]) -> dict:
    commands = _normalize_robot_sequence(actions)
    return _send_robot_command_sequence(commands)


def _finger_command(hand: str, finger: str, position: str) -> tuple[str, str]:
    normalized_hand = _normalize_choice(hand, _HAND_ALIASES, "mano", ROBOT_HANDS)
    normalized_finger = _normalize_choice(finger, _FINGER_ALIASES, "dedo", ROBOT_FINGERS)
    normalized_position = _normalize_choice(
        position,
        _POSITION_ALIASES,
        "posicion del dedo",
        ROBOT_FINGER_POSITIONS,
    )
    command = f"ROBOT FINGER {normalized_hand} {normalized_finger} {normalized_position}"
    expected = f"OK FINGER {normalized_hand} {normalized_finger} {normalized_position}"
    return command, expected


def _routine_command(routine_name: str) -> tuple[str, str]:
    routine = _normalize_routine(routine_name)
    return f"ROBOT ROUTINE {routine}", f"OK ROUTINE {routine}"


def _normalize_robot_sequence(actions: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    if not isinstance(actions, list):
        raise RobotError("La secuencia del robot debe ser una lista de acciones.")
    if not actions:
        raise RobotError("La secuencia del robot no puede estar vacia.")
    if len(actions) > MAX_ROBOT_SEQUENCE_ACTIONS:
        raise RobotError(f"La secuencia del robot acepta maximo {MAX_ROBOT_SEQUENCE_ACTIONS} acciones.")

    commands: list[tuple[str, str, float]] = []
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise RobotError(f"La accion {index} de la secuencia no es valida.")
        action_type = _normalize_choice(
            action.get("action_type", ""),
            _ACTION_TYPE_ALIASES,
            "tipo de accion",
            ROBOT_SEQUENCE_ACTION_TYPES,
        )
        delay_after_seconds = _normalize_delay(action.get("delay_after_seconds", 0), index)
        if action_type == "finger":
            command, expected = _finger_command(
                _required_action_value(action, "hand", index),
                _required_action_value(action, "finger", index),
                _required_action_value(action, "position", index),
            )
        else:
            command, expected = _routine_command(
                _required_action_value(action, "routine_name", index),
            )
        commands.append((command, expected, delay_after_seconds))
    return commands


def _required_action_value(action: dict[str, Any], key: str, index: int) -> str:
    value = action.get(key, "")
    if _normalize_text(value) in ("", ROBOT_SEQUENCE_NONE):
        raise RobotError(f"Falta {key} en la accion {index} de la secuencia.")
    return str(value)


def _normalize_delay(value: Any, index: int) -> float:
    try:
        delay = float(value)
    except (TypeError, ValueError) as exc:
        raise RobotError(f"delay_after_seconds invalido en la accion {index}.") from exc
    if delay < 0 or delay > 10:
        raise RobotError(f"delay_after_seconds debe estar entre 0 y 10 en la accion {index}.")
    return delay


def _normalize_routine(routine_name: str) -> str:
    routine = "_".join(_normalize_text(routine_name).replace("-", "_").split())
    if routine not in ROBOT_ROUTINES:
        allowed = ", ".join(ROBOT_ROUTINES)
        raise RobotError(f"Rutina de robot desconocida: {routine_name}. Permitidas: {allowed}")
    return routine


def _normalize_choice(value: str, aliases: dict[str, str], label: str, allowed_values: tuple[str, ...]) -> str:
    key = "_".join(_normalize_text(value).replace("-", "_").split())
    if key in aliases:
        return aliases[key]
    allowed = ", ".join(allowed_values)
    raise RobotError(f"{label.capitalize()} desconocida: {value}. Permitidas: {allowed}")


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).strip().lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _resolve_robot_port() -> str:
    configured = os.getenv("ROBOT_SERIAL_PORT")
    candidates = (configured, *DEFAULT_PORT_CANDIDATES) if configured else DEFAULT_PORT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RobotError("No encontre el Arduino Mega del robot. Configura ROBOT_SERIAL_PORT o conecta la placa.")


def _send_robot_command(command: str, expected_prefix: str) -> RobotCommandResult:
    result = _send_robot_command_sequence([(command, expected_prefix, 0.0)])
    first = result["results"][0]
    return RobotCommandResult(
        ok=True,
        command=first["command"],
        port=result["port"],
        response=first["response"],
    )


def _send_robot_command_sequence(commands: list[tuple[str, str, float]]) -> dict:
    if serial is None:
        raise RobotError("Falta instalar pyserial para controlar el robot.")

    port = _resolve_robot_port()
    baudrate = int(os.getenv("ROBOT_SERIAL_BAUDRATE", str(DEFAULT_BAUDRATE)))
    timeout = float(os.getenv("ROBOT_SERIAL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    ready_delay = float(os.getenv("ROBOT_SERIAL_READY_DELAY_SECONDS", "2.5"))
    results = []

    try:
        with serial.Serial(port, baudrate, timeout=timeout, write_timeout=timeout) as handle:
            time.sleep(ready_delay)
            handle.reset_input_buffer()
            for command, expected_prefix, delay_after_seconds in commands:
                handle.write((command + "\n").encode("ascii"))
                handle.flush()
                response = _read_response(handle, expected_prefix)
                results.append({"command": command, "response": response})
                if delay_after_seconds:
                    time.sleep(delay_after_seconds)
    except RobotError:
        raise
    except Exception as exc:
        raise RobotError(f"No pude comunicarme con el Arduino Mega en {port}: {exc}") from exc

    return {
        "ok": True,
        "port": port,
        "actions_executed": len(results),
        "results": results,
    }


def _read_response(handle, expected_prefix: str) -> str:
    while True:
        raw = handle.readline()
        if not raw:
            raise RobotError("El Arduino Mega no respondio al comando del robot.")
        response = raw.decode("utf-8", "replace").strip()
        if not response or response == "READY":
            continue
        if response.startswith("ERR"):
            raise RobotError(f"Arduino Mega rechazo el comando: {response}")
        if response.startswith(expected_prefix):
            return response
        raise RobotError(f"Respuesta inesperada del Arduino Mega: {response}")
