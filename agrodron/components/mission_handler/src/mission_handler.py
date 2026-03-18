import json
import uuid
from datetime import datetime, timezone
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
        self._drone_registered_with_orvd: bool = False

        super().__init__(
            component_id=component_id,
            component_type="mission_handler",
            topic=(topic or config.component_topic()),
            bus=bus,
        )

    # ------------------------------------------------------------ registration

    def _register_handlers(self) -> None:
        self.register_handler("load_mission", self._handle_load_mission)
        self.register_handler("validate_only", self._handle_validate_only)
        self.register_handler("get_state", self._handle_get_state)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _is_trusted_sender(message: Dict[str, Any]) -> bool:
        """Принимаем сообщения только от монитора безопасности."""
        sender = message.get("sender")
        return isinstance(sender, str) and sender == config.security_monitor_topic()

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

        # ОрВД: регистрация дрона и миссии перед загрузкой в автопилот
        if config.orvd_enabled() and config.orvd_topic():
            ok_orvd, err_orvd = self._orvd_register_drone_and_mission(mission)
            if not ok_orvd:
                self._last_error = err_orvd or "orvd_rejected"
                self._log_to_journal(
                    event="MISSION_HANDLER_ORVD_ERROR",
                    details={"error": self._last_error, "mission_id": mid},
                )
                return {"ok": False, "error": self._last_error}

        request_message: Dict[str, Any] = {
            "action": "proxy_request",
            "sender": self.topic,
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
        self._send_home_to_sitl(mission)
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

    # ------------------------------------------------------------ ORVD

    def _orvd_proxy_request(self, action: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Запрос к ОрВД через монитор безопасности."""
        topic = config.orvd_topic()
        if not topic:
            return None
        message = {
            "action": "proxy_request",
            "sender": self.topic,
            "payload": {"target": {"topic": topic, "action": action}, "data": payload},
        }
        response = self.bus.request(
            config.security_monitor_topic(),
            message,
            timeout=config.mission_handler_request_timeout_s(),
        )
        if not isinstance(response, dict):
            return None
        return response.get("target_response") or response

    def _orvd_register_drone_and_mission(self, mission: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Регистрирует дрон (если ещё не зарегистрирован) и миссию в ОрВД. Возвращает (ok, error)."""
        drone_id = config.orvd_drone_id()

        if not self._drone_registered_with_orvd:
            resp = self._orvd_proxy_request(
                "register_drone",
                {"drone_id": drone_id, "model": "Agrodron", "operator": config.orvd_operator(), "additional_info": {}},
            )
            if not resp or resp.get("status") != "registered":
                return False, resp.get("message") or "orvd_register_drone_failed"
            self._drone_registered_with_orvd = True

        steps = mission.get("steps") or []
        route = [{"lat": float(s.get("lat", 0)), "lon": float(s.get("lon", 0))} for s in steps if isinstance(s, dict)]
        velocity = 5.0
        if steps and isinstance(steps[0], dict):
            velocity = float(steps[0].get("speed_mps", 5.0))

        resp = self._orvd_proxy_request(
            "register_mission",
            {
                "mission_id": mission.get("mission_id"),
                "drone_id": drone_id,
                "route": route,
                "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "velocity": velocity,
            },
        )
        if not resp:
            return False, "orvd_register_mission_timeout"
        if resp.get("status") == "mission_registered":
            return True, None
        if resp.get("status") == "rejected":
            return False, resp.get("reason") or "orvd_rejected"
        return False, resp.get("message") or "orvd_register_mission_failed"

    # ------------------------------------------------------------ SITL HOME

    def _build_home_message(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Формирует сообщение HOME в формате SITL из первого waypoint."""
        lat = float(step.get("lat") or 0.0)
        lon = float(step.get("lon") or 0.0)
        alt_m = float(step.get("alt_m") or 0.0)
        now = datetime.now(timezone.utc)
        time_str = now.strftime("%H%M%S.000")
        date_str = now.strftime("%d%m%y")
        lat_nmea = f"{int(abs(lat)):02d}{int((abs(lat) % 1) * 60):02d}.{int(round(((abs(lat) % 1) * 60) % 1 * 10000)):04d}"
        lon_nmea = f"{int(abs(lon)):03d}{int((abs(lon) % 1) * 60):02d}.{int(round(((abs(lon) % 1) * 60) % 1 * 10000)):04d}"
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        return {
            "drone_id": config.sitl_drone_id(),
            "msg_id": str(uuid.uuid4()),
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "nmea": {
                "rmc": {
                    "talker_id": "GN",
                    "time": time_str,
                    "status": "A",
                    "latitude": lat_nmea,
                    "lat_dir": lat_dir,
                    "longitude": lon_nmea,
                    "lon_dir": lon_dir,
                    "speed_knots": 0.0,
                    "course_degrees": 0.0,
                    "date": date_str,
                },
                "gga": {
                    "talker_id": "GN",
                    "time": time_str,
                    "latitude": lat_nmea,
                    "lat_dir": lat_dir,
                    "longitude": lon_nmea,
                    "lon_dir": lon_dir,
                    "quality": 1,
                    "satellites": 10,
                    "hdop": 0.8,
                },
            },
            "derived": {
                "lat_decimal": round(lat, 6),
                "lon_decimal": round(lon, 6),
                "altitude_msl": round(alt_m, 2),
                "gps_valid": True,
                "satellites_used": 10,
                "position_accuracy_hdop": 0.8,
            },
        }

    def _send_home_to_sitl(self, mission: Dict[str, Any]) -> None:
        """Отправляет HOME в SITL через proxy_publish."""
        steps = mission.get("steps") if isinstance(mission, dict) else []
        if not steps:
            return
        sitl = config.sitl_topic()
        if not sitl:
            return
        home_msg = self._build_home_message(steps[0])
        message = {
            "action": "proxy_publish",
            "sender": self.topic,
            "payload": {
                "target": {"topic": sitl, "action": "set_home"},
                "data": home_msg,
            },
        }
        self.bus.publish(config.security_monitor_topic(), message)

    # -------------------------------------------------------------- journal log

    def _log_to_journal(self, event: str, details: Dict[str, Any]) -> None:
        message = {
            "action": "proxy_publish",
            "sender": self.topic,
            "payload": {
                "target": {
                    "topic": config.journal_topic(),
                    "action": "log_event",
                },
                "data": {
                    "event": event,
                    "source": "mission_handler",
                    "details": details,
                },
            },
        }
        self.bus.publish(config.security_monitor_topic(), message)
