#!/usr/bin/env python3
"""Trazas por turno del trial de generacion de acciones (revision camara-lista).

Reduce el JSONL del trial a un registro por turno con todo lo que pidieron los
revisores: transcripcion, consignas propuestas / aceptadas / rechazadas, aceptacion
de la primera propuesta, campos fuera de rango por articulacion, consignas aceptadas
en orden, trayectoria nominal de 21 articulaciones inicializada en home, estado final,
y latencias con fronteras de reloj explicitas.

La trayectoria sigue la definicion del revisor:

    q_{i,0} = q_home
    q_{i,k} = apply(q_{i,k-1}, c_{i,k})      (las articulaciones omitidas conservan su valor)
    T_i     = (q_{i,1}, ..., q_{i,K_i})

Es una trayectoria NOMINAL: se calcula a partir de las consignas aceptadas y del vector
home del firmware. En el lote de software los servos estaban sin alimentacion y la
memoria de posicion del firmware no se re-inicializo entre turnos, de modo que la
pose fisica no fue verificada.

    python3 experiments/make_trial_traces.py experiments/data/trial-*.jsonl --outdir experiments/tables

Genera `per_trial.json` (legible por maquina) y `per_trial.tex` (tabla del paper).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Iterable

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_assistant.robot import ROBOT_JOINTS  # noqa: E402

from make_paper_tables import DEFAULT_LOCAL_EXECUTION_SECONDS, escape_latex, load_turns  # noqa: E402

JOINT_ORDER = tuple(joint.name for joint in ROBOT_JOINTS)
HOME = OrderedDict((joint.name, joint.home_angle) for joint in ROBOT_JOINTS)
LIMITS = {joint.name: (joint.min_angle, joint.max_angle) for joint in ROBOT_JOINTS}

COMMAND_GLOSS = {
    "saluda": "greet",
    "festeja": "celebrate",
    "haz una pose de robot": "strike a robot pose",
    "haz un gesto de bienvenida": "make a welcome gesture",
}


def apply(state: "OrderedDict[str, int]", command: list[dict[str, Any]]) -> "OrderedDict[str, int]":
    """Aplica una consigna parcial: las articulaciones omitidas conservan su valor."""
    new_state = OrderedDict(state)
    for item in command:
        new_state[item["joint"]] = int(item["angle_degrees"])
    return new_state


def trajectory(accepted_commands: list[list[dict[str, Any]]]) -> list["OrderedDict[str, int]"]:
    state = OrderedDict(HOME)
    states = []
    for command in accepted_commands:
        state = apply(state, command)
        states.append(state)
    return states


def joint_calls(turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for call in turn.get("tool_calls", []) if call.get("name") == "set_robot_joints"]


def is_accepted(call: dict[str, Any]) -> bool:
    return isinstance(call.get("result"), dict) and bool(call["result"].get("ok"))


def is_rejected(call: dict[str, Any]) -> bool:
    return isinstance(call.get("result"), dict) and bool(call["result"].get("error"))


def out_of_range_fields(call: dict[str, Any]) -> list[str]:
    """Articulaciones de la llamada cuyo angulo cae fuera del rango permitido.

    Una llamada rechazada puede traer varias violaciones; el validador solo reporta la
    primera, asi que se recorren todos los pares para contarlas.
    """
    joints = (call.get("arguments") or {}).get("joints") or []
    fields = []
    for item in joints:
        name = item.get("joint")
        if name not in LIMITS:
            continue
        low, high = LIMITS[name]
        if not low <= int(item["angle_degrees"]) <= high:
            fields.append(name)
    return fields


def audit_call(call: dict[str, Any]) -> dict[str, Any]:
    joints = (call.get("arguments") or {}).get("joints") or []
    names = [item.get("joint") for item in joints]
    return {
        "accepted": is_accepted(call),
        "invalid_names": [name for name in names if name not in LIMITS],
        "duplicate_names": sorted({name for name in names if names.count(name) > 1}),
        "out_of_range_fields": out_of_range_fields(call),
        "error": call["result"].get("error") if is_rejected(call) else None,
    }


def reduce_turn(turn: dict[str, Any], local_exec: float) -> dict[str, Any]:
    calls = joint_calls(turn)
    audits = [audit_call(call) for call in calls]
    accepted_commands = [call["result"]["joints_moved"] for call in calls if is_accepted(call)]
    states = trajectory(accepted_commands)
    final_state = states[-1] if states else OrderedDict(HOME)

    addressed: list[str] = []
    for command in accepted_commands:
        for item in command:
            if item["joint"] not in addressed:
                addressed.append(item["joint"])
    displaced = [name for name in JOINT_ORDER if final_state[name] != HOME[name]]

    oor_by_joint = Counter()
    for audit in audits:
        oor_by_joint.update(audit["out_of_range_fields"])

    latency = turn.get("latency_seconds") or {}
    asr, llm, first = latency.get("asr"), latency.get("llm"), latency.get("total")
    turn_seconds = None if None in (asr, llm) else round(asr + llm, 3)
    eta = None
    if turn_seconds:
        eta = round((turn_seconds - len(accepted_commands) * local_exec) / turn_seconds, 3)

    return {
        "turn_id": turn["turn_id"],
        "command": turn["command_label"],
        "repetition": turn["repetition"],
        "timestamp": turn.get("timestamp"),
        "transcript": turn.get("transcript"),
        "final_response": turn.get("reply_text"),
        "completed": bool(turn.get("reply_text")) and not turn.get("error"),
        "proposals": len(calls),
        "accepted": len(accepted_commands),
        "rejected": sum(1 for audit in audits if not audit["accepted"]),
        "first_proposal_accepted": bool(audits) and audits[0]["accepted"],
        "retries_after_rejection": sum(1 for audit in audits if not audit["accepted"]),
        "get_robot_status_calls": sum(1 for c in turn.get("tool_calls", []) if c.get("name") == "get_robot_status"),
        "invalid_name_calls": sum(1 for audit in audits if audit["invalid_names"]),
        "duplicate_name_calls": sum(1 for audit in audits if audit["duplicate_names"]),
        "out_of_range_calls": sum(1 for audit in audits if audit["out_of_range_fields"]),
        "out_of_range_fields": sum(oor_by_joint.values()),
        "out_of_range_fields_by_joint": dict(oor_by_joint),
        "rejected_calls_with_multiple_violations": sum(
            1 for audit in audits if len(audit["out_of_range_fields"]) > 1
        ),
        "proposal_audit": audits,
        "accepted_commands": [
            {"joints": [{"joint": item["joint"], "angle_degrees": item["angle_degrees"]} for item in command]}
            for command in accepted_commands
        ],
        "serial_commands": turn.get("serial_commands"),
        "trajectory": [[state[name] for name in JOINT_ORDER] for state in states],
        "final_state": [final_state[name] for name in JOINT_ORDER],
        "joints_addressed": len(addressed),
        "joints_displaced_from_home": len(displaced),
        "latency_seconds": {
            "asr": asr,
            "llm": llm,
            "first_accepted_command": first,
            "turn": turn_seconds,
            "eta_noncontrol": eta,
        },
        "models": turn.get("models"),
        "dry_run": turn.get("dry_run"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def center_range(key: str) -> dict[str, float]:
        values = [row["latency_seconds"][key] for row in rows if row["latency_seconds"][key] is not None]
        return {
            "mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    by_command: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for row in rows:
        by_command.setdefault(row["command"], []).append(row)

    def distinct(items: Iterable[Any]) -> int:
        return len({json.dumps(item) for item in items})

    oor = Counter()
    for row in rows:
        oor.update(row["out_of_range_fields_by_joint"])

    return {
        "turns": len(rows),
        "completed": sum(1 for row in rows if row["completed"]),
        "proposals": sum(row["proposals"] for row in rows),
        "accepted": sum(row["accepted"] for row in rows),
        "rejected": sum(row["rejected"] for row in rows),
        "first_proposal_accepted": sum(1 for row in rows if row["first_proposal_accepted"]),
        "invalid_name_calls": sum(row["invalid_name_calls"] for row in rows),
        "duplicate_name_calls": sum(row["duplicate_name_calls"] for row in rows),
        "out_of_range_fields": sum(oor.values()),
        "out_of_range_fields_by_joint": dict(oor.most_common()),
        "rejected_calls_with_multiple_violations": sum(
            row["rejected_calls_with_multiple_violations"] for row in rows
        ),
        "get_robot_status_calls": sum(row["get_robot_status_calls"] for row in rows),
        "distinct_final_states_overall": distinct(row["final_state"] for row in rows),
        "distinct_trajectories_overall": distinct(row["trajectory"] for row in rows),
        "per_command": {
            command: {
                "turns": len(group),
                "distinct_final_states": distinct(row["final_state"] for row in group),
                "distinct_trajectories": distinct(row["trajectory"] for row in group),
                "proposals": sum(row["proposals"] for row in group),
                "rejected": sum(row["rejected"] for row in group),
            }
            for command, group in by_command.items()
        },
        "latency_seconds": {
            key: center_range(key) for key in ("asr", "llm", "first_accepted_command", "turn", "eta_noncontrol")
        },
        "local_execution_seconds_per_command": DEFAULT_LOCAL_EXECUTION_SECONDS,
        "accepted_commands_per_turn": [row["accepted"] for row in rows],
    }


def fmt(value: Any, digits: int = 1) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def build_table(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        r"\begin{table*}[!t]",
        r"  \centering",
        r"  \caption{Per-trial record of the software-level batch (one trial per row; servomotors unpowered). "
        r"\emph{Prop.}, \emph{Rej.}, and \emph{Acc.} count \setjoints{} proposals, rejections, and accepted commands; "
        r"\emph{OOR} is the number of out-of-range joint fields in the rejected proposals of the trial (a rejected call "
        r"may contain several); \emph{Addr.} and \emph{Disp.} are the joints addressed by accepted commands and the "
        r"joints whose final nominal value differs from home. Latencies in seconds as defined in Section~\ref{sec:latency}; "
        r"$\hat\eta$ is the non-control remainder of (\ref{eq:noncontrol}). All twelve trials ended with a final "
        r"model response; none reached the tool-round limit and no API failure occurred.}",
        r"  \label{tab:per_trial}",
        r"  \setlength{\tabcolsep}{4pt}",
        r"  \scriptsize",
        r"  \begin{tabular}{@{}cl cccccc ccccc@{}}",
        r"    \hline",
        r"    \# & Transcript & Prop. & Rej. & Acc. & OOR & Addr. & Disp. & "
        r"$T_{\mathrm{ASR}}$ & $T_{\mathrm{LLM}}$ & $T_{\mathrm{first}}$ & $T_{\mathrm{turn}}$ & $\hat\eta$ \\",
    ]
    previous = None
    for row in rows:
        if row["command"] != previous:
            gloss = COMMAND_GLOSS.get(row["command"])
            label = f"\\texttt{{{escape_latex(row['command'])}}}"
            if gloss:
                label += f" (\\emph{{{gloss}}})"
            lines.append(r"    \hline")
            lines.append(f"    \\multicolumn{{13}}{{@{{}}l}}{{Instruction: {label}}} \\\\")
            previous = row["command"]
        lat = row["latency_seconds"]
        lines.append(
            f"    {row['turn_id']} & \\texttt{{{escape_latex(row['transcript'])}}} & {row['proposals']} & "
            f"{row['rejected']} & {row['accepted']} & {row['out_of_range_fields']} & {row['joints_addressed']} & "
            f"{row['joints_displaced_from_home']} & {fmt(lat['asr'])} & {fmt(lat['llm'])} & "
            f"{fmt(lat['first_accepted_command'])} & {fmt(lat['turn'])} & {fmt(lat['eta_noncontrol'], 2)} \\\\"
        )
    s = summary
    L = s["latency_seconds"]

    def med(key: str) -> str:
        return f"{L[key]['median']:.1f}" if key != "eta_noncontrol" else f"{L[key]['median']:.2f}"

    def rng(key: str) -> str:
        d = 2 if key == "eta_noncontrol" else 1
        return f"{L[key]['min']:.{d}f}--{L[key]['max']:.{d}f}"

    keys = ("asr", "llm", "first_accepted_command", "turn", "eta_noncontrol")
    lines += [
        r"    \hline",
        f"    \\multicolumn{{2}}{{@{{}}l}}{{Total}} & {s['proposals']} & {s['rejected']} & {s['accepted']} & "
        f"{s['out_of_range_fields']} & -- & -- & \\multicolumn{{5}}{{c@{{}}}}{{}} \\\\",
        f"    \\multicolumn{{2}}{{@{{}}l}}{{Median}} & \\multicolumn{{6}}{{c}}{{}} & "
        + " & ".join(med(k) for k in keys) + " \\\\",
        f"    \\multicolumn{{2}}{{@{{}}l}}{{Range}} & \\multicolumn{{6}}{{c}}{{}} & "
        + " & ".join(rng(k) for k in keys) + " \\\\",
        r"    \hline",
        r"  \end{tabular}",
        r"\end{table*}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", nargs="+", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path(__file__).resolve().parent / "tables")
    parser.add_argument("--local-exec-seconds", type=float, default=DEFAULT_LOCAL_EXECUTION_SECONDS)
    args = parser.parse_args(argv)

    turns = [turn for turn in load_turns(args.jsonl) if not turn.get("error")]
    rows = [reduce_turn(turn, args.local_exec_seconds) for turn in turns]
    summary = summarize(rows)

    args.outdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_files": [str(path) for path in args.jsonl],
        "home_vector": dict(HOME),
        "joint_order": list(JOINT_ORDER),
        "joint_limits": {name: {"min": low, "max": high} for name, (low, high) in LIMITS.items()},
        "trajectory_definition": "q_0 = home; q_k = apply(q_{k-1}, c_k) with omitted joints unchanged; nominal, not measured",
        "summary": summary,
        "trials": rows,
    }
    (args.outdir / "per_trial.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.outdir / "per_trial.tex").write_text(build_table(rows, summary), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nTrazas en {args.outdir / 'per_trial.json'} y tabla en {args.outdir / 'per_trial.tex'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
