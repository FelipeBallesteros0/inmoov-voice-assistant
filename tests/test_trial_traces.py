import sys
import unittest
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import make_trial_traces as traces  # noqa: E402


def _call(joints, ok=True, error=None):
    arguments = {"joints": [{"joint": j, "angle_degrees": a} for j, a in joints]}
    if ok:
        result = {"ok": True, "joints_moved": [{"joint": j, "index": 0, "angle_degrees": a} for j, a in joints]}
    else:
        result = {"error": error or "Angulo fuera de rango"}
    return {"name": "set_robot_joints", "arguments": arguments, "result": result}


class ApplyAndTrajectoryTests(unittest.TestCase):
    def test_apply_keeps_omitted_joints(self):
        state = OrderedDict(traces.HOME)
        new_state = traces.apply(state, [{"joint": "cabeza", "angle_degrees": 120}])
        self.assertEqual(new_state["cabeza"], 120)
        self.assertEqual(new_state["lat_izq"], traces.HOME["lat_izq"])
        self.assertEqual(state["cabeza"], traces.HOME["cabeza"], "apply must not mutate its input")

    def test_trajectory_starts_from_home_and_accumulates(self):
        states = traces.trajectory(
            [
                [{"joint": "cabeza", "angle_degrees": 120}],
                [{"joint": "mandibula", "angle_degrees": 40}],
            ]
        )
        self.assertEqual(len(states), 2)
        self.assertEqual(states[0]["cabeza"], 120)
        self.assertEqual(states[1]["cabeza"], 120)
        self.assertEqual(states[1]["mandibula"], 40)

    def test_out_of_range_counts_every_violating_field(self):
        call = _call([("bicep_der", 55), ("rotor_der", 120), ("cabeza", 90)], ok=False)
        self.assertEqual(traces.out_of_range_fields(call), ["bicep_der", "rotor_der"])

    def test_reduce_turn_audits_first_proposal_and_displacement(self):
        turn = {
            "turn_id": 1,
            "command_label": "saluda",
            "repetition": 1,
            "transcript": "Saluda.",
            "reply_text": "Hola",
            "tool_calls": [
                _call([("bicep_der", 55)], ok=False),
                _call([("cabeza", 90), ("mandibula", 35)]),
            ],
            "latency_seconds": {"asr": 1.0, "llm": 9.0, "total": 8.0},
        }
        row = traces.reduce_turn(turn, local_exec=1.0)
        self.assertEqual((row["proposals"], row["accepted"], row["rejected"]), (2, 1, 1))
        self.assertFalse(row["first_proposal_accepted"])
        self.assertEqual(row["out_of_range_fields"], 1)
        # cabeza:90 equals home, so only the jaw is displaced although two joints were addressed.
        self.assertEqual(row["joints_addressed"], 2)
        self.assertEqual(row["joints_displaced_from_home"], 1)
        self.assertEqual(row["latency_seconds"]["turn"], 10.0)
        self.assertAlmostEqual(row["latency_seconds"]["eta_noncontrol"], 0.9)
        self.assertTrue(row["completed"])


if __name__ == "__main__":
    unittest.main()
