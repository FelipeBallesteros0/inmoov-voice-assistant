import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from voice_assistant.alarms import LOCAL_TZ
from voice_assistant.robot import RobotCommandResult
from voice_assistant.tools import call_tool, safe_calculate


class ToolsTest(unittest.TestCase):
    def test_calculates_simple_expression(self) -> None:
        self.assertEqual(safe_calculate("(25 * 17) / 2"), 212.5)

    def test_rejects_non_arithmetic_expression(self) -> None:
        with self.assertRaises(ValueError):
            safe_calculate("__import__('os').system('date')")

    def test_saves_lists_and_reads_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"RVA_NOTES_DIR": tmpdir}):
                saved = json.loads(
                    call_tool(
                        "save_note",
                        {"title": "Prueba", "content": "Comprar pilas"},
                    )
                )
                listed = json.loads(call_tool("list_notes", {}))
                read = json.loads(call_tool("read_note", {"name": "Prueba"}))

        self.assertTrue(saved["saved"])
        self.assertEqual(listed["notes"], ["prueba.txt"])
        self.assertIn("Comprar pilas", read["content"])

    def test_schedules_and_lists_alarm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alarms_path = os.path.join(tmpdir, "alarms.json")
            with mock.patch.dict(os.environ, {"RVA_ALARMS_PATH": alarms_path}):
                due_at = datetime.now(LOCAL_TZ) + timedelta(minutes=5)
                scheduled = json.loads(
                    call_tool(
                        "schedule_alarm",
                        {"due_at": due_at.isoformat(), "message": "comprar pan"},
                    )
                )
                listed = json.loads(call_tool("list_alarms", {"include_triggered": False}))

        self.assertEqual(scheduled["message"], "comprar pan")
        self.assertEqual(listed["alarms"][0]["id"], scheduled["id"])

    def test_move_servo_tool_returns_move_result(self) -> None:
        fake_result = mock.Mock(
            moved=True,
            angle=90,
            port="/dev/test-servo",
            response="OK 90",
        )
        with mock.patch("voice_assistant.tools.move_servo", return_value=fake_result):
            result = json.loads(call_tool("move_servo", {"angle_degrees": 90}))

        self.assertEqual(
            result,
            {
                "moved": True,
                "angle": 90,
                "port": "/dev/test-servo",
                "response": "OK 90",
            },
        )

    def test_tool_schemas_include_servo_and_general_robot_tools(self) -> None:
        from voice_assistant.tools import tool_schemas

        schemas = tool_schemas()
        names = {tool["name"] for tool in schemas}
        self.assertIn("move_servo", names)
        self.assertIn("run_servo_sequence", names)
        self.assertIn("get_robot_status", names)
        self.assertIn("set_robot_joints", names)
        self.assertNotIn("run_robot_routine", names)
        self.assertNotIn("move_robot_finger", names)
        self.assertNotIn("run_robot_sequence", names)

        set_joints_schema = next(tool for tool in schemas if tool["name"] == "set_robot_joints")
        joints_schema = set_joints_schema["parameters"]["properties"]["joints"]
        self.assertEqual(joints_schema["maxItems"], 21)
        self.assertIn("cabeza", joints_schema["items"]["properties"]["joint"]["enum"])

    def test_run_servo_sequence_tool_returns_sequence_result(self) -> None:
        fake_result = {
            "completed": True,
            "repeat": 2,
            "port": "/dev/test-servo",
            "steps_executed": 4,
            "results": [],
        }
        with mock.patch("voice_assistant.tools.run_servo_sequence", return_value=fake_result):
            result = json.loads(
                call_tool(
                    "run_servo_sequence",
                    {
                        "repeat": 2,
                        "steps": [
                            {"angle_degrees": 90, "delay_after_seconds": 1},
                            {"angle_degrees": 180, "delay_after_seconds": 0},
                        ],
                    },
                )
            )

        self.assertEqual(result, fake_result)

    def test_get_robot_status_tool_returns_robot_result(self) -> None:
        fake_result = RobotCommandResult(
            ok=True,
            command="ROBOT STATUS",
            port="/dev/test-robot",
            response="OK STATUS idle",
        )
        with mock.patch("voice_assistant.tools.get_robot_status", return_value=fake_result):
            result = json.loads(call_tool("get_robot_status", {}))

        self.assertEqual(
            result,
            {
                "ok": True,
                "command": "ROBOT STATUS",
                "port": "/dev/test-robot",
                "response": "OK STATUS idle",
            },
        )

    def test_set_robot_joints_tool_returns_joint_result(self) -> None:
        fake_result = {
            "ok": True,
            "command": "ROBOT JOINTS 6:90 17:40",
            "port": "/dev/test-robot",
            "response": "OK JOINTS 2",
            "joints_moved": [
                {"joint": "cabeza", "index": 6, "angle_degrees": 90},
                {"joint": "indice_der", "index": 17, "angle_degrees": 40},
            ],
        }
        joints = [
            {"joint": "cabeza", "angle_degrees": 90},
            {"joint": "indice_der", "angle_degrees": 40},
        ]
        with mock.patch("voice_assistant.tools.set_robot_joints", return_value=fake_result):
            result = json.loads(call_tool("set_robot_joints", {"joints": joints}))

        self.assertEqual(result, fake_result)

    def test_old_robot_action_tools_are_not_dispatchable(self) -> None:
        result = json.loads(
            call_tool(
                "move_robot_finger",
                {"hand": "right", "finger": "index", "position": "open"},
            )
        )

        self.assertEqual(result, {"error": "Herramienta desconocida: move_robot_finger"})


if __name__ == "__main__":
    unittest.main()
