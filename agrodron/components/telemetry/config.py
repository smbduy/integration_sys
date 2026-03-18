"""Конфигурация компонента telemetry.

Чтение топиков и параметров через переменные окружения.
"""
import os
from typing import Optional

from sdk.topic_utils import topic_for, system_name


def component_topic() -> str:
    return (os.environ.get("COMPONENT_TOPIC") or topic_for("telemetry")).strip()


def security_monitor_topic() -> str:
    return (os.environ.get("SECURITY_MONITOR_TOPIC") or topic_for("security_monitor")).strip()


def motors_topic() -> str:
    return (os.environ.get("MOTORS_TOPIC") or topic_for("motors")).strip()


def sprayer_topic() -> str:
    return (os.environ.get("SPRAYER_TOPIC") or topic_for("sprayer")).strip()


def navigation_topic() -> str:
    return (os.environ.get("NAVIGATION_TOPIC") or topic_for("navigation")).strip()


def autopilot_topic() -> str:
    """Топик автопилота (для EMERGENCY_STOP при emergency от ОрВД)."""
    return (os.environ.get("AUTOPILOT_TOPIC") or topic_for("autopilot")).strip()


def motors_get_state_action() -> str:
    return (os.environ.get("MOTORS_GET_STATE_ACTION") or "get_state").strip()


def sprayer_get_state_action() -> str:
    return (os.environ.get("SPRAYER_GET_STATE_ACTION") or "get_state").strip()


def _get_float(name: str, default: float, *, min_value: Optional[float] = None) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        value = float(default)
    else:
        value = float(raw)
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    return value


def telemetry_poll_interval_s() -> float:
    return _get_float("TELEMETRY_POLL_INTERVAL_S", 0.5, min_value=0.05)


def telemetry_request_timeout_s() -> float:
    return _get_float("TELEMETRY_REQUEST_TIMEOUT_S", 2.0, min_value=0.1)


# --- ОрВД ---

def orvd_topic() -> str:
    """Топик API ОрВД. Пусто — телеметрия в ОрВД не отправляется."""
    return (os.environ.get("ORVD_TOPIC") or os.environ.get("ORVD_EXTERNAL_TOPIC") or "").strip()


def orvd_enabled() -> bool:
    """Включена ли отправка телеметрии в ОрВД."""
    v = os.environ.get("ORVD_ENABLED", "false").strip().lower()
    return v in ("1", "true", "yes")


def orvd_drone_id() -> str:
    return (os.environ.get("ORVD_DRONE_ID") or os.environ.get("SITL_DRONE_ID") or "drone_001").strip()


def orvd_send_interval_s() -> float:
    """Период отправки телеметрии в ОрВД (сек)."""
    return _get_float("ORVD_TELEMETRY_SEND_INTERVAL_S", 1.0, min_value=0.2)
