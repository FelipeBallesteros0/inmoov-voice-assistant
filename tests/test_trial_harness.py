import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import action_generation_trial as trial  # noqa: E402


class TurnPlanTest(unittest.TestCase):
    def test_groups_repetitions_by_command(self) -> None:
        plan = trial.build_turn_plan(["saluda", "festeja"], 3)

        self.assertEqual(len(plan), 6)
        self.assertEqual(plan[0], (1, "saluda", 1))
        self.assertEqual(plan[2], (3, "saluda", 3))
        self.assertEqual(plan[3], (4, "festeja", 1))
        self.assertEqual([turn_id for turn_id, _, _ in plan], [1, 2, 3, 4, 5, 6])


class TrialSystemPromptTest(unittest.TestCase):
    def test_sets_trial_prompt_when_operator_did_not_define_one(self) -> None:
        env: dict[str, str] = {}

        prompt = trial.apply_trial_system_prompt(env)

        self.assertEqual(prompt, trial.TRIAL_SYSTEM_PROMPT)
        self.assertEqual(env["OPENAI_SYSTEM_PROMPT"], trial.TRIAL_SYSTEM_PROMPT)

    def test_respects_an_explicit_system_prompt(self) -> None:
        env = {"OPENAI_SYSTEM_PROMPT": "prompt propio"}

        self.assertEqual(trial.apply_trial_system_prompt(env), "prompt propio")

    def test_trial_prompt_does_not_prescribe_joints_per_command(self) -> None:
        prompt = trial.TRIAL_SYSTEM_PROMPT.lower()

        self.assertIn("set_robot_joints", prompt)
        self.assertNotIn("run_robot_routine", prompt)
        for command in ("saluda", "festeja", "pose", "bienvenida"):
            self.assertNotIn(command, prompt)


class TurnRecorderTest(unittest.TestCase):
    def test_records_accepted_joint_configuration(self) -> None:
        recorder = trial.TurnRecorder()
        arguments = json.dumps(
            {"joints": [{"joint": "cabeza", "angle_degrees": 95}, {"joint": "lat_der", "angle_degrees": 110}]}
        )

        with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1"}):
            raw = recorder("set_robot_joints", arguments)

        payload = json.loads(raw)
        self.assertEqual(payload["command"], "ROBOT JOINTS 6:95 1:110")
        self.assertEqual(len(recorder.joint_calls), 1)
        accepted = recorder.first_accepted
        self.assertIsNotNone(accepted)
        self.assertIsNotNone(accepted.accepted_at)
        self.assertEqual(
            trial.summarize_joints(accepted),
            "cabeza:95, lat_der:110",
        )

    def test_rejected_configuration_is_recorded_but_not_accepted(self) -> None:
        recorder = trial.TurnRecorder()
        arguments = json.dumps({"joints": [{"joint": "cabeza", "angle_degrees": 200}]})

        with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1"}):
            raw = recorder("set_robot_joints", arguments)

        self.assertIn("error", json.loads(raw))
        self.assertEqual(len(recorder.joint_calls), 1)
        self.assertIsNone(recorder.first_accepted)
        self.assertEqual(trial.summarize_joints(recorder.first_accepted), "(sin consigna articular)")

    def test_keeps_every_accepted_configuration_of_the_turn(self) -> None:
        recorder = trial.TurnRecorder()
        with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1"}):
            recorder("set_robot_joints", json.dumps({"joints": [{"joint": "cabeza", "angle_degrees": 90}]}))
            recorder("set_robot_joints", json.dumps({"joints": [{"joint": "lat_der", "angle_degrees": 110}]}))
            recorder("set_robot_joints", json.dumps({"joints": [{"joint": "cabeza", "angle_degrees": 200}]}))

        self.assertEqual(len(recorder.joint_calls), 3)
        self.assertEqual(len(recorder.accepted_calls), 2)  # la tercera viola el limite
        self.assertIs(recorder.first_accepted, recorder.accepted_calls[0])

    def test_non_robot_tool_calls_are_kept_in_order(self) -> None:
        recorder = trial.TurnRecorder()

        with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1"}):
            recorder("get_robot_status", {})
            recorder("set_robot_joints", json.dumps({"joints": [{"joint": "mandibula", "angle_degrees": 40}]}))

        self.assertEqual([call.name for call in recorder.calls], ["get_robot_status", "set_robot_joints"])
        self.assertEqual(len(recorder.joint_calls), 1)


class RunTurnTest(unittest.TestCase):
    def _context(self, tmpdir: str, recorder: trial.TurnRecorder):
        config = SimpleNamespace(
            temp_audio_dir=Path(tmpdir),
            stt_model="whisper-1",
            chat_model="gpt-5.5",
        )
        audio = mock.Mock()
        audio.record_until_silence.return_value = Path(tmpdir) / "turn.wav"

        def fake_reply(user_text, history):
            self.assertEqual(list(history), [])
            recorder(
                "set_robot_joints",
                json.dumps({"joints": [{"joint": "cabeza", "angle_degrees": 95}]}),
            )
            recorder(
                "set_robot_joints",
                json.dumps({"joints": [{"joint": "lat_der", "angle_degrees": 110}]}),
            )
            return "Listo, te saludo."

        openai = mock.Mock()
        openai.transcribe.return_value = "saluda"
        openai.reply.side_effect = fake_reply
        return SimpleNamespace(config=config, audio=audio, openai=openai)

    def test_records_transcript_joints_and_latencies(self) -> None:
        recorder = trial.TurnRecorder()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(tmpdir, recorder)
            with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1", "ROBOT_TOOLS_MODE": "joints_only"}):
                turn = trial.run_turn(context, recorder, turn_id=1, command="saluda", rep=1, use_tts=False)

        self.assertEqual(turn["transcript"], "saluda")
        self.assertEqual(turn["command_label"], "saluda")
        self.assertEqual(turn["serial_command"], "ROBOT JOINTS 6:95")
        self.assertEqual(turn["joints_generated"], [{"joint": "cabeza", "index": 6, "angle_degrees": 95}])
        self.assertTrue(turn["limit_validation_passed"])
        self.assertTrue(turn["dry_run"])
        self.assertEqual(turn["robot_tools_mode"], "joints_only")
        self.assertEqual(turn["models"], {"stt": "whisper-1", "chat": "gpt-5.5"})
        for key in ("asr", "llm", "total"):
            self.assertIsNotNone(turn["latency_seconds"][key])
            self.assertGreaterEqual(turn["latency_seconds"][key], 0.0)
        self.assertEqual(len(turn["tool_calls"]), 2)
        # La secuencia completa queda registrada, no solo la primera consigna.
        self.assertEqual(turn["accepted_call_count"], 2)
        self.assertEqual(len(turn["configuration_steps"]), 2)
        self.assertEqual(turn["serial_commands"], ["ROBOT JOINTS 6:95", "ROBOT JOINTS 1:110"])

    def test_turn_without_speech_is_reported_as_error(self) -> None:
        recorder = trial.TurnRecorder()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(tmpdir, recorder)
            context.audio.record_until_silence.return_value = None
            turn = trial.run_turn(context, recorder, turn_id=2, command="festeja", rep=1, use_tts=False)

        self.assertEqual(turn["error"], "sin voz detectada")
        context.openai.transcribe.assert_not_called()

    def test_turn_without_tool_call_reports_missing_configuration(self) -> None:
        recorder = trial.TurnRecorder()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(tmpdir, recorder)
            context.openai.reply.side_effect = None
            context.openai.reply.return_value = "Hola, como estas."
            turn = trial.run_turn(context, recorder, turn_id=3, command="saluda", rep=2, use_tts=False)

        self.assertFalse(turn["limit_validation_passed"])
        self.assertIsNone(turn["joints_generated"])
        self.assertIsNone(turn["latency_seconds"]["total"])
        self.assertEqual(turn["joint_call_count"], 0)


if __name__ == "__main__":
    unittest.main()
