"""Конфигурация компонента mission_handler.

Чтение SYSTEM_NAME, топиков и параметров через переменные окружения.
"""
import os
from typing import Optional

from sdk.topic_utils import topic_for, system_name


def component_topic() -> str:
    return (os.environ.get("COMPONENT_TOPIC") or topic_for("mission_handler")).strip()


def security_monitor_topic() -> str:
    return (os.environ.get("SECURITY_MONITOR_TOPIC") or topic_for("security_monitor")).strip()


def autopilot_topic() -> str:
    return (os.environ.get("AUTOPILOT_TOPIC") or topic_for("autopilot")).strip()


def journal_topic() -> str:
    return (os.environ.get("JOURNAL_TOPIC") or topic_for("journal")).strip()


def sitl_topic() -> str:
    return (os.environ.get("SITL_TOPIC") or "").strip()


def sitl_drone_id() -> str:
    return (os.environ.get("SITL_DRONE_ID") or "drone_001").strip()


def _get_float(name: str, default: float, *, min_value: Optional[float] = None) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        value = float(default)
    else:
        value = float(raw)
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    return value


def mission_handler_request_timeout_s() -> float:
    return _get_float("MISSION_HANDLER_REQUEST_TIMEOUT_S", 10.0, min_value=0.1)


def orvd_topic() -> str:
    """Топик API ОрВД (v1.ORVD.ORVD001.main). Пусто — ОрВД не используется."""
    return (os.environ.get("ORVD_TOPIC") or os.environ.get("ORVD_EXTERNAL_TOPIC") or "").strip()


def orvd_enabled() -> bool:
    """Включена ли регистрация в ОрВД перед загрузкой миссии."""
    v = os.environ.get("ORVD_ENABLED", "false").strip().lower()
    return v in ("1", "true", "yes")


def orvd_drone_id() -> str:
    """Идентификатор дрона для ОрВД."""
    return (os.environ.get("ORVD_DRONE_ID") or os.environ.get("SITL_DRONE_ID") or "drone_001").strip()


def orvd_operator() -> str:
    """Эксплуатант для регистрации дрона в ОрВД."""
    return (os.environ.get("ORVD_OPERATOR") or "AgrodronOperator").strip()
