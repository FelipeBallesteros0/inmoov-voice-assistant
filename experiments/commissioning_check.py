#!/usr/bin/env python3
"""Verificacion de puesta en marcha articulacion por articulacion.

Reproduce el procedimiento descrito en el paper: cada articulacion se lleva a home,
se barre dentro de su rango permitido y se retorna a home. El script registra la
respuesta del firmware a cada comando y pregunta al operador por los criterios que
solo se pueden observar (bloqueo mecanico, vibracion excesiva, retorno estable).

A diferencia del trial de generacion de acciones, esta verificacion necesita el
Arduino Mega conectado y los servos energizados.

    python3 experiments/commissioning_check.py --group manos_der
    python3 experiments/commissioning_check.py --all

El JSONL resultante se reduce a la tabla del paper con:

    python3 experiments/commissioning_check.py --tables experiments/data/commissioning-*.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_assistant.robot import (  # noqa: E402
    ROBOT_JOINTS,
    RobotError,
    dry_run_enabled,
    set_robot_joints,
)

# Agrupacion usada en la tabla de puesta en marcha del paper.
JOINT_GROUPS: "OrderedDict[str, tuple[str, tuple[str, ...]]]" = OrderedDict(
    [
        ("hombros", ("Shoulders", ("lat_izq", "lat_der", "rotor_izq", "rotor_der"))),
        ("biceps", ("Biceps", ("bicep_izq", "bicep_der"))),
        ("cabeza_cuello", ("Head and neck", ("cabeza", "mandibula", "cuello", "cuello_izq", "cuello_der"))),
        ("mano_izq", ("Left hand", ("pulgar_izq", "indice_izq", "medio_izq", "anular_izq", "meni_izq"))),
        ("mano_der", ("Right hand", ("pulgar_der", "indice_der", "medio_der", "anular_der", "meni_der"))),
    ]
)

_JOINTS_BY_NAME = {joint.name: joint for joint in ROBOT_JOINTS}


def sweep_plan(joint_name: str) -> list[tuple[str, int]]:
    """home -> minimo -> maximo -> home, en grados."""
    joint = _JOINTS_BY_NAME[joint_name]
    return [
        ("home", joint.home_angle),
        ("min", joint.min_angle),
        ("max", joint.max_angle),
        ("home", joint.home_angle),
    ]


def group_of(joint_name: str) -> str:
    for key, (_, joints) in JOINT_GROUPS.items():
        if joint_name in joints:
            return key
    raise KeyError(joint_name)


def run_sweep(joint_name: str, settle_seconds: float) -> dict[str, Any]:
    """Ejecuta el barrido y devuelve la respuesta del firmware en cada paso."""
    steps = []
    for label, angle in sweep_plan(joint_name):
        try:
            result = set_robot_joints([{"joint": joint_name, "angle_degrees": angle}])
            steps.append(
                {
                    "target": label,
                    "angle_degrees": angle,
                    "command": result["command"],
                    "response": result["response"],
                    "ok": True,
                }
            )
        except RobotError as exc:
            steps.append({"target": label, "angle_degrees": angle, "ok": False, "error": str(exc)})
            break
        time.sleep(settle_seconds)
    return {
        "joint": joint_name,
        "group": group_of(joint_name),
        "responded": all(step["ok"] for step in steps),
        "range_reached": all(step["ok"] for step in steps),
        "steps": steps,
    }


def ask_operator(joint_name: str) -> dict[str, Any]:
    """Criterios de aceptacion que requieren observacion directa."""
    print(f"      Movimiento libre, sin bloqueo ni vibracion excesiva, retorno estable? [s/n/x]")
    answer = input("      > ").strip().lower()
    note = ""
    if answer not in {"s", "si", "y"}:
        note = input("      Observacion: ").strip()
    return {
        "accepted": answer in {"s", "si", "y"},
        "skipped": answer in {"x", "skip"},
        "note": note,
    }


def summarize(records: list[dict[str, Any]]) -> "OrderedDict[str, dict[str, Any]]":
    summary: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for key, (label, joints) in JOINT_GROUPS.items():
        group_records = [r for r in records if r["group"] == key and not r.get("skipped")]
        verified = [r for r in group_records if r["responded"] and r.get("accepted")]
        full_range = [r for r in verified if r.get("range_reached")]
        notes = [f"{r['joint']}: {r['note']}" for r in group_records if r.get("note")]
        summary[key] = {
            "label": label,
            "total": len(joints),
            "verified": len(verified),
            "range_reached": len(full_range),
            "notes": notes,
        }
    return summary


def build_table(summary: "OrderedDict[str, dict[str, Any]]") -> str:
    lines = [
        r"\begin{table}[!t]",
        r"  \centering",
        r"  \caption{Commissioning results by joint group. A joint is counted as verified when it "
        r"responded to the serial command, moved without visible mechanical blocking or excessive "
        r"vibration, and returned stably to its home position.}",
        r"  \label{tab:commissioning}",
        r"  \resizebox{\columnwidth}{!}{%",
        r"  \begin{tabular}{lcccc}",
        r"    \hline",
        r"    Joint group & Joints & Verified & Range reached & Result \\",
        r"    \hline",
    ]
    for stats in summary.values():
        total, verified, reached = stats["total"], stats["verified"], stats["range_reached"]
        result = "Operational" if verified == total else f"Partial ({total - verified} pending)"
        lines.append(
            f"    {stats['label']:<15} & {total} & {verified}/{total} & {reached}/{total} & {result} \\\\"
        )
    lines += [r"    \hline", r"  \end{tabular}%", r"  }", r"\end{table}", ""]
    return "\n".join(lines)


def selected_joints(args: argparse.Namespace) -> list[str]:
    if args.joint:
        return list(args.joint)
    if args.all:
        return [joint for _, joints in JOINT_GROUPS.values() for joint in joints]
    return list(JOINT_GROUPS[args.group][1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", choices=list(JOINT_GROUPS), help="Verifica un grupo articular")
    parser.add_argument("--joint", nargs="+", help="Verifica articulaciones concretas")
    parser.add_argument("--all", action="store_true", help="Verifica las 21 articulaciones")
    parser.add_argument("--settle", type=float, default=1.5, help="Espera entre pasos, en segundos")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--tables", nargs="+", type=Path, help="Solo genera la tabla desde JSONL existente")
    args = parser.parse_args(argv)

    if args.tables:
        records = []
        for path in args.tables:
            with path.open(encoding="utf-8") as handle:
                records.extend(json.loads(line) for line in handle if line.strip())
        print(build_table(summarize(records)))
        return 0

    if not (args.group or args.joint or args.all):
        parser.error("indica --group, --joint o --all")

    if dry_run_enabled():
        print("AVISO: ROBOT_DRY_RUN esta activo; no se movera ninguna articulacion real.\n")

    joints = selected_joints(args)
    output_path = args.output or (
        Path(__file__).resolve().parent / "data" / f"commissioning-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Puesta en marcha: {len(joints)} articulaciones -> {output_path}\n")
    with output_path.open("a", encoding="utf-8") as sink:
        for position, joint_name in enumerate(joints, start=1):
            joint = _JOINTS_BY_NAME[joint_name]
            print(
                f"[{position}/{len(joints)}] {joint_name} "
                f"(home {joint.home_angle}, rango {joint.min_angle}-{joint.max_angle})"
            )
            record = run_sweep(joint_name, args.settle)
            if not record["responded"]:
                failed = record["steps"][-1]
                print(f"      sin respuesta: {failed.get('error')}")
                record.update({"accepted": False, "skipped": False, "note": failed.get("error", "")})
            else:
                record.update(ask_operator(joint_name))
            record["timestamp"] = datetime.now().astimezone().isoformat()
            record["dry_run"] = dry_run_enabled()
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            sink.flush()
            print()

    print(build_table(summarize(_read_all(output_path))))
    return 0


def _read_all(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
