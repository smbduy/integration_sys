"""Топики и actions для компонента автопилота."""


class ComponentTopics:
    AUTOPILOT = "components.autopilot"


class AutopilotActions:
    MISSION_LOAD = "mission_load"
    CMD = "cmd"
    NAV_STATE = "nav_state"
    GET_STATE = "get_state"

