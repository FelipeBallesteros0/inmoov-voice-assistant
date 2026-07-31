#!/usr/bin/env python3
"""Convierte el JSONL del trial en los fragmentos LaTeX que usa el paper.

Genera dos tablas y un resumen de consola:

  - configuraciones articulares generadas por comando y repeticion (Seccion IV);
  - descomposicion de latencia con la fraccion remota eta_remote (Seccion IV);
  - estadisticas agregadas para el abstract (turnos, configuraciones distintas, medias).

Ningun numero del paper se escribe a mano: todos salen de este script.

    python3 experiments/make_paper_tables.py experiments/data/trial-*.jsonl --outdir experiments/tables
"""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str) -> str:
    return "".join(LATEX_SPECIALS.get(char, char) for char in str(text))


def load_turns(paths: Iterable[Path]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    turns.append(json.loads(line))
    return turns


def valid_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [turn for turn in turns if not turn.get("error") and turn.get("limit_validation_passed")]


def group_by_command(turns: list[dict[str, Any]]) -> "OrderedDict[str, list[dict[str, Any]]]":
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for turn in turns:
        grouped.setdefault(turn["command_label"], []).append(turn)
    for command in grouped:
        grouped[command].sort(key=lambda item: item.get("repetition", 0))
    return grouped


def configuration_steps(turn: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Consignas sucesivas del turno; los registros antiguos traen solo la primera."""
    steps = turn.get("configuration_steps")
    if steps:
        return steps
    first = turn.get("joints_generated")
    return [first] if first else []


def configuration_signature(turn: dict[str, Any]) -> tuple:
    """Firma de la realizacion completa, no solo de la primera consigna."""
    return tuple(
        tuple(sorted((item["joint"], item["angle_degrees"]) for item in step))
        for step in configuration_steps(turn)
    )


def activated_joints(turn: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for step in configuration_steps(turn):
        for item in step:
            if item["joint"] not in seen:
                seen.append(item["joint"])
    return seen


def format_configuration(turn: dict[str, Any]) -> str:
    steps = configuration_steps(turn)
    if not steps:
        return "--"
    pairs = ", ".join(f"{item['joint']}:{item['angle_degrees']}" for item in steps[0])
    return f"\\texttt{{{escape_latex(pairs)}}}"


def joint_group(joint_name: str) -> str:
    if joint_name in {"cabeza", "cuello", "cuello_izq", "cuello_der", "mandibula"}:
        return "head/neck"
    if joint_name in {"lat_izq", "lat_der", "rotor_izq", "rotor_der", "bicep_izq", "bicep_der"}:
        return "arms"
    return "hands"


def format_groups(turn: dict[str, Any]) -> str:
    groups = sorted({joint_group(name) for name in activated_joints(turn)})
    return ", ".join(groups)


# Costo del control local por consigna ejecutada: validacion de limites, envio serial
# y acuse del firmware, que ejecuta su rampa de movimiento. Medido en la Raspberry con
# el Mega conectado (n=20): 1149.1 ms con varianza nula. get_robot_status: 6 ms.
DEFAULT_LOCAL_EXECUTION_SECONDS = 1.149


def turn_seconds(turn: dict[str, Any]) -> float | None:
    """Duracion del turno: fin de la captura -> respuesta final del modelo."""
    latency = turn.get("latency_seconds") or {}
    asr, llm = latency.get("asr"), latency.get("llm")
    return None if None in (asr, llm) else asr + llm


def local_seconds(turn: dict[str, Any], local_exec: float) -> float:
    """Tiempo que la capa de control local consume dentro del turno."""
    return len(configuration_steps(turn)) * local_exec


def eta_remote(turn: dict[str, Any], local_exec: float = DEFAULT_LOCAL_EXECUTION_SECONDS) -> float | None:
    """Fraccion del turno atribuible a los servicios remotos (ASR + LLM).

    Se descuenta del turno el tiempo del control local, en vez de comparar contra el
    instante de la primera consigna: de otro modo el cociente puede superar 1, porque
    el modelo sigue generando consignas despues de la primera.
    """
    total = turn_seconds(turn)
    if not total:
        return None
    return (total - local_seconds(turn, local_exec)) / total


def joint_call_stats(turn: dict[str, Any]) -> tuple[int, int, int]:
    """Consignas propuestas, aceptadas y rechazadas por la validacion de limites."""
    calls = [c for c in turn.get("tool_calls", []) if c.get("name") == "set_robot_joints"]
    rejected = sum(1 for c in calls if isinstance(c.get("result"), dict) and c["result"].get("error"))
    return len(calls), len(calls) - rejected, rejected


def mean(values: list[float]) -> float | None:
    numeric = [value for value in values if value is not None]
    return sum(numeric) / len(numeric) if numeric else None


def fmt(value: float | None, digits: int = 2) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def build_generation_table(grouped: "OrderedDict[str, list[dict[str, Any]]]") -> str:
    lines = [
        r"\begin{table*}[!tb]",
        r"  \centering",
        r"  \caption{Joint configurations generated by the LLM for repeated semantic voice commands. "
        r"Each repetition starts from the home configuration with an empty dialogue history. A single "
        r"spoken command may yield several successive configurations, composing an articulated motion "
        r"rather than a static posture; the first one is shown, and $S$ reports the number of "
        r"configurations in the realization. The reduced sample illustrates---rather than statistically "
        r"quantifies---the variability of the generated actions.}",
        r"  \label{tab:software_generation}",
        r"  \resizebox{\textwidth}{!}{%",
        r"  \begin{tabular}{llccp{2.4cm}p{6.4cm}}",
        r"    \hline",
        r"    Command & Rep. & $S$ & Joints & Joint groups & First generated joint--angle configuration \\",
        r"    \hline",
    ]
    for command, turns in grouped.items():
        for position, turn in enumerate(turns):
            label = f"\\texttt{{{escape_latex(command)}}}" if position == 0 else ""
            steps = configuration_steps(turn)
            lines.append(
                f"    {label} & R{turn['repetition']} & {len(steps)} & {len(activated_joints(turn))} & "
                f"{format_groups(turn)} & {format_configuration(turn)} \\\\"
            )
        lines.append(r"    \hline")
    lines += [r"  \end{tabular}%", r"  }", r"\end{table*}", ""]
    return "\n".join(lines)


def build_latency_table(
    grouped: "OrderedDict[str, list[dict[str, Any]]]",
    local_exec: float = DEFAULT_LOCAL_EXECUTION_SECONDS,
) -> str:
    lines = [
        r"\begin{table}[!t]",
        r"  \centering",
        r"  \caption{Latency breakdown of the voice-to-action pipeline. $T_{\mathrm{turn}}$ spans from "
        r"the end of speech capture to the final model response; $T_{\mathrm{first}}$ is the time until "
        r"the control layer accepts the first executable configuration. $T_{\mathrm{LLM}}$ includes the "
        r"local execution of the generated commands, which is discounted in "
        r"$\eta_{\mathrm{remote}}$. Mechanical settling is excluded: the servomotors were unpowered.}",
        r"  \label{tab:latency}",
        r"  \resizebox{\columnwidth}{!}{%",
        r"  \begin{tabular}{lcccccc}",
        r"    \hline",
        r"    Command & $N$ & $T_{\mathrm{ASR}}$ (s) & $T_{\mathrm{LLM}}$ (s) & "
        r"$T_{\mathrm{first}}$ (s) & $T_{\mathrm{turn}}$ (s) & $\eta_{\mathrm{remote}}$ \\",
        r"    \hline",
    ]

    def row(label: str, turns: list[dict[str, Any]]) -> str:
        return (
            f"    {label} & {len(turns)} & "
            f"{fmt(mean([t['latency_seconds']['asr'] for t in turns]))} & "
            f"{fmt(mean([t['latency_seconds']['llm'] for t in turns]))} & "
            f"{fmt(mean([t['latency_seconds']['total'] for t in turns]))} & "
            f"{fmt(mean([turn_seconds(t) for t in turns]))} & "
            f"{fmt(mean([eta_remote(t, local_exec) for t in turns]))} \\\\"
        )

    all_turns: list[dict[str, Any]] = []
    for command, turns in grouped.items():
        all_turns.extend(turns)
        lines.append(row(f"\\texttt{{{escape_latex(command)}}}", turns))
    lines += [
        r"    \hline",
        row("Overall", all_turns),
        r"    \hline",
        r"  \end{tabular}%",
        r"  }",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)


def build_validation_table(grouped: "OrderedDict[str, list[dict[str, Any]]]") -> str:
    """Efecto de la capa de validacion de limites sobre lo que propone el modelo."""
    lines = [
        r"\begin{table}[!t]",
        r"  \centering",
        r"  \caption{Effect of the joint-limit validation layer. Proposed configurations are the "
        r"\texttt{set\_robot\_joints} calls issued by the LLM; rejected ones requested at least one "
        r"angle outside the safe range of Table~\ref{tab:joint_limits} and were never transmitted to "
        r"the microcontroller. After a rejection the error is returned to the model, which reformulates "
        r"the configuration.}",
        r"  \label{tab:validation}",
        r"  \resizebox{\columnwidth}{!}{%",
        r"  \begin{tabular}{lccccc}",
        r"    \hline",
        r"    Command & $N$ & Proposed & Accepted & Rejected & Realizations completed \\",
        r"    \hline",
    ]
    totals = [0, 0, 0, 0, 0]
    for command, turns in grouped.items():
        stats = [joint_call_stats(turn) for turn in turns]
        proposed = sum(s[0] for s in stats)
        accepted = sum(s[1] for s in stats)
        rejected = sum(s[2] for s in stats)
        done = sum(1 for turn in turns if turn.get("limit_validation_passed"))
        lines.append(
            f"    \\texttt{{{escape_latex(command)}}} & {len(turns)} & {proposed} & {accepted} & "
            f"{rejected} & {done}/{len(turns)} \\\\"
        )
        totals = [
            totals[0] + len(turns),
            totals[1] + proposed,
            totals[2] + accepted,
            totals[3] + rejected,
            totals[4] + done,
        ]
    lines += [
        r"    \hline",
        f"    Overall & {totals[0]} & {totals[1]} & {totals[2]} & {totals[3]} & {totals[4]}/{totals[0]} \\\\",
        r"    \hline",
        r"  \end{tabular}%",
        r"  }",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)


def build_summary(
    turns: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    local_exec: float = DEFAULT_LOCAL_EXECUTION_SECONDS,
) -> dict[str, Any]:
    grouped = group_by_command(accepted)
    per_command = {}
    for command, command_turns in grouped.items():
        signatures = {configuration_signature(turn) for turn in command_turns}
        stats = [joint_call_stats(turn) for turn in command_turns]
        per_command[command] = {
            "turns": len(command_turns),
            "distinct_configurations": len(signatures),
            "steps_per_realization": [len(configuration_steps(turn)) for turn in command_turns],
            "joints_activated": [len(activated_joints(turn)) for turn in command_turns],
            "proposed": sum(s[0] for s in stats),
            "accepted": sum(s[1] for s in stats),
            "rejected": sum(s[2] for s in stats),
        }
    attempted = [turn for turn in turns if not turn.get("error")]
    call_stats = [joint_call_stats(turn) for turn in attempted]
    proposed = sum(s[0] for s in call_stats)
    accepted_calls = sum(s[1] for s in call_stats)
    return {
        "turns_recorded": len(turns),
        "turns_with_accepted_configuration": len(accepted),
        # Turnos que convergieron a una configuracion ejecutable.
        "turn_convergence_rate": (len(accepted) / len(attempted)) if attempted else None,
        # Consignas que pasaron la validacion al primer intento.
        "call_validity_rate": (accepted_calls / proposed) if proposed else None,
        "joint_calls_proposed": proposed,
        "joint_calls_accepted": accepted_calls,
        "joint_calls_rejected": proposed - accepted_calls,
        "commands": per_command,
        "mean_latency_seconds": {
            "asr": mean([t["latency_seconds"]["asr"] for t in accepted]),
            "llm": mean([t["latency_seconds"]["llm"] for t in accepted]),
            "first_command": mean([t["latency_seconds"]["total"] for t in accepted]),
            "turn": mean([turn_seconds(t) for t in accepted]),
        },
        "local_execution_seconds_per_command": local_exec,
        "mean_eta_remote": mean([eta_remote(t, local_exec) for t in accepted]),
        "models": accepted[0]["models"] if accepted else None,
        "dry_run": accepted[0]["dry_run"] if accepted else None,
        "robot_tools_mode": accepted[0]["robot_tools_mode"] if accepted else None,
    }


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.0f}%"


def print_summary(summary: dict[str, Any]) -> None:
    print(f"Turnos registrados:            {summary['turns_recorded']}")
    print(f"Turnos que convergieron:       {summary['turns_with_accepted_configuration']} "
          f"({_pct(summary['turn_convergence_rate'])})")
    print(f"Consignas propuestas:          {summary['joint_calls_proposed']}")
    print(f"  aceptadas:                   {summary['joint_calls_accepted']} "
          f"({_pct(summary['call_validity_rate'])})")
    print(f"  rechazadas por limites:      {summary['joint_calls_rejected']}")
    print(f"Modelos:                       {summary['models']}")
    print(f"dry_run={summary['dry_run']}  tools_mode={summary['robot_tools_mode']}")
    print("\nPor comando:")
    for command, stats in summary["commands"].items():
        print(
            f"  {command:<28} turnos={stats['turns']}  "
            f"realizaciones distintas={stats['distinct_configurations']}  "
            f"consignas={stats['steps_per_realization']}  "
            f"articulaciones={stats['joints_activated']}  "
            f"propuestas/rechazadas={stats['proposed']}/{stats['rejected']}"
        )
    latency = summary["mean_latency_seconds"]
    print(
        f"\nLatencia media: T_ASR={fmt(latency['asr'])}s  T_LLM={fmt(latency['llm'])}s  "
        f"T_first={fmt(latency['first_command'])}s  T_turn={fmt(latency['turn'])}s  "
        f"eta_remote={fmt(summary['mean_eta_remote'])}"
    )
    print(f"Control local por consigna: {summary['local_execution_seconds_per_command']}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", nargs="+", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path(__file__).resolve().parent / "tables")
    parser.add_argument(
        "--local-exec-seconds",
        type=float,
        default=DEFAULT_LOCAL_EXECUTION_SECONDS,
        help="Costo del control local por consigna ejecutada (medido en la plataforma)",
    )
    args = parser.parse_args(argv)

    turns = load_turns(args.jsonl)
    accepted = valid_turns(turns)
    if not accepted:
        print("No hay turnos con consigna articular aceptada; nada que tabular.")
        return 1

    grouped = group_by_command(accepted)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "table_software_generation.tex").write_text(build_generation_table(grouped), encoding="utf-8")
    (args.outdir / "table_validation.tex").write_text(build_validation_table(grouped), encoding="utf-8")
    (args.outdir / "table_latency.tex").write_text(
        build_latency_table(grouped, args.local_exec_seconds), encoding="utf-8"
    )

    summary = build_summary(turns, accepted, args.local_exec_seconds)
    (args.outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print_summary(summary)
    print(f"\nFragmentos LaTeX en {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
