from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import serial
except ImportError:  # pragma: no cover - exercised only on missing dependency
    serial = None

DEFAULT_PORT_CANDIDATES = (
    "/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_7513931383135120D090-if00",
    "/dev/ttyACM0",
    "/dev/ttyUSB0",
)
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT_SECONDS = 3.0


class ServoError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServoMoveResult:
    moved: bool
    angle: int
    port: str
    response: str


def move_servo(angle_degrees: int | str) -> ServoMoveResult:
    angle = _parse_angle(angle_degrees)
    port = _resolve_serial_port()
    response = _send_servo_command(port, angle)
    return ServoMoveResult(
        moved=True,
        angle=angle,
        port=port,
        response=response,
    )


def run_servo_sequence(steps: list[dict[str, Any]], repeat: int | str = 1) -> dict[str, Any]:
    repeat_count = _parse_repeat(repeat)
    parsed_steps = _parse_steps(steps)
    port = _resolve_serial_port()
    results: list[dict[str, Any]] = []

    with _open_serial_port(port) as handle:
        for cycle in range(1, repeat_count + 1):
            for index, step in enumerate(parsed_steps, start=1):
                angle = step["angle"]
                response = _write_servo_command(handle, angle)
                results.append(
                    {
                        "cycle": cycle,
                        "step": index,
                        "angle": angle,
                        "response": response,
                    }
                )
                delay_seconds = step["delay_after_seconds"]
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

    return {
        "completed": True,
        "repeat": repeat_count,
        "port": port,
        "steps_executed": len(results),
        "results": results,
    }


def _parse_angle(value: int | str) -> int:
    try:
        angle = int(value)
    except (TypeError, ValueError) as exc:
        raise ServoError("El angulo debe ser un numero entero entre 0 y 180.") from exc
    if angle < 0 or angle > 180:
        raise ServoError("El angulo debe estar entre 0 y 180 grados.")
    return angle


def _parse_repeat(value: int | str) -> int:
    try:
        repeat = int(value)
    except (TypeError, ValueError) as exc:
        raise ServoError("La repeticion debe ser un numero entero entre 1 y 10.") from exc
    if repeat < 1 or repeat > 10:
        raise ServoError("La repeticion debe estar entre 1 y 10.")
    return repeat


def _parse_steps(steps: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    if not isinstance(steps, list) or not steps:
        raise ServoError("La secuencia necesita al menos un paso.")
    if len(steps) > 20:
        raise ServoError("La secuencia no puede tener mas de 20 pasos.")

    parsed: list[dict[str, float | int]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ServoError("Cada paso de servo debe ser un objeto.")
        angle = _parse_angle(step.get("angle_degrees"))
        delay_value = step.get("delay_after_seconds", 0)
        try:
            delay_seconds = float(delay_value)
        except (TypeError, ValueError) as exc:
            raise ServoError("El delay debe ser un numero entre 0 y 10 segundos.") from exc
        if delay_seconds < 0 or delay_seconds > 10:
            raise ServoError("El delay debe estar entre 0 y 10 segundos.")
        parsed.append({"angle": angle, "delay_after_seconds": delay_seconds})
    return parsed


def _resolve_serial_port() -> str:
    configured = os.getenv("SERVO_SERIAL_PORT")
    candidates = (configured, *DEFAULT_PORT_CANDIDATES) if configured else DEFAULT_PORT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise ServoError(
        "No encontre el Arduino en puerto serial. "
        "Configura SERVO_SERIAL_PORT o conecta el Arduino."
    )


def _send_servo_command(port: str, angle: int) -> str:
    with _open_serial_port(port) as handle:
        return _write_servo_command(handle, angle)


def _open_serial_port(port: str):
    if serial is None:
        raise ServoError("Falta instalar pyserial para controlar el Arduino.")

    baudrate = int(os.getenv("SERVO_SERIAL_BAUDRATE", str(DEFAULT_BAUDRATE)))
    timeout = float(os.getenv("SERVO_SERIAL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    try:
        handle = serial.Serial(port, baudrate, timeout=timeout, write_timeout=timeout)
    except Exception as exc:
        raise ServoError(f"No pude abrir el Arduino en {port}: {exc}") from exc

    try:
        time.sleep(float(os.getenv("SERVO_SERIAL_READY_DELAY_SECONDS", "2.0")))
        handle.reset_input_buffer()
        return handle
    except Exception:
        handle.close()
        raise


def _write_servo_command(handle, angle: int) -> str:
    command = f"SERVO {angle}\n".encode("ascii")
    try:
        handle.write(command)
        handle.flush()
        raw_response = handle.readline()
    except Exception as exc:
        raise ServoError(f"No pude comunicarme con el Arduino: {exc}") from exc

    response = raw_response.decode("utf-8", "replace").strip()
    if response == f"OK {angle}":
        return response
    if response.startswith("ERR"):
        raise ServoError(f"Arduino rechazo el comando: {response}")
    if not response:
        raise ServoError("Arduino no respondio al comando del servo.")
    raise ServoError(f"Respuesta inesperada del Arduino: {response}")
