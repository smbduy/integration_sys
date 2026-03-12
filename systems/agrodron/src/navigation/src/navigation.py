"""
Компонент навигации агродрона.

Получает навигационные данные от SITL-адаптера (через монитор безопасности),
нормализует форматы sitl.position.v1 / Redis в единый NAV_STATE,
хранит последнее состояние и отдаёт его по запросу (get_state).

Взаимодействие с SITL — только через монитор (proxy_request → components.sitl_adapter).
SITL-адаптер читает MQTT sitl.position.v1 или Redis drone:{id}:state и возвращает JSON.
"""
import math
import threading
import time
from typing import Any, Dict, Optional

from sdk.base_component import BaseComponent
from broker.system_bus import SystemBus

from components.navigation import config
from components.navigation.src.sitl_normalizer import normalize_sitl_to_nav_state


class NavigationComponent(BaseComponent):
    """
    Компонент навигации агродрона.

    - Опрашивает SITL-адаптер через монитор безопасности (10 Гц);
    - Нормализует форматы SITL (sitl.position.v1, Redis state) в NAV_STATE;
    - Хранит последнее состояние и отдаёт по get_state;
    - Принимает обновление конфигурации (nav_state, update_config).
    """

    def __init__(
        self,
        component_id: str,
        bus: SystemBus,
        topic: str,
    ):
        self._last_nav_state: Optional[Dict[str, Any]] = None
        self._config: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._housekeeping_thread: Optional[threading.Thread] = None

        super().__init__(
            component_id=component_id,
            component_type="navigation",
            topic=topic,
            bus=bus,
        )

    # ------------------------------------------------------------ registration

    def _register_handlers(self) -> None:
        self.register_handler("nav_state", self._handle_nav_state)
        self.register_handler("update_config", self._handle_update_config)
        self.register_handler("get_state", self._handle_get_state)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _is_trusted_sender(message: Dict[str, Any]) -> bool:
        """Принимаем сообщения только от монитора безопасности."""
        sender = message.get("sender")
        return isinstance(sender, str) and sender.startswith("security_monitor")

    # ---------------------------------------------------------------- handlers

    def _handle_nav_state(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_nav_payload"}

        normalized = normalize_sitl_to_nav_state(payload)
        with self._lock:
            self._last_nav_state = normalized
        return {"ok": True}

    def _handle_update_config(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_config_payload"}

        with self._lock:
            self._config.update(payload)
            current = dict(self._config)
        return {"ok": True, "config": current}

    def _handle_get_state(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None

        with self._lock:
            nav_state = dict(self._last_nav_state) if isinstance(self._last_nav_state, dict) else None
            config_copy = dict(self._config)
        # payload — для совместимости с autopilot/limiter (они читают target_response.payload)
        return {
            "nav_state": nav_state,
            "config": config_copy,
            "payload": nav_state,
        }

    # --------------------------------------------------------------- lifecycle

    def start(self) -> None:
        super().start()
        self._housekeeping_thread = threading.Thread(
            target=self._housekeeping_loop,
            name=f"{self.component_id}_housekeeping",
            daemon=True,
        )
        self._housekeeping_thread.start()

    def stop(self) -> None:
        super().stop()

    # ----------------------------------------------------------- housekeeping

    def _housekeeping_loop(self) -> None:
        """Опрос SITL-адаптера через монитор безопасности (10 Гц)."""
        interval = config.navigation_poll_interval_s()
        while self._running:
            try:
                self._poll_sitl_once()
            except Exception as exc:
                print(f"[{self.component_id}] SITL poll error: {exc}")
            time.sleep(interval)

    def _poll_sitl_once(self) -> None:
        """
        Один шаг опроса SITL-адаптера через монитор.

        SITL-адаптер (bridge) читает MQTT sitl.position.v1 или Redis drone:{id}:state
        и возвращает JSON. Навигация нормализует его в NAV_STATE.
        """
        request_message: Dict[str, Any] = {
            "action": "proxy_request",
            "sender": self.component_id,
            "payload": {
                "target": {
                    "topic": config.sitl_adapter_topic(),
                    "action": "get_nav_state",
                },
                "data": {"drone_id": self._config.get("drone_id")},
            },
        }

        response = self.bus.request(
            topic=config.security_monitor_topic(),
            message=request_message,
            timeout=config.navigation_request_timeout_s(),
        )
        if not response:
            return

        # Ответ монитора: target_response или payload
        sitl_resp = response.get("target_response") or response.get("payload") or response
        if not isinstance(sitl_resp, dict):
            return

        raw = sitl_resp.get("nav_state", sitl_resp)
        if not isinstance(raw, dict):
            return

        normalized = normalize_sitl_to_nav_state(raw, self._config)
        with self._lock:
            self._last_nav_state = normalized
            drone_id = normalized.get("drone_id") or self._config.get("drone_id")

        # Публикация в общий поток (для подписчиков, если есть)
        self._publish_nav_state(normalized)

        # Событие при деградации GPS
        gps_valid = bool(normalized.get("gps_valid", True))
        if not gps_valid:
            self._log_gps_degraded(normalized)

    # ----------------------------------------------------------- publishing

    def _publish_nav_state(self, nav_state: Dict[str, Any]) -> None:
        """Публикует NAV_STATE в agrodron.navigation.state."""
        message = dict(nav_state)
        if not message.get("drone_id") and self._config.get("drone_id"):
            message["drone_id"] = self._config.get("drone_id")
        self.bus.publish(config.agrodron_nav_state_topic(), message)

    def _log_gps_degraded(self, nav_state: Dict[str, Any]) -> None:
        """Отправляет событие NAVIGATION_GPS_DEGRADED в журнал через МБ."""
        msg = {
            "action": "proxy_publish",
            "sender": self.component_id,
            "payload": {
                "target": {
                    "topic": config.journal_topic(),
                    "action": "LOG_EVENT",
                },
                "data": {
                    "event": "NAVIGATION_GPS_DEGRADED",
                    "source": "navigation",
                    "details": {"nav_state": nav_state},
                },
            },
        }
        self.bus.publish(config.security_monitor_topic(), msg)
