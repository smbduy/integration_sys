"""Топики и actions для компонента ограничителя."""


class ComponentTopics:
    LIMITER = "components.limiter"


class LimiterActions:
    MISSION_LOAD = "mission_load"
    NAV_STATE = "nav_state"
    TELEMETRY_STATE = "telemetry_state"
    UPDATE_CONFIG = "update_config"
    GET_STATE = "get_state"
    EVENT = "event"

