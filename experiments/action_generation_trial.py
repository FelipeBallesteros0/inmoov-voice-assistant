#!/usr/bin/env python3
"""Registro empirico de generacion de acciones a nivel de software.

Corre el pipeline completo de voz (captura local con VAD por energia, ASR remoto y
LLM con function calling) sobre los mismos comandos semanticos repetidos, y guarda en
JSONL la configuracion articular que el modelo genera en cada realizacion.

Pensado para correr con la capa de actuacion desacoplada (`ROBOT_DRY_RUN=1`): la
consigna se genera, se valida contra los limites articulares y se arma el comando
serial, pero no se abre el puerto del Arduino Mega. Con `ROBOT_TOOLS_MODE=joints_only`
el modelo solo ve la interfaz generalizada (`get_robot_status` / `set_robot_joints`).

Uso tipico en la Raspberry Pi:

    ROBOT_DRY_RUN=1 ROBOT_TOOLS_MODE=joints_only GAMEPAD_DEVICE=keyboard \\
    python3 experiments/action_generation_trial.py --reps 3

Cada turno espera Enter, graba hasta detectar silencio y reinicia el historial de
dialogo, de modo que las repeticiones de un mismo comando son independientes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_assistant import openai_client as openai_client_module  # noqa: E402
from voice_assistant.audio_io import AudioError  # noqa: E402
from voice_assistant.openai_client import EmptyTranscriptionError, OpenAIClientError  # noqa: E402
from voice_assistant.robot import dry_run_enabled  # noqa: E402
from voice_assistant.session_controller import build_context  # noqa: E402
from voice_assistant.tools import call_tool as real_call_tool  # noqa: E402
from voice_assistant.tools import robot_tools_mode  # noqa: E402

DEFAULT_COMMANDS = (
    "saluda",
    "festeja",
    "haz una pose de robot",
    "haz un gesto de bienvenida",
)

# Prompt del trial: describe la interfaz y las convenciones del InMoov, pero no dice que
# articulaciones usar para cada comando. Cualquier postura concreta la compone el modelo.
TRIAL_SYSTEM_PROMPT = (
    "Eres el sistema de control por voz de un robot humanoide InMoov. "
    "Responde en espanol, de forma breve y natural. "
    "Para cualquier accion fisica del robot usa set_robot_joints con pares articulacion-angulo; "
    "puedes consultar get_robot_status si necesitas saber si el robot esta disponible. "
    "Compon la postura eligiendo las articulaciones y los angulos que mejor expresen la orden. "
    "Convencion del InMoov: en los dedos 0 grados = flexionado (mano cerrada) y el angulo de reposo "
    "del dedo = estirado (mano abierta); mandibula 10 cerrada / 70 abierta; cabeza 90 al frente, "
    "10 izquierda, 170 derecha. "
    "No uses markdown ni listas."
)


def apply_trial_system_prompt(env: dict[str, str] | None = None) -> str:
    """Fija el prompt del trial si el operador no definio uno propio."""
    env = os.environ if env is None else env
    if not env.get("OPENAI_SYSTEM_PROMPT"):
        env["OPENAI_SYSTEM_PROMPT"] = TRIAL_SYSTEM_PROMPT
    return env["OPENAI_SYSTEM_PROMPT"]


@dataclass
class ToolCallRecord:
    name: str
    arguments: Any
    result: Any
    accepted_at: float | None = None


@dataclass
class TurnRecorder:
    """Envuelve `call_tool` para capturar lo que el modelo pide durante un turno."""

    calls: list[ToolCallRecord] = field(default_factory=list)

    def __call__(self, name: str, arguments: str | dict) -> str:
        raw_result = real_call_tool(name, arguments)
        try:
            parsed_result = json.loads(raw_result)
        except json.JSONDecodeError:
            parsed_result = raw_result
        try:
            parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            parsed_arguments = arguments

        record = ToolCallRecord(name=name, arguments=parsed_arguments, result=parsed_result)
        # El instante de aceptacion local es cuando la consigna articular pasa la
        # validacion de limites y queda lista para el envio serial.
        if name == "set_robot_joints" and isinstance(parsed_result, dict) and parsed_result.get("ok"):
            record.accepted_at = time.monotonic()
        self.calls.append(record)
        return raw_result

    @property
    def joint_calls(self) -> list[ToolCallRecord]:
        return [call for call in self.calls if call.name == "set_robot_joints"]

    @property
    def accepted_calls(self) -> list[ToolCallRecord]:
        """Un turno puede producir varias consignas sucesivas (un movimiento, no una pose)."""
        return [call for call in self.joint_calls if call.accepted_at is not None]

    @property
    def first_accepted(self) -> ToolCallRecord | None:
        accepted = self.accepted_calls
        return accepted[0] if accepted else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commands", nargs="+", default=list(DEFAULT_COMMANDS))
    parser.add_argument("--reps", type=int, default=3, help="Repeticiones por comando (defecto: 3)")
    parser.add_argument("--output", type=Path, default=None, help="Ruta del JSONL de salida")
    parser.add_argument("--tts", action="store_true", help="Sintetiza y reproduce la respuesta del modelo")
    return parser.parse_args(argv)


def build_turn_plan(commands: list[str], reps: int) -> list[tuple[int, str, int]]:
    """Turnos agrupados por comando: todas las repeticiones de uno, luego el siguiente."""
    plan = []
    turn_id = 1
    for command in commands:
        for rep in range(1, reps + 1):
            plan.append((turn_id, command, rep))
            turn_id += 1
    return plan


def summarize_joints(record: ToolCallRecord | None) -> str:
    if record is None or not isinstance(record.result, dict):
        return "(sin consigna articular)"
    moved = record.result.get("joints_moved") or []
    return ", ".join(f"{item['joint']}:{item['angle_degrees']}" for item in moved) or "(vacia)"


def run_turn(context, recorder: TurnRecorder, turn_id: int, command: str, rep: int, use_tts: bool) -> dict:
    config = context.config
    stop_event = threading.Event()

    recording_path = config.temp_audio_dir / f"trial-{turn_id:02d}-{int(time.time() * 1000)}.wav"
    spoken_audio = context.audio.record_until_silence(recording_path, stop_event=stop_event)
    capture_end = time.monotonic()
    if spoken_audio is None:
        return {"turn_id": turn_id, "command_label": command, "repetition": rep, "error": "sin voz detectada"}

    asr_start = time.monotonic()
    transcript = context.openai.transcribe(spoken_audio)
    asr_seconds = time.monotonic() - asr_start

    # Historial vacio: cada repeticion parte de la misma condicion inicial.
    llm_start = time.monotonic()
    reply_text = context.openai.reply(transcript, [])
    llm_seconds = time.monotonic() - llm_start

    accepted_calls = recorder.accepted_calls
    accepted = accepted_calls[0] if accepted_calls else None
    # T_total se mide hasta la PRIMERA consigna aceptada: es el instante en que la
    # capa de control acepta una accion ejecutable, como define el paper.
    total_seconds = (accepted.accepted_at - capture_end) if accepted else None

    if use_tts:
        reply_path = config.temp_audio_dir / f"trial-reply-{turn_id:02d}.wav"
        context.openai.synthesize(reply_text, reply_path)
        context.audio.play_wav(reply_path, stop_event=stop_event)

    return {
        "turn_id": turn_id,
        "command_label": command,
        "repetition": rep,
        "timestamp": datetime.now().astimezone().isoformat(),
        "audio_file": str(spoken_audio),
        "transcript": transcript,
        "reply_text": reply_text,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments, "result": call.result}
            for call in recorder.calls
        ],
        "joints_generated": (accepted.result.get("joints_moved") if accepted else None),
        "serial_command": (accepted.result.get("command") if accepted else None),
        # Secuencia completa: el modelo puede componer varias consignas en un turno.
        "configuration_steps": [call.result.get("joints_moved") for call in accepted_calls],
        "serial_commands": [call.result.get("command") for call in accepted_calls],
        "limit_validation_passed": accepted is not None,
        "joint_call_count": len(recorder.joint_calls),
        "accepted_call_count": len(accepted_calls),
        "latency_seconds": {
            "asr": round(asr_seconds, 3),
            "llm": round(llm_seconds, 3),
            "total": round(total_seconds, 3) if total_seconds is not None else None,
        },
        "models": {"stt": config.stt_model, "chat": config.chat_model},
        "dry_run": dry_run_enabled(),
        "robot_tools_mode": robot_tools_mode(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    apply_trial_system_prompt()
    context = build_context()
    plan = build_turn_plan(args.commands, args.reps)

    output_path = args.output or (
        Path(__file__).resolve().parent / "data" / f"trial-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Trial de generacion de acciones: {len(plan)} turnos")
    print(f"  dry_run={dry_run_enabled()}  tools_mode={robot_tools_mode()}")
    print(f"  ASR={context.config.stt_model}  LLM={context.config.chat_model}")
    print(f"  salida: {output_path}\n")
    if not dry_run_enabled():
        print("AVISO: ROBOT_DRY_RUN no esta activo; las consignas se enviaran al Arduino.\n")

    stop_event = threading.Event()
    completed = 0
    with output_path.open("a", encoding="utf-8") as sink:
        for turn_id, command, rep in plan:
            print(f"[{turn_id}/{len(plan)}] Di: \"{command}\" (repeticion {rep})")
            print("      Enter para empezar a grabar, Ctrl-C para abortar.")
            if not context.gamepad.wait_for_press(stop_event):
                print("      Sin pulsacion; se aborta el trial.")
                break

            recorder = TurnRecorder()
            try:
                with mock.patch.object(openai_client_module, "call_tool", recorder):
                    turn = run_turn(context, recorder, turn_id, command, rep, args.tts)
            except EmptyTranscriptionError:
                print("      No se detecto voz clara; se repite este turno.\n")
                continue
            except (AudioError, OpenAIClientError) as exc:
                print(f"      Fallo el turno: {exc}\n")
                turn = {
                    "turn_id": turn_id,
                    "command_label": command,
                    "repetition": rep,
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "error": str(exc),
                }

            sink.write(json.dumps(turn, ensure_ascii=False) + "\n")
            sink.flush()
            completed += 1

            if turn.get("error"):
                print(f"      ERROR: {turn['error']}\n")
                continue
            print(f"      transcripcion: {turn['transcript']}")
            print(f"      consignas aceptadas: {turn['accepted_call_count']}")
            for step, call in enumerate(recorder.accepted_calls, start=1):
                print(f"        {step}. {summarize_joints(call)}")
            latency = turn["latency_seconds"]
            print(f"      T_ASR={latency['asr']}s  T_LLM={latency['llm']}s  T_total={latency['total']}s\n")

    context.gamepad.close()
    print(f"Listo: {completed} turnos registrados en {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
