import os
import unittest
from unittest import mock

from voice_assistant import servo
from voice_assistant.servo import ServoError, move_servo, run_servo_sequence


class _FakeSerial:
    def __init__(self, response=b"OK 90\n") -> None:
        self.response = response
        self.writes = []
        self.reset_called = False
        self.flushed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def reset_input_buffer(self):
        self.reset_called = True

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        self.flushed = True

    def readline(self):
        return self.response


class ServoTest(unittest.TestCase):
    def test_move_servo_sends_serial_command(self) -> None:
        fake = _FakeSerial(response=b"OK 90\n")
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(servo, "serial", serial_module):
            with mock.patch.object(servo.Path, "exists", return_value=True):
                with mock.patch.object(servo.time, "sleep"):
                    with mock.patch.dict(os.environ, {"SERVO_SERIAL_PORT": "/dev/test-servo"}):
                        result = move_servo(90)

        self.assertTrue(result.moved)
        self.assertEqual(result.angle, 90)
        self.assertEqual(result.port, "/dev/test-servo")
        self.assertEqual(result.response, "OK 90")
        self.assertEqual(fake.writes, [b"SERVO 90\n"])
        self.assertTrue(fake.reset_called)
        self.assertTrue(fake.flushed)

    def test_move_servo_rejects_out_of_range_angle(self) -> None:
        with self.assertRaises(ServoError):
            move_servo(181)

    def test_move_servo_rejects_bad_angle(self) -> None:
        with self.assertRaises(ServoError):
            move_servo("noventa")

    def test_move_servo_rejects_arduino_error_response(self) -> None:
        fake = _FakeSerial(response=b"ERR angle_out_of_range\n")
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(servo, "serial", serial_module):
            with mock.patch.object(servo.Path, "exists", return_value=True):
                with mock.patch.object(servo.time, "sleep"):
                    with mock.patch.dict(os.environ, {"SERVO_SERIAL_PORT": "/dev/test-servo"}):
                        with self.assertRaises(ServoError):
                            move_servo(90)

    def test_run_servo_sequence_reuses_serial_port(self) -> None:
        fake = _FakeSerial(response=b"OK 90\n")
        responses = [b"OK 90\n", b"OK 180\n", b"OK 90\n", b"OK 180\n"]
        fake.readline = mock.Mock(side_effect=responses)
        serial_module = mock.Mock()
        serial_module.Serial.return_value = fake

        with mock.patch.object(servo, "serial", serial_module):
            with mock.patch.object(servo.Path, "exists", return_value=True):
                with mock.patch.object(servo.time, "sleep"):
                    with mock.patch.dict(os.environ, {"SERVO_SERIAL_PORT": "/dev/test-servo"}):
                        result = run_servo_sequence(
                            [
                                {"angle_degrees": 90, "delay_after_seconds": 1},
                                {"angle_degrees": 180, "delay_after_seconds": 0},
                            ],
                            repeat=2,
                        )

        self.assertTrue(result["completed"])
        self.assertEqual(result["steps_executed"], 4)
        self.assertEqual(serial_module.Serial.call_count, 1)
        self.assertEqual(
            fake.writes,
            [b"SERVO 90\n", b"SERVO 180\n", b"SERVO 90\n", b"SERVO 180\n"],
        )

    def test_run_servo_sequence_rejects_large_delay(self) -> None:
        with self.assertRaises(ServoError):
            run_servo_sequence(
                [{"angle_degrees": 90, "delay_after_seconds": 11}],
                repeat=1,
            )


if __name__ == "__main__":
    unittest.main()
