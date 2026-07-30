import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import commissioning_check as commissioning  # noqa: E402

from voice_assistant.robot import ROBOT_JOINTS  # noqa: E402


class JointGroupsTest(unittest.TestCase):
    def test_groups_cover_the_21_controlled_joints_exactly_once(self) -> None:
        grouped = [joint for _, joints in commissioning.JOINT_GROUPS.values() for joint in joints]

        self.assertEqual(len(grouped), 21)
        self.assertEqual(sorted(grouped), sorted(joint.name for joint in ROBOT_JOINTS))

    def test_group_of_matches_the_paper_table(self) -> None:
        self.assertEqual(commissioning.group_of("lat_der"), "hombros")
        self.assertEqual(commissioning.group_of("cabeza"), "cabeza_cuello")
        self.assertEqual(commissioning.group_of("meni_der"), "mano_der")


class SweepPlanTest(unittest.TestCase):
    def test_sweeps_home_min_max_home_within_joint_limits(self) -> None:
        plan = commissioning.sweep_plan("cabeza")

        self.assertEqual([label for label, _ in plan], ["home", "min", "max", "home"])
        self.assertEqual([angle for _, angle in plan], [90, 10, 170, 90])

    def test_every_joint_sweep_stays_within_its_declared_range(self) -> None:
        for joint in ROBOT_JOINTS:
            for _, angle in commissioning.sweep_plan(joint.name):
                self.assertGreaterEqual(angle, joint.min_angle, joint.name)
                self.assertLessEqual(angle, joint.max_angle, joint.name)


class RunSweepTest(unittest.TestCase):
    def test_records_each_step_in_dry_run(self) -> None:
        with mock.patch.dict(os.environ, {"ROBOT_DRY_RUN": "1"}):
            with mock.patch.object(commissioning.time, "sleep"):
                record = commissioning.run_sweep("mandibula", settle_seconds=0.0)

        self.assertTrue(record["responded"])
        self.assertEqual(record["group"], "cabeza_cuello")
        self.assertEqual([step["angle_degrees"] for step in record["steps"]], [10, 10, 70, 10])
        self.assertEqual(record["steps"][2]["command"], "ROBOT JOINTS 7:70")

    def test_stops_and_reports_when_the_firmware_does_not_respond(self) -> None:
        from voice_assistant.robot import RobotError

        with mock.patch.object(commissioning, "set_robot_joints", side_effect=RobotError("sin puerto")):
            with mock.patch.object(commissioning.time, "sleep"):
                record = commissioning.run_sweep("cabeza", settle_seconds=0.0)

        self.assertFalse(record["responded"])
        self.assertEqual(len(record["steps"]), 1)
        self.assertIn("sin puerto", record["steps"][0]["error"])


class SummaryTableTest(unittest.TestCase):
    def _record(self, joint, responded=True, accepted=True, note="", skipped=False):
        return {
            "joint": joint,
            "group": commissioning.group_of(joint),
            "responded": responded,
            "range_reached": responded,
            "accepted": accepted,
            "skipped": skipped,
            "note": note,
        }

    def test_counts_only_joints_that_responded_and_were_accepted(self) -> None:
        records = [
            self._record("pulgar_der"),
            self._record("indice_der"),
            self._record("medio_der"),
            self._record("anular_der"),
            self._record("meni_der", responded=False, accepted=False, note="no responde"),
        ]

        summary = commissioning.summarize(records)

        self.assertEqual(summary["mano_der"]["total"], 5)
        self.assertEqual(summary["mano_der"]["verified"], 4)
        self.assertEqual(summary["mano_der"]["notes"], ["meni_der: no responde"])
        self.assertEqual(summary["hombros"]["verified"], 0)

    def test_table_reports_partial_groups(self) -> None:
        records = [self._record(joint) for joint in ("lat_izq", "lat_der", "rotor_izq")]
        latex = commissioning.build_table(commissioning.summarize(records))

        self.assertIn(r"\label{tab:commissioning}", latex)
        self.assertIn("Shoulders", latex)
        self.assertIn("3/4", latex)
        self.assertIn("Partial (1 pending)", latex)

    def test_table_reports_operational_when_every_joint_passes(self) -> None:
        records = [self._record(joint) for joint in ("bicep_izq", "bicep_der")]
        latex = commissioning.build_table(commissioning.summarize(records))

        self.assertIn("Biceps", latex)
        self.assertIn("2/2", latex)
        self.assertIn("Operational", latex)

    def test_skipped_joints_do_not_count_as_verified(self) -> None:
        records = [self._record("bicep_izq"), self._record("bicep_der", skipped=True)]

        summary = commissioning.summarize(records)

        self.assertEqual(summary["biceps"]["verified"], 1)


if __name__ == "__main__":
    unittest.main()
