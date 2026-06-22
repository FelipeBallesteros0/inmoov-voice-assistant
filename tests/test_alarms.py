import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from voice_assistant.alarms import (
    LOCAL_TZ,
    cancel_alarm,
    list_alarms,
    parse_due_at,
    pop_due_alarms,
    schedule_alarm,
)


class AlarmsTest(unittest.TestCase):
    def test_time_only_uses_next_occurrence(self) -> None:
        now = datetime(2026, 6, 11, 20, 0, tzinfo=LOCAL_TZ)

        due = parse_due_at("19:00", now=now)

        self.assertEqual(due.date().isoformat(), "2026-06-12")
        self.assertEqual(due.hour, 19)

    def test_schedule_list_and_pop_due_alarm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "alarms.json")
            with mock.patch.dict(os.environ, {"RVA_ALARMS_PATH": path}):
                due_at = datetime.now(LOCAL_TZ) + timedelta(minutes=5)
                alarm = schedule_alarm(due_at.isoformat(), "salir a comprar pan")

                self.assertEqual(list_alarms(), [alarm])
                self.assertEqual(pop_due_alarms(now=due_at - timedelta(seconds=1)), [])
                due = pop_due_alarms(now=due_at + timedelta(seconds=1))

                self.assertEqual(len(due), 1)
                self.assertEqual(due[0]["message"], "salir a comprar pan")
                self.assertEqual(list_alarms(), [])
                self.assertEqual(list_alarms(include_triggered=True)[0]["status"], "triggered")

    def test_cancel_alarm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "alarms.json")
            with mock.patch.dict(os.environ, {"RVA_ALARMS_PATH": path}):
                due_at = datetime.now(LOCAL_TZ) + timedelta(minutes=5)
                alarm = schedule_alarm(due_at.isoformat(), "cancelame")

                result = cancel_alarm(alarm["id"])

                self.assertTrue(result["cancelled"])
                self.assertEqual(list_alarms(), [])


if __name__ == "__main__":
    unittest.main()
