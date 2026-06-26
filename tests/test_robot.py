import os
import unittest
from unittest import mock

from voice_assistant import robot
from voice_assistant.robot import (
    RobotError,
    get_robot_status,
    move_robot_finger,
    run_robot_routine,
    run_robot_sequence,
    set_robot_joints,
)


class _FakeSerial:
    def __init__(self, responses=None) -> None:
        self.responses = list(responses or [b"OK STATUS idle\n"])
        self.writes = []
        self.reset_called = False
        self.flushed = False
        self.is_open = True
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close(self):
        self.is_open = False
        self.closed = True

    def reset_input_buffer(self):
        self.reset_called = True

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        self.flushed = True

    def readline(self):
        if self.responses:
            return self.responses.pop(0)
        return b""


class RobotTest(unittest.TestCase):
    def setUp(self) -> None:
        robot.reset_robot_connection()

    def tearDown(self) -> None:
        robot.reset_robot_connection()

    def test_get_robot_status_sends_serial_command(self) -> None:
        fake = _FakeSerial(responses=[b"READY\n", b"OK STATUS idle\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = get_robot_status()

        self.assertTrue(result.ok)
        self.assertEqual(result.command, "ROBOT STATUS")
        self.assertEqual(result.port, "/dev/test-robot")
        self.assertEqual(result.response, "OK STATUS idle")
        self.assertEqual(fake.writes, [b"ROBOT STATUS\n"])
        self.assertTrue(fake.reset_called)
        self.assertTrue(fake.flushed)

    def test_set_robot_joints_sends_compact_serial_command(self) -> None:
        fake = _FakeSerial(responses=[b"OK JOINTS 2\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = set_robot_joints(
                            [
                                {"joint": "cabeza", "angle_degrees": 90},
                                {"joint": "indice_der", "angle_degrees": 40},
                            ]
                        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "ROBOT JOINTS 6:90 17:40")
        self.assertEqual(result["port"], "/dev/test-robot")
        self.assertEqual(result["response"], "OK JOINTS 2")
        self.assertEqual(
            result["joints_moved"],
            [
                {"joint": "cabeza", "index": 6, "angle_degrees": 90},
                {"joint": "indice_der", "index": 17, "angle_degrees": 40},
            ],
        )
        self.assertEqual(fake.writes, [b"ROBOT JOINTS 6:90 17:40\n"])

    def test_set_robot_joints_normalizes_joint_names(self) -> None:
        fake = _FakeSerial(responses=[b"OK JOINTS 1\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = set_robot_joints([{"joint": "lat izq", "angle_degrees": 100}])

        self.assertEqual(result["command"], "ROBOT JOINTS 0:100")
        self.assertEqual(fake.writes, [b"ROBOT JOINTS 0:100\n"])

    def test_set_robot_joints_rejects_duplicate_joint(self) -> None:
        with self.assertRaises(RobotError):
            set_robot_joints(
                [
                    {"joint": "cabeza", "angle_degrees": 90},
                    {"joint": "cabeza", "angle_degrees": 100},
                ]
            )

    def test_set_robot_joints_rejects_unknown_joint(self) -> None:
        with self.assertRaises(RobotError):
            set_robot_joints([{"joint": "codo_der", "angle_degrees": 90}])

    def test_set_robot_joints_rejects_out_of_range_angle(self) -> None:
        with self.assertRaises(RobotError):
            set_robot_joints([{"joint": "lat_izq", "angle_degrees": 70}])

    def test_set_robot_joints_rejects_non_integer_angle(self) -> None:
        with self.assertRaises(RobotError):
            set_robot_joints([{"joint": "cabeza", "angle_degrees": 90.5}])

    def test_run_robot_routine_normalizes_name(self) -> None:
        fake = _FakeSerial(responses=[b"OK ROUTINE head_left\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = run_robot_routine("head left")

        self.assertEqual(result.command, "ROBOT ROUTINE head_left")
        self.assertEqual(result.response, "OK ROUTINE head_left")
        self.assertEqual(fake.writes, [b"ROBOT ROUTINE head_left\n"])

    def test_move_robot_finger_normalizes_spanish_aliases(self) -> None:
        fake = _FakeSerial(responses=[b"OK FINGER right index open\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = move_robot_finger("derecha", "indice", "levanta")

        self.assertEqual(result.command, "ROBOT FINGER right index open")
        self.assertEqual(result.response, "OK FINGER right index open")
        self.assertEqual(fake.writes, [b"ROBOT FINGER right index open\n"])

    def test_move_robot_finger_rejects_unknown_finger(self) -> None:
        with self.assertRaises(RobotError):
            move_robot_finger("right", "elbow", "open")

    def test_run_robot_sequence_reuses_one_serial_connection(self) -> None:
        fake = _FakeSerial(
            responses=[
                b"OK FINGER right index open\n",
                b"OK ROUTINE head_center\n",
            ]
        )
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        result = run_robot_sequence(
                            [
                                {
                                    "action_type": "finger",
                                    "routine_name": "none",
                                    "hand": "right",
                                    "finger": "index",
                                    "position": "open",
                                    "delay_after_seconds": 0,
                                },
                                {
                                    "action_type": "routine",
                                    "routine_name": "head_center",
                                    "hand": "none",
                                    "finger": "none",
                                    "position": "none",
                                    "delay_after_seconds": 0,
                                },
                            ]
                        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["actions_executed"], 2)
        self.assertEqual(serial_module.Serial.call_count, 1)
        self.assertEqual(
            fake.writes,
            [b"ROBOT FINGER right index open\n", b"ROBOT ROUTINE head_center\n"],
        )

    def test_run_robot_sequence_rejects_missing_finger_data(self) -> None:
        with self.assertRaises(RobotError):
            run_robot_sequence(
                [
                    {
                        "action_type": "finger",
                        "routine_name": "none",
                        "hand": "right",
                        "finger": "none",
                        "position": "open",
                        "delay_after_seconds": 0,
                    }
                ]
            )

    def test_run_robot_routine_rejects_unknown_routine(self) -> None:
        with self.assertRaises(RobotError):
            run_robot_routine("wave individual servo")

    def test_run_robot_routine_rejects_arduino_error_response(self) -> None:
        fake = _FakeSerial(responses=[b"ERR unknown_routine\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        with self.assertRaises(RobotError):
                            run_robot_routine("rest")


    def test_separate_commands_reuse_one_serial_connection(self) -> None:
        # Regresion: el Arduino se resetea por DTR cada vez que se ABRE el puerto.
        # Al resetear, el firmware deja los servos sueltos y currentAngle=HOME, asi
        # que las articulaciones "vuelven a home" despues de cada accion. Dos
        # acciones separadas deben compartir UNA sola conexion (sin reabrir/resetear).
        fake = _FakeSerial(responses=[b"OK JOINTS 1\n", b"OK STATUS idle\n"])
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(robot, "serial", serial_module):
            with mock.patch.object(robot.Path, "exists", return_value=True):
                with mock.patch.object(robot.time, "sleep"):
                    with mock.patch.dict(os.environ, {"ROBOT_SERIAL_PORT": "/dev/test-robot"}):
                        set_robot_joints([{"joint": "mandibula", "angle_degrees": 40}])
                        get_robot_status()

        self.assertEqual(serial_module.Serial.call_count, 1)
        self.assertEqual(
            fake.writes,
            [b"ROBOT JOINTS 7:40\n", b"ROBOT STATUS\n"],
        )


if __name__ == "__main__":
    unittest.main()
