from __future__ import annotations

import time
from typing import Any, Dict, Optional

from broker.system_bus import SystemBus
from sdk.base_component import BaseComponent

from components.motors import config


class MotorsMode:
    IDLE = "IDLE"
    TRACKING = "TRACKING"
    LANDING = "LANDING"


class MotorsComponent(BaseComponent):
    """
    Компонент приводов (motors).

    Принимает команды:
    - SET_TARGET: целевые heading/speed/alt
    - LAND: аварийная посадка
    - get_state: вернуть последнее состояние

    Все входящие команды принимаются только от security_monitor (trusted sender).
    """

    def __init__(self, component_id: str, bus: SystemBus, topic: str = ""):
        self._mode: str = MotorsMode.IDLE
        self._last_target: Optional[Dict[str, Any]] = None
        self._last_cmd_ts: float = 0.0
        self._temperature_c: float = config.motors_temperature_c_default()

        super().__init__(
            component_id=component_id,
            component_type="motors",
            topic=(topic or config.component_topic()),
            bus=bus,
        )

    @staticmethod
    def _is_trusted_sender(message: Dict[str, Any]) -> bool:
        sender = message.get("sender")
        return isinstance(sender, str) and sender.startswith("security_monitor")

    def _register_handlers(self) -> None:
        self.register_handler("SET_TARGET", self._handle_set_target)
        self.register_handler("LAND", self._handle_land)
        self.register_handler("get_state", self._handle_get_state)

    def _handle_set_target(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_payload"}

        target = {
            "heading_deg": payload.get("heading_deg"),
            "ground_speed_mps": payload.get("ground_speed_mps"),
            "alt_m": payload.get("alt_m"),
        }
        self._last_target = target
        self._mode = MotorsMode.TRACKING
        self._last_cmd_ts = time.time()

        self._emit_sitl_command({"cmd": "SET_TARGET", "target": target})
        return {"ok": True, "mode": self._mode}

    def _handle_land(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        self._mode = MotorsMode.LANDING
        self._last_cmd_ts = time.time()
        self._emit_sitl_command({"cmd": "LAND"})
        return {"ok": True, "mode": self._mode}

    def _handle_get_state(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "last_target": self._last_target,
            "last_cmd_ts": self._last_cmd_ts,
            "temperature_c": self._temperature_c,
            "sitl_mode": config.sitl_mode(),
        }

    def _emit_sitl_command(self, command: Dict[str, Any]) -> None:
        """
        Варианты интеграции с SITL (будущие):
        - mqtt: publish в топик симулятора (например sitl.commands.v1)
        - redis: запись ключа (например drone:{id}:cmd)
        - http: POST в REST симулятора
        Сейчас реализован mock: публикуем в системный топик наблюдения.
        """
        mode = config.sitl_mode()
        if mode == "mock":
            self.bus.publish(
                config.sitl_commands_topic(),
                {
                    "source": "motors",
                    "command": command,
                },
            )
        else:
            # Пока не реализовано — чтобы компонент не падал, остаёмся в mock-поведение
            self.bus.publish(
                config.sitl_commands_topic(),
                {
                    "source": "motors",
                    "command": command,
                    "note": f"sitl_mode={mode} not implemented, emitted as mock",
                },
            )

