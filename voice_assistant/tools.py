from __future__ import annotations

import ast
import json
import operator
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .alarms import cancel_alarm, list_alarms, schedule_alarm
from .robot import ROBOT_JOINT_NAMES, get_robot_status, set_robot_joints
from .servo import move_servo, run_servo_sequence


def tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "get_current_datetime",
            "description": "Obtiene la fecha y hora local actual de la Raspberry.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "calculate_expression",
            "description": "Calcula una expresion aritmetica simple.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expresion con numeros y operadores, por ejemplo: (25 * 17) / 2",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "save_note",
            "description": "Guarda una nota local con titulo y contenido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["title", "content"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "list_notes",
            "description": "Lista las notas locales guardadas.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "read_note",
            "description": "Lee una nota local por nombre de archivo o titulo.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "schedule_alarm",
            "description": (
                "Programa una alarma local de una sola vez. Usa get_current_datetime "
                "antes si el usuario da una hora relativa o incompleta. due_at debe "
                "ser una fecha/hora futura en ISO 8601, idealmente con zona horaria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "due_at": {
                        "type": "string",
                        "description": "Ejemplo: 2026-06-11T19:00:00-04:00",
                    },
                    "message": {
                        "type": "string",
                        "description": "Texto que se dira cuando llegue la alarma.",
                    },
                },
                "required": ["due_at", "message"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "list_alarms",
            "description": "Lista las alarmas locales pendientes o todas si se solicita historial.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_triggered": {
                        "type": "boolean",
                        "description": "Incluye alarmas ya disparadas o canceladas.",
                    }
                },
                "required": ["include_triggered"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "cancel_alarm",
            "description": "Cancela una alarma pendiente por su id.",
            "parameters": {
                "type": "object",
                "properties": {"alarm_id": {"type": "string"}},
                "required": ["alarm_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "move_servo",
            "description": "Mueve el servo conectado al Arduino a un angulo absoluto entre 0 y 180 grados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "angle_degrees": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 180,
                        "description": "Angulo destino del servo en grados.",
                    }
                },
                "required": ["angle_degrees"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "run_servo_sequence",
            "description": "Ejecuta una secuencia de movimientos del servo con esperas y repeticiones en una sola llamada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repeat": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Cantidad de veces que se repite toda la secuencia.",
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "angle_degrees": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 180,
                                },
                                "delay_after_seconds": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 10,
                                },
                            },
                            "required": ["angle_degrees", "delay_after_seconds"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["repeat", "steps"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_robot_status",
            "description": "Consulta si el robot InMoov conectado al Arduino Mega esta disponible, detenido o ejecutando un movimiento.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "set_robot_joints",
            "description": (
                "Mueve una o mas articulaciones del robot InMoov usando pares nombre-angulo. "
                "Las articulaciones omitidas mantienen su posicion actual. Usa get_robot_status "
                "si necesitas comprobar disponibilidad antes de mover."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "joints": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 21,
                        "items": {
                            "type": "object",
                            "properties": {
                                "joint": {
                                    "type": "string",
                                    "enum": list(ROBOT_JOINT_NAMES),
                                    "description": "Nombre de la articulacion segun el firmware del InMoov.",
                                },
                                "angle_degrees": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 180,
                                    "description": "Angulo absoluto en grados; se valida contra el rango seguro de cada articulacion.",
                                },
                            },
                            "required": ["joint", "angle_degrees"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["joints"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def call_tool(name: str, arguments: str | dict) -> str:
    try:
        args = _parse_arguments(arguments)
        if name == "get_current_datetime":
            result = {"now": datetime.now(ZoneInfo("America/Santiago")).isoformat()}
        elif name == "calculate_expression":
            result = {"result": safe_calculate(str(args["expression"]))}
        elif name == "save_note":
            result = save_note(str(args["title"]), str(args["content"]))
        elif name == "list_notes":
            result = {"notes": list_notes()}
        elif name == "read_note":
            result = read_note(str(args["name"]))
        elif name == "schedule_alarm":
            result = schedule_alarm(str(args["due_at"]), str(args["message"]))
        elif name == "list_alarms":
            result = {"alarms": list_alarms(bool(args["include_triggered"]))}
        elif name == "cancel_alarm":
            result = cancel_alarm(str(args["alarm_id"]))
        elif name == "move_servo":
            servo_result = move_servo(args["angle_degrees"])
            result = {
                "moved": servo_result.moved,
                "angle": servo_result.angle,
                "port": servo_result.port,
                "response": servo_result.response,
            }
        elif name == "run_servo_sequence":
            result = run_servo_sequence(args["steps"], args["repeat"])
        elif name == "get_robot_status":
            robot_result = get_robot_status()
            result = {
                "ok": robot_result.ok,
                "command": robot_result.command,
                "port": robot_result.port,
                "response": robot_result.response,
            }
        elif name == "set_robot_joints":
            result = set_robot_joints(args["joints"])
        else:
            result = {"error": f"Herramienta desconocida: {name}"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def _parse_arguments(arguments: str | dict) -> dict:
    if isinstance(arguments, dict):
        return arguments
    return json.loads(arguments or "{}")


def safe_calculate(expression: str) -> float:
    if len(expression) > 120:
        raise ValueError("La expresion es demasiado larga.")
    node = ast.parse(expression, mode="eval")
    return float(_eval_node(node.body))


def _eval_node(node: ast.AST) -> float:
    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("Exponente demasiado grande.")
        return float(binary_ops[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
        return float(unary_ops[type(node.op)](_eval_node(node.operand)))
    raise ValueError("Solo se permiten numeros y operadores aritmeticos simples.")


def _notes_dir() -> Path:
    configured = os.getenv("RVA_NOTES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "rpi_voice_assistant_notes"


def _safe_note_name(title: str) -> str:
    clean = "".join(
        ch
        for ch in title.strip().lower().replace(" ", "_")
        if ch.isalnum() or ch in "-_"
    )
    return (clean or "nota")[:80] + ".txt"


def save_note(title: str, content: str) -> dict:
    notes_dir = _notes_dir()
    notes_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_note_name(title)
    path = notes_dir / filename
    path.write_text(f"{title.strip()}\n\n{content.strip()}\n", encoding="utf-8")
    return {"saved": True, "file": str(path)}


def list_notes() -> list[str]:
    notes_dir = _notes_dir()
    if not notes_dir.exists():
        return []
    return sorted(path.name for path in notes_dir.glob("*.txt"))


def read_note(name: str) -> dict:
    notes_dir = _notes_dir()
    if not notes_dir.exists():
        return {"error": "No hay notas guardadas."}

    raw_name = Path(name).name
    candidates = [notes_dir / raw_name, notes_dir / _safe_note_name(name)]
    for path in candidates:
        if path.exists() and path.is_file():
            return {"file": path.name, "content": path.read_text(encoding="utf-8")}
    return {"error": f"No encontre la nota: {name}"}
