from typing import Any, Dict, Optional

from sdk.base_component import BaseComponent
from broker.system_bus import SystemBus


class LimiterComponent(BaseComponent):
    """
    Упрощённый компонент ограничителя.

    Хранит миссию, последние навигационные и телеметрические данные, вычисляет
    грубое отклонение от маршрута и при превышении порогов публикует событие
    для экстренных ситуаций (через брокер/монитор).
    """

    def __init__(
        self,
        component_id: str,
        bus: SystemBus,
        topic: str = "components.limiter",
    ):
        self._mission: Optional[Dict[str, Any]] = None
        self._last_nav: Optional[Dict[str, Any]] = None
        self._last_telemetry: Optional[Dict[str, Any]] = None
        self._state: str = "NORMAL"
        self._max_distance_from_path_m: float = 10.0
        self._max_alt_deviation_m: float = 3.0

        super().__init__(
            component_id=component_id,
            component_type="limiter",
            topic=topic,
            bus=bus,
        )

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _is_trusted_sender(message: Dict[str, Any]) -> bool:
        sender = message.get("sender")
        return isinstance(sender, str) and sender.startswith("security_monitor")

    # ------------------------------------------------------------ registration

    def _register_handlers(self) -> None:
        self.register_handler("mission_load", self._handle_mission_load)
        self.register_handler("nav_state", self._handle_nav_state)
        self.register_handler("telemetry_state", self._handle_telemetry_state)
        self.register_handler("update_config", self._handle_update_config)
        self.register_handler("get_state", self._handle_get_state)

    # ---------------------------------------------------------------- handlers

    def _handle_mission_load(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        payload = message.get("payload") or {}
        mission = payload.get("mission")
        if not isinstance(mission, dict):
            return {"ok": False, "error": "invalid_mission"}
        self._mission = mission
        return {"ok": True}

    def _handle_nav_state(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_nav"}
        self._last_nav = payload
        self._recalculate()
        return {"ok": True}

    def _handle_telemetry_state(
        self, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_telemetry"}
        self._last_telemetry = payload
        return {"ok": True}

    def _handle_update_config(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        payload = message.get("payload") or {}
        if "max_distance_from_path_m" in payload:
            self._max_distance_from_path_m = float(payload["max_distance_from_path_m"])
        if "max_alt_deviation_m" in payload:
            self._max_alt_deviation_m = float(payload["max_alt_deviation_m"])
        return {
            "ok": True,
            "max_distance_from_path_m": self._max_distance_from_path_m,
            "max_alt_deviation_m": self._max_alt_deviation_m,
        }

    def _handle_get_state(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "state": self._state,
            "max_distance_from_path_m": self._max_distance_from_path_m,
            "max_alt_deviation_m": self._max_alt_deviation_m,
        }

    # -------------------------------------------------------------- core logic

    def _recalculate(self) -> None:
        if not self._mission or not self._last_nav:
            return

        steps = self._mission.get("steps") or []
        if not steps:
            return

        target = steps[-1]
        try:
            lat = float(self._last_nav.get("lat"))
            lon = float(self._last_nav.get("lon"))
            alt = float(self._last_nav.get("alt_m"))
            t_lat = float(target.get("lat"))
            t_lon = float(target.get("lon"))
            t_alt = float(target.get("alt_m"))
        except (TypeError, ValueError):
            return

        # Очень грубая оценка расстояния: просто евклидова метрика в градусах,
        # умноженная на константу, достаточная для прототипа.
        d_lat = lat - t_lat
        d_lon = lon - t_lon
        distance_m = ((d_lat**2 + d_lon**2) ** 0.5) * 111_000.0
        alt_dev = abs(alt - t_alt)

        if distance_m > self._max_distance_from_path_m or alt_dev > self._max_alt_deviation_m:
            if self._state != "EMERGENCY":
                self._state = "EMERGENCY"
                self._publish_emergency(distance_m, alt_dev)
        elif distance_m > 0.5 * self._max_distance_from_path_m or alt_dev > 0.5 * self._max_alt_deviation_m:
            self._state = "WARNING"
        else:
            self._state = "NORMAL"

    def _publish_emergency(self, distance_m: float, alt_dev: float) -> None:
        event_payload = {
            "event": "EMERGENCY_LAND_REQUIRED",
            "details": {
                "distance_from_path_m": distance_m,
                "max_distance_from_path_m": self._max_distance_from_path_m,
                "alt_deviation_m": alt_dev,
                "max_alt_deviation_m": self._max_alt_deviation_m,
            },
        }
        message = {
            "action": "event",
            "sender": self.component_id,
            "payload": event_payload,
        }
        # Публикуем на собственный топик; в реальной системе сообщение
        # подхватывается через брокер и доставляется компоненту emergensy.
        self.bus.publish(self.topic, message)

