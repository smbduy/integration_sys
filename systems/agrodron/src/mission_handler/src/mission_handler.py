from typing import Any, Dict, Optional

from sdk.base_component import BaseComponent
from broker.system_bus import SystemBus

from components.mission_handler import config
from components.mission_handler.src.wpl_parser import parse_wpl


class MissionHandlerComponent(BaseComponent):
    """
    Обработчик миссий агродрона.

    На вход поступают **строго файлы WPL** (QGC WPL / ArduPilot Waypoint).
    Другие форматы на вход не принимаются — преобразование в WPL должно
    выполняться до отправки в этот компонент.

    Обработчик:
    - парсит WPL и преобразует в JSON-формат автопилота;
    - валидирует миссию;
    - передаёт её в автопилот через монитор безопасности;
    - пишет ключевые события в журнал.
    """

    def __init__(
        self,
        component_id: str,
        bus: SystemBus,
        topic: str = "",
    ):
        self._last_mission: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None

        super().__init__(
            component_id=component_id,
            component_type="mission_handler",
            topic=(topic or config.component_topic()),
            bus=bus,
        )

    # ------------------------------------------------------------ registration

    def _register_handlers(self) -> None:
        self.register_handler("LOAD_MISSION", self._handle_load_mission)
        self.register_handler("VALIDATE_ONLY", self._handle_validate_only)
        self.register_handler("get_state", self._handle_get_state)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _is_trusted_sender(message: Dict[str, Any]) -> bool:
        """Принимаем сообщения только от монитора безопасности."""
        sender = message.get("sender")
        return isinstance(sender, str) and sender.startswith("security_monitor")

    # ---------------------------------------------------------------- handlers

    def _handle_load_mission(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        payload = message.get("payload") or {}
        wpl_content = payload.get("wpl_content") if isinstance(payload, dict) else None

        if not wpl_content or not isinstance(wpl_content, str):
            self._last_error = "invalid_input_wpl_required"
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": self._last_error},
            )
            return {"ok": False, "error": self._last_error}

        mission_id = payload.get("mission_id") if isinstance(payload, dict) else None
        mission, parse_error = parse_wpl(wpl_content, mission_id=mission_id)

        if mission is None:
            self._last_error = parse_error or "wpl_parse_failed"
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": self._last_error, "wpl_preview": wpl_content[:200]},
            )
            return {"ok": False, "error": self._last_error}

        ok, error = self._validate_mission(mission)
        if not ok:
            self._last_error = error
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": error, "mission_id": mission.get("mission_id")},
            )
            return {"ok": False, "error": error}

        self._last_mission = mission
        self._last_error = None
        mid = mission.get("mission_id")

        self._log_to_journal(
            event="MISSION_HANDLER_MISSION_RECEIVED",
            details={"mission_id": mid},
        )

        request_message: Dict[str, Any] = {
            "action": "proxy_request",
            "sender": self.component_id,
            "payload": {
                "target": {
                    "topic": config.autopilot_topic(),
                    "action": "mission_load",
                },
                "data": {
                    "mission": mission,
                },
            },
        }
        response = self.bus.request(
            topic=config.security_monitor_topic(),
            message=request_message,
            timeout=config.mission_handler_request_timeout_s(),
        )
        if not response:
            error = "autopilot_no_response"
            self._last_error = error
            self._log_to_journal(
                event="MISSION_HANDLER_AUTOPILOT_ERROR",
                details={"error": error, "mission_id": mid},
            )
            return {"ok": False, "error": error}

        ap_resp = response.get("target_response") or response.get("payload") or response
        if not isinstance(ap_resp, dict):
            ap_resp = {}
        if not ap_resp.get("ok", True):
            error = str(ap_resp.get("error") or "autopilot_error")
            self._last_error = error
            self._log_to_journal(
                event="MISSION_HANDLER_AUTOPILOT_ERROR",
                details={"error": error, "mission_id": mid},
            )
            return {"ok": False, "error": error}

        self._log_to_journal(
            event="MISSION_HANDLER_MISSION_SENT_TO_AUTOPILOT",
            details={"mission_id": mid},
        )
        return {"ok": True}

    def _handle_validate_only(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        payload = message.get("payload") or {}
        wpl_content = payload.get("wpl_content") if isinstance(payload, dict) else None

        if not wpl_content or not isinstance(wpl_content, str):
            self._last_error = "invalid_input_wpl_required"
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": self._last_error},
            )
            return {"ok": False, "error": self._last_error}

        mission_id = payload.get("mission_id") if isinstance(payload, dict) else None
        mission, parse_error = parse_wpl(wpl_content, mission_id=mission_id)

        if mission is None:
            self._last_error = parse_error or "wpl_parse_failed"
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": self._last_error},
            )
            return {"ok": False, "error": self._last_error}

        ok, error = self._validate_mission(mission)
        if not ok:
            self._last_error = error
            self._log_to_journal(
                event="MISSION_HANDLER_VALIDATION_ERROR",
                details={"error": error},
            )
            return {"ok": False, "error": error}

        self._last_error = None
        return {"ok": True}

    def _handle_get_state(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        return {
            "last_mission": self._last_mission,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------- validations

    def _validate_mission(self, mission: Dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(mission, dict):
            return False, "mission_not_dict"

        mission_id = mission.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id:
            return False, "invalid_mission_id"

        steps = mission.get("steps")
        if not isinstance(steps, list) or not steps:
            return False, "empty_steps"

        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                return False, f"invalid_step_{idx}"
            for field in ("lat", "lon", "alt_m"):
                if field not in step:
                    return False, f"missing_{field}_in_step_{idx}"

        return True, ""

    # -------------------------------------------------------------- journal log

    def _log_to_journal(self, event: str, details: Dict[str, Any]) -> None:
        message = {
            "action": "proxy_publish",
            "sender": self.component_id,
            "payload": {
                "target": {
                    "topic": config.journal_topic(),
                    "action": "LOG_EVENT",
                },
                "data": {
                    "event": event,
                    "source": "mission_handler",
                    "details": details,
                },
            },
        }
        self.bus.publish(config.security_monitor_topic(), message)
