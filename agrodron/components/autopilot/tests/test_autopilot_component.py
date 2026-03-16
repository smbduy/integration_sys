import os

from components.bus_mock import MockSystemBus
from components.autopilot.src.autopilot import AutopilotComponent
from components.autopilot import config

SM_TOPIC = config.security_monitor_topic()


def _make_component() -> AutopilotComponent:
    bus = MockSystemBus()
    return AutopilotComponent(component_id="autopilot_test", bus=bus)


def test_mission_load_and_start():
    saved = {k: os.environ.pop(k, None) for k in ("ORVD_TOPIC", "DRONEPORT_TOPIC")}
    try:
        _run_mission_load_and_start()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _run_mission_load_and_start():
    comp = _make_component()

    mission = {"mission_id": "m1", "steps": []}
    msg = {
        "action": "mission_load",
        "sender": SM_TOPIC,
        "payload": {"mission": mission},
    }
    result = comp._handle_mission_load(msg)
    assert result and result["ok"]

    cmd_msg = {
        "action": "cmd",
        "sender": SM_TOPIC,
        "payload": {"command": "START"},
    }
    cmd_result = comp._handle_cmd(cmd_msg)
    assert cmd_result and cmd_result["ok"]
    state = comp._handle_get_state({"action": "get_state"})
    assert state["state"] == "EXECUTING"

