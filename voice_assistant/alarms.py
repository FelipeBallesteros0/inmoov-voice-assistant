from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Santiago")
_TIME_ONLY_RE = re.compile(r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?::(?P<second>\d{2}))?$")


def alarms_path() -> Path:
    configured = os.getenv("RVA_ALARMS_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "rpi_voice_assistant" / "alarms.json"


def schedule_alarm(due_at: str, message: str) -> dict:
    due = parse_due_at(due_at)
    now = datetime.now(LOCAL_TZ)
    if due <= now:
        raise ValueError("La alarma debe quedar en el futuro.")

    clean_message = " ".join(message.strip().split())
    if not clean_message:
        raise ValueError("La alarma necesita un mensaje.")

    alarm = {
        "id": _new_alarm_id(due),
        "due_at": due.isoformat(),
        "message": clean_message,
        "created_at": now.isoformat(),
        "status": "pending",
        "triggered_at": None,
    }
    alarms = _load_alarms()
    alarms.append(alarm)
    _save_alarms(alarms)
    return alarm


def list_alarms(include_triggered: bool = False) -> list[dict]:
    alarms = _load_alarms()
    if not include_triggered:
        alarms = [alarm for alarm in alarms if alarm.get("status") == "pending"]
    return sorted(alarms, key=lambda alarm: str(alarm.get("due_at", "")))


def cancel_alarm(alarm_id: str) -> dict:
    target = alarm_id.strip()
    alarms = _load_alarms()
    for alarm in alarms:
        if alarm.get("id") == target and alarm.get("status") == "pending":
            alarm["status"] = "cancelled"
            alarm["cancelled_at"] = datetime.now(LOCAL_TZ).isoformat()
            _save_alarms(alarms)
            return {"cancelled": True, "alarm": alarm}
    return {"cancelled": False, "error": f"No encontre una alarma pendiente con id {alarm_id}"}


def pop_due_alarms(now: datetime | None = None) -> list[dict]:
    current = _as_local(now or datetime.now(LOCAL_TZ))
    alarms = _load_alarms()
    due: list[dict] = []
    changed = False

    for alarm in alarms:
        if alarm.get("status") != "pending":
            continue
        try:
            due_at = parse_due_at(str(alarm["due_at"]))
        except (KeyError, ValueError):
            alarm["status"] = "invalid"
            changed = True
            continue
        if due_at <= current:
            alarm["status"] = "triggered"
            alarm["triggered_at"] = current.isoformat()
            due.append(dict(alarm))
            changed = True

    if changed:
        _save_alarms(alarms)
    return due


def parse_due_at(value: str, now: datetime | None = None) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("Fecha/hora vacia para la alarma.")

    match = _TIME_ONLY_RE.match(raw)
    if match:
        current = _as_local(now or datetime.now(LOCAL_TZ))
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        second = int(match.group("second") or 0)
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError("Hora de alarma invalida.")
        due = datetime.combine(
            current.date(),
            time(hour, minute, second),
            tzinfo=LOCAL_TZ,
        )
        if due <= current:
            due += timedelta(days=1)
        return due

    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed_date = date.fromisoformat(raw)
        parsed = datetime.combine(parsed_date, time(9, 0), tzinfo=LOCAL_TZ)
    return _as_local(parsed)


def _as_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _new_alarm_id(due: datetime) -> str:
    return f"alarm-{due.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"


def _load_alarms() -> list[dict]:
    path = alarms_path()
    if not path.exists():
        return []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    alarms = body.get("alarms", []) if isinstance(body, dict) else []
    return [alarm for alarm in alarms if isinstance(alarm, dict)]


def _save_alarms(alarms: list[dict]) -> None:
    path = alarms_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"alarms": alarms}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
