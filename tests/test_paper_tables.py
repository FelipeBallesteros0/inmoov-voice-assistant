import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import make_paper_tables as tables  # noqa: E402


def _steps(joints):
    return [{"joint": name, "index": index, "angle_degrees": angle} for name, index, angle in joints]


def _turn(turn_id, command, rep, joints, asr=1.0, llm=2.0, total=4.0, accepted=True, extra_steps=()):
    first = _steps(joints)
    return {
        "turn_id": turn_id,
        "command_label": command,
        "repetition": rep,
        "transcript": command,
        "joints_generated": first if accepted else None,
        "configuration_steps": ([first] + [_steps(s) for s in extra_steps]) if accepted else [],
        "serial_command": "ROBOT JOINTS 6:95" if accepted else None,
        "limit_validation_passed": accepted,
        "joint_call_count": 1 if accepted else 0,
        "tool_calls": (
            [{"name": "set_robot_joints", "arguments": {}, "result": {"ok": True}}] * (1 + len(extra_steps))
            + [{"name": "set_robot_joints", "arguments": {}, "result": {"error": "Angulo fuera de rango"}}]
            if accepted
            else [{"name": "set_robot_joints", "arguments": {}, "result": {"error": "Angulo fuera de rango"}}]
        ),
        "latency_seconds": {"asr": asr, "llm": llm, "total": total if accepted else None},
        "models": {"stt": "whisper-1", "chat": "gpt-5.5"},
        "dry_run": True,
        "robot_tools_mode": "joints_only",
    }


class PaperTablesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.turns = [
            _turn(1, "saluda", 1, [("cabeza", 6, 95), ("lat_der", 1, 110)]),
            _turn(2, "saluda", 2, [("bicep_der", 5, 120)], asr=1.4, llm=2.6, total=4.4),
            _turn(3, "saluda", 3, [("cabeza", 6, 95), ("lat_der", 1, 110)]),
            _turn(4, "festeja", 1, [("lat_izq", 0, 100), ("lat_der", 1, 100)], asr=1.2, llm=3.0, total=4.6),
        ]

    def test_escapes_underscores_in_joint_names(self) -> None:
        grouped = tables.group_by_command(self.turns)
        latex = tables.build_generation_table(grouped)

        self.assertIn(r"lat\_der:110", latex)
        self.assertNotIn("lat_der:110", latex)

    def test_generation_table_has_one_row_per_repetition(self) -> None:
        grouped = tables.group_by_command(self.turns)
        latex = tables.build_generation_table(grouped)

        self.assertEqual(latex.count(r"\\"), len(self.turns) + 1)  # filas + encabezado
        self.assertIn(r"\label{tab:software_generation}", latex)

    def test_multi_step_realization_reports_steps_and_union_of_joints(self) -> None:
        turn = _turn(
            9,
            "saluda",
            1,
            [("cabeza", 6, 90), ("lat_der", 1, 110)],
            extra_steps=[[("bicep_der", 5, 120)], [("cabeza", 6, 95), ("lat_der", 1, 100)]],
        )

        self.assertEqual(len(tables.configuration_steps(turn)), 3)
        self.assertEqual(tables.activated_joints(turn), ["cabeza", "lat_der", "bicep_der"])

        latex = tables.build_generation_table(tables.group_by_command([turn]))
        # S=3 consignas, 3 articulaciones distintas, y se muestra la primera configuracion.
        self.assertIn("& R1 & 3 & 3 &", latex)
        self.assertIn(r"cabeza:90, lat\_der:110", latex)

    def test_signature_covers_the_whole_sequence_not_only_the_first_step(self) -> None:
        base = [("cabeza", 6, 90)]
        a = _turn(1, "saluda", 1, base, extra_steps=[[("lat_der", 1, 110)]])
        b = _turn(2, "saluda", 2, base, extra_steps=[[("lat_izq", 0, 110)]])

        # Misma primera consigna, secuencias distintas -> deben contarse como distintas.
        self.assertNotEqual(tables.configuration_signature(a), tables.configuration_signature(b))
        summary = tables.build_summary([a, b], tables.valid_turns([a, b]))
        self.assertEqual(summary["commands"]["saluda"]["distinct_configurations"], 2)

    def test_reads_legacy_records_without_configuration_steps(self) -> None:
        legacy = _turn(1, "saluda", 1, [("cabeza", 6, 90)])
        legacy.pop("configuration_steps")

        self.assertEqual(len(tables.configuration_steps(legacy)), 1)
        self.assertEqual(tables.activated_joints(legacy), ["cabeza"])

    def test_counts_distinct_configurations_per_command(self) -> None:
        summary = tables.build_summary(self.turns, tables.valid_turns(self.turns))

        # saluda: R1 y R3 coinciden, R2 difiere -> 2 configuraciones distintas de 3 turnos.
        self.assertEqual(summary["commands"]["saluda"]["turns"], 3)
        self.assertEqual(summary["commands"]["saluda"]["distinct_configurations"], 2)
        self.assertEqual(summary["commands"]["festeja"]["distinct_configurations"], 1)

    def test_turn_duration_spans_asr_plus_llm(self) -> None:
        self.assertAlmostEqual(tables.turn_seconds(self.turns[0]), 3.0)

    def test_eta_remote_discounts_local_control_time(self) -> None:
        # Un turno de 1 consigna: (3.0 - 1.0) / 3.0
        self.assertAlmostEqual(tables.eta_remote(self.turns[0], local_exec=1.0), 2.0 / 3.0)

    def test_eta_remote_never_exceeds_one(self) -> None:
        # Regresion: comparar T_LLM completo contra el instante de la primera consigna
        # daba cocientes mayores que 1, que son imposibles por definicion.
        for turn in self.turns:
            eta = tables.eta_remote(turn)
            self.assertIsNotNone(eta)
            self.assertLessEqual(eta, 1.0)
            self.assertGreater(eta, 0.0)

    def test_eta_remote_drops_when_the_turn_has_more_steps(self) -> None:
        one = _turn(1, "saluda", 1, [("cabeza", 6, 90)])
        three = _turn(2, "saluda", 2, [("cabeza", 6, 90)], extra_steps=[[("lat_der", 1, 110)], [("cabeza", 6, 95)]])

        self.assertGreater(tables.eta_remote(one, 0.5), tables.eta_remote(three, 0.5))

    def test_counts_proposed_accepted_and_rejected_calls(self) -> None:
        turn = _turn(1, "saluda", 1, [("cabeza", 6, 90)], extra_steps=[[("lat_der", 1, 110)]])

        proposed, accepted, rejected = tables.joint_call_stats(turn)

        self.assertEqual((proposed, accepted, rejected), (3, 2, 1))

    def test_validation_table_reports_rejections(self) -> None:
        latex = tables.build_validation_table(tables.group_by_command(self.turns))

        self.assertIn(r"\label{tab:validation}", latex)
        self.assertIn("Rejected", latex)
        self.assertIn("3/3", latex)  # las 3 realizaciones de saluda completaron

    def test_latency_table_reports_per_command_and_overall(self) -> None:
        grouped = tables.group_by_command(self.turns)
        latex = tables.build_latency_table(grouped)

        self.assertIn(r"\eta_{\mathrm{remote}}", latex)
        self.assertIn("Overall & 4 &", latex)
        self.assertIn(r"\label{tab:latency}", latex)

    def test_turns_without_accepted_configuration_are_excluded(self) -> None:
        turns = self.turns + [_turn(5, "festeja", 2, [], accepted=False)]
        accepted = tables.valid_turns(turns)

        self.assertEqual(len(accepted), 4)
        summary = tables.build_summary(turns, accepted)
        self.assertEqual(summary["turns_recorded"], 5)
        self.assertEqual(summary["turns_with_accepted_configuration"], 4)
        # 4 de 5 turnos convergieron a una configuracion ejecutable...
        self.assertAlmostEqual(summary["turn_convergence_rate"], 0.8)
        # ...pero eso no es lo mismo que la validez de cada consigna propuesta:
        # 4 turnos aceptados aportan 2 consignas cada uno (1 aceptada, 1 rechazada)
        # y el turno fallido aporta 1 rechazada.
        self.assertEqual(summary["joint_calls_proposed"], 9)
        self.assertEqual(summary["joint_calls_accepted"], 4)
        self.assertEqual(summary["joint_calls_rejected"], 5)
        self.assertAlmostEqual(summary["call_validity_rate"], 4 / 9)

    def test_compact_table_drops_long_configuration_strings(self) -> None:
        grouped = tables.group_by_command(self.turns)
        compact = tables.build_generation_table_compact(grouped)

        self.assertIn(r"\label{tab:software_generation}", compact)
        self.assertIn(r"\begin{table}", compact)
        self.assertNotIn(r"\begin{table*}", compact)   # una sola columna
        self.assertNotIn("cabeza:95", compact)          # sin cadenas de pares
        self.assertLess(len(compact), len(tables.build_generation_table(grouped)))

    def test_examples_snippet_returns_configurations_for_the_text(self) -> None:
        snippet = tables.build_examples_snippet(tables.group_by_command(self.turns), "saluda")

        self.assertIn(r"cabeza:95, lat\_der:110", snippet)
        self.assertEqual(snippet.count(r"\texttt{"), 2)

    def test_main_writes_fragments_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl = Path(tmpdir) / "trial.jsonl"
            jsonl.write_text("\n".join(json.dumps(turn) for turn in self.turns), encoding="utf-8")
            outdir = Path(tmpdir) / "tables"

            exit_code = tables.main([str(jsonl), "--outdir", str(outdir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((outdir / "table_software_generation.tex").exists())
            self.assertTrue((outdir / "table_latency.tex").exists())
            summary = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["turns_with_accepted_configuration"], 4)

    def test_main_reports_when_there_is_nothing_to_tabulate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl = Path(tmpdir) / "empty.jsonl"
            jsonl.write_text(json.dumps(_turn(1, "saluda", 1, [], accepted=False)), encoding="utf-8")

            self.assertEqual(tables.main([str(jsonl), "--outdir", str(Path(tmpdir) / "out")]), 1)


if __name__ == "__main__":
    unittest.main()
