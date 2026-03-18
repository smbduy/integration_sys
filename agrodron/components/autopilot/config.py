import os
from typing import Optional

from sdk.topic_utils import topic_for, system_name


def component_topic() -> str:
    return (os.environ.get("COMPONENT_TOPIC") or topic_for("autopilot")).strip()


def security_monitor_topic() -> str:
    return (os.environ.get("SECURITY_MONITOR_TOPIC") or topic_for("security_monitor")).strip()


def journal_topic() -> str:
    return (os.environ.get("JOURNAL_TOPIC") or topic_for("journal")).strip()


def _get_float(name: str, default: float, *, min_value: Optional[float] = None) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        value = float(default)
    else:
        value = float(raw)
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    return value


def autopilot_control_interval_s() -> float:
    return _get_float("AUTOPILOT_CONTROL_INTERVAL_S", 0.2, min_value=0.01)


def autopilot_nav_poll_interval_s() -> float:
    return _get_float("AUTOPILOT_NAV_POLL_INTERVAL_S", 0.2, min_value=0.01)


def autopilot_request_timeout_s() -> float:
    return _get_float("AUTOPILOT_REQUEST_TIMEOUT_S", 2.0, min_value=0.1)


def navigation_get_state_action() -> str:
    return (os.environ.get("NAVIGATION_GET_STATE_ACTION") or "get_state").strip()


def orvd_topic() -> str:
    """Топик API ОрВД. Пусто = не обращаться к ОрВД."""
    return (os.environ.get("ORVD_TOPIC") or os.environ.get("ORVD_EXTERNAL_TOPIC") or "").strip()


def orvd_drone_id() -> str:
    """Идентификатор дрона для ОрВД."""
    return (os.environ.get("ORVD_DRONE_ID") or os.environ.get("SITL_DRONE_ID") or "drone_001").strip()


def nus_topic() -> str:
    return (os.environ.get("NUS_TOPIC") or "").strip()


def droneport_topic() -> str:
    return (os.environ.get("DRONEPORT_TOPIC") or "").strip()


def sitl_topic() -> str:
    return (os.environ.get("SITL_TOPIC") or "").strip()

