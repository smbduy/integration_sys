from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from broker.system_bus import SystemBus
from kafka import KafkaProducer
from sdk.base_component import BaseComponent

from components.motors import config


def _decimal_to_nmea_lat(lat: float) -> tuple[str, str]:
    """Десятичные градусы -> NMEA DDMM.MMMM, dir (N/S)."""
    lat = max(-90.0, min(90.0, lat))
    deg = int(abs(lat))
    mins = (abs(lat) - deg) * 60.0
    nmea = f"{deg:02d}{int(mins):02d}.{int(round((mins % 1) * 10000)):04d}"
    return (nmea, "N" if lat >= 0 else "S")


def _decimal_to_nmea_lon(lon: float) -> tuple[str, str]:
    """Десятичные градусы -> NMEA DDDMM.MMMM, dir (E/W)."""
    lon = max(-180.0, min(180.0, lon))
    deg = int(abs(lon))
    mins = (abs(lon) - deg) * 60.0
    nmea = f"{deg:03d}{int(mins):02d}.{int(round((mins % 1) * 10000)):04d}"
    return (nmea, "E" if lon >= 0 else "W")


def _vx_vy_to_course_speed(vx: float, vy: float) -> tuple[float, float]:
    """vx, vy (м/с) -> course_degrees, speed_knots. North=0, East=90."""
    speed_mps = math.sqrt(vx * vx + vy * vy)
    if speed_mps < 1e-6:
        return (0.0, 0.0)
    heading_rad = math.atan2(vx, vy)  # North=0, East=pi/2
    course_deg = (math.degrees(heading_rad) + 360.0) % 360.0
    speed_knots = speed_mps * 1.94384
    return (course_deg, speed_knots)


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
        self._kafka_producer: Optional[KafkaProducer] = None

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

        # Поддержка нового формата (vx, vy, vz) и старого (heading_deg, ground_speed_mps)
        vx = payload.get("vx")
        vy = payload.get("vy")
        vz = payload.get("vz")
        if vx is None or vy is None or vz is None:
            h = float(payload.get("heading_deg") or 0.0)
            s = float(payload.get("ground_speed_mps") or 0.0)
            hr = math.radians(h)
            vx = s * math.sin(hr)
            vy = s * math.cos(hr)
            vz = 0.0
        else:
            vx = float(vx)
            vy = float(vy)
            vz = float(vz)

        target = {
            "vx": vx,
            "vy": vy,
            "vz": vz,
            "alt_m": payload.get("alt_m"),
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "heading_deg": payload.get("heading_deg"),
            "drop": payload.get("drop", False),
        }
        self._last_target = target
        self._mode = MotorsMode.TRACKING
        self._last_cmd_ts = time.time()

        self._emit_sitl_command(target)
        return {"ok": True, "mode": self._mode}

    def _handle_land(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_trusted_sender(message):
            return None
        self._mode = MotorsMode.LANDING
        self._last_cmd_ts = time.time()
        # Аварийная посадка: нулевая скорость, emergency_landing=True
        last = self._last_target or {}
        self._emit_sitl_command({
            "vx": 0.0, "vy": 0.0, "vz": -2.0,
            "alt_m": last.get("alt_m", 0.0),
            "lat": last.get("lat", 0.0),
            "lon": last.get("lon", 0.0),
            "heading_deg": last.get("heading_deg", 0.0),
            "drop": False,
            "emergency_landing": True,
        })
        return {"ok": True, "mode": self._mode}

    def _handle_get_state(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "last_target": self._last_target,
            "last_cmd_ts": self._last_cmd_ts,
            "temperature_c": self._temperature_c,
            "sitl_mode": config.sitl_mode(),
        }

    def _build_sitl_command(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Формирует команду в формате SITL Command Message."""
        lat = float(data.get("lat") or 0.0)
        lon = float(data.get("lon") or 0.0)
        alt_m = float(data.get("alt_m") or 0.0)
        vx = float(data.get("vx") or 0.0)
        vy = float(data.get("vy") or 0.0)
        vz = float(data.get("vz") or 0.0)
        drop = bool(data.get("drop", False))
        emergency_landing = bool(data.get("emergency_landing", False))

        course_deg, speed_knots = _vx_vy_to_course_speed(vx, vy)
        lat_nmea, lat_dir = _decimal_to_nmea_lat(lat)
        lon_nmea, lon_dir = _decimal_to_nmea_lon(lon)

        now = datetime.now(timezone.utc)
        time_str = now.strftime("%H%M%S.000")
        date_str = now.strftime("%d%m%y")

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
                    "speed_knots": round(speed_knots, 2),
                    "course_degrees": round(course_deg, 1),
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
                "speed_vertical_ms": round(vz, 2),
            },
            "actions": {
                "drop": drop,
                "emergency_landing": emergency_landing,
            },
        }

    def _get_kafka_producer(self) -> Optional[KafkaProducer]:
        if self._kafka_producer is None and config.sitl_mode() != "mock":
            try:
                self._kafka_producer = KafkaProducer(
                    bootstrap_servers=config.sitl_kafka_servers(),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                )
            except Exception:
                pass
        return self._kafka_producer

    def _emit_sitl_command(self, command: Dict[str, Any]) -> None:
        """Публикует команду в SITL: Kafka (если не mock) и/или локальный топик."""
        sitl_msg = self._build_sitl_command(command)
        if config.sitl_mode() != "mock":
            prod = self._get_kafka_producer()
            if prod:
                try:
                    prod.send(config.sitl_kafka_commands_topic(), value=sitl_msg)
                    prod.flush()
                except Exception:
                    pass
        self.bus.publish(
            config.sitl_commands_topic(),
            {"source": "motors", "command": sitl_msg, "raw_target": command},
        )

