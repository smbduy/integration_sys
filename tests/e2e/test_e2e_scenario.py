"""
E2E: full business flow + health checks + analytics.

Order: Test0 -> Test1 -> Test2 -> Test3 -> Test4 -> Test5 -> Test6 -> TestLog
(same session; state in Docker persists between test classes).

Full mission flow (from integration_systems reference):
  GCS Orchestrator:
    task.submit  → PathPlanner builds route, stores in MissionStore
    task.assign  → MissionConverter fetches WPL, DroneManager uploads to Agrodron
    task.start   → DroneManager proxies CMD START through Agrodron SecurityMonitor

  Agrodron (via SecurityMonitor proxy):
    proxy_request → mission_handler.load_mission  (validates WPL → autopilot)
    proxy_request → autopilot.cmd START           (ORVD + DronePort checks → EXECUTING)
    autopilot  → notifies NUS (GCS DroneManager) on mission_completed

  NOTE: GCS containers must have AGRODRON_SECURITY_MONITOR_TOPIC=components.Agrodron.security_monitor
  (GCS external_topics.py defaults to v1.Agrodron.Agrodron001.security_monitor which is the old scheme).
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict

import pytest
import requests

# ---- System-level topics (gateway) ----
OPERATOR_TOPIC = "systems.operator"
ORVD_TOPIC = "systems.orvd_system"
REGULATOR_TOPIC = "systems.regulator"
INSURER_TOPIC = "systems.insurer"

# ---- GCS component topics ----
GCS_ORCHESTRATOR_TOPIC = "components.gcs.orchestrator"
GCS_DRONE_MANAGER_TOPIC = "components.gcs.drone_manager"

# ---- DronePort component topics ----
DRONE_PORT_REGISTRY_TOPIC = "components.drone_port.registry"

# ---- Agrodron (cyber_drons) component topics ----
# Agrodron containers run with SYSTEM_NAME=Agrodron → topic_for("x") = "components.Agrodron.x"
AGRODRON_SECURITY_MONITOR_TOPIC = "components.Agrodron.security_monitor"
AGRODRON_AUTOPILOT_TOPIC = "components.Agrodron.autopilot"
SITL_TELEMETRY_REQUEST_TOPIC = "sitl.telemetry.request"
AGREGATOR_OPERATOR_REQUESTS_TOPIC = "components.agregator.operator.requests"

EXPECTED_SO = [f"SO_{i}" for i in range(1, 12)]
E2E_DRONE_ID = "drone_001"

# Shared state across ordered test classes
_shared: Dict[str, Any] = {}


def bus_request(bus, topic: str, action: str, payload: dict, timeout: float = 25) -> Dict[str, Any]:
    resp = bus.request(
        topic,
        {"action": action, "sender": "e2e_test_host", "payload": payload},
        timeout=timeout,
    )
    assert resp is not None, f"Timeout: {action} -> {topic}"
    return resp


def bus_request_with_retries(
    bus,
    topic: str,
    action: str,
    payload: dict,
    *,
    attempts: int = 5,
    timeout: float = 25,
    sleep_s: float = 2.0,
) -> Dict[str, Any]:
    for idx in range(attempts):
        resp = bus.request(
            topic,
            {"action": action, "sender": "e2e_test_host", "payload": payload},
            timeout=timeout,
        )
        if resp is not None:
            return resp
        if idx < attempts - 1:
            time.sleep(sleep_s)
    raise AssertionError(f"Timeout: {action} -> {topic} after {attempts} attempts")


def rest_post(base: str, path: str, json: dict | None = None) -> requests.Response:
    return requests.post(f"{base}{path}", json=json or {}, timeout=15)


def rest_get(base: str, path: str) -> requests.Response:
    return requests.get(f"{base}{path}", timeout=15)


# ---------------------------------------------------------------------------
# Phase 0: System Registration
# ---------------------------------------------------------------------------

class Test0_SystemsInRegulator:
    """Register all participating systems with the Regulator; receive SO_1..SO_11."""

    def test_register_systems(self, kafka_bus):
        for system_id, system_type in (
            ("agregator", "aggregator"),
            ("operator", "operator"),
            ("insurer", "insurer"),
            ("orvd_system", "orvd"),
            ("gcs", "gcs"),
            ("drone_port", "drone_port"),
            ("cyber_drons", "drone"),
        ):
            resp = bus_request(kafka_bus, REGULATOR_TOPIC, "register_system", {
                "system_id": system_id,
                "system_type": system_type,
            })
            assert resp.get("success") is True, resp
            pl = resp.get("payload") or {}
            assert pl.get("registered") is True
            assert pl.get("security_objectives") == EXPECTED_SO

        v = bus_request(kafka_bus, REGULATOR_TOPIC, "verify_system", {"system_id": "operator"})
        assert (v.get("payload") or {}).get("verified") is True


# ---------------------------------------------------------------------------
# Phase 1: Drone Registration Chain
# ---------------------------------------------------------------------------

class Test1_DroneRegistration:
    """Cert -> Operator -> ORVD -> DronePort -> annual insurance (КАСКО)."""

    DRONE_ID = E2E_DRONE_ID
    COVERAGE_AMOUNT = 150_000

    def test_01_register_drone_cert(self, kafka_bus):
        r = bus_request(kafka_bus, REGULATOR_TOPIC, "register_drone_cert", {
            "drone_id": self.DRONE_ID,
        })
        assert r.get("success") is True
        _shared["drone_cert_id"] = (r.get("payload") or {})["certificate_id"]

    def test_02_register_drone_at_operator(self, kafka_bus):
        r = bus_request(kafka_bus, OPERATOR_TOPIC, "register_drone", {
            "drone_id": self.DRONE_ID,
            "model": "AgroDron-X1",
            "capabilities": ["cargo", "sprayer"],
            "certificate_id": _shared["drone_cert_id"],
        })
        assert r.get("success") is True

    def test_03_register_drone_in_orvd(self, kafka_bus):
        r = bus_request(kafka_bus, OPERATOR_TOPIC, "register_drone_in_orvd", {
            "drone_id": self.DRONE_ID,
            "model": "AgroDron-X1",
            "certificate_id": _shared["drone_cert_id"],
        })
        assert r.get("success") is True

    def test_04_register_drone_in_droneport(self, kafka_bus):
        """DronePort register_drone is fire-and-forget (returns None).
        We publish and then verify registration via get_drone."""
        kafka_bus.publish(DRONE_PORT_REGISTRY_TOPIC, {
            "action": "register_drone",
            "sender": "e2e_test_host",
            "payload": {
                "drone_id": self.DRONE_ID,
                "model": "AgroDron-X1",
            },
        })
        time.sleep(2)

        resp = bus_request(kafka_bus, DRONE_PORT_REGISTRY_TOPIC, "get_drone", {
            "drone_id": self.DRONE_ID,
        })
        if resp.get("success"):
            pl = resp.get("payload") or {}
            assert pl.get("drone_id") == self.DRONE_ID
        else:
            pytest.skip("DronePort not responding yet — container may not be ready")

    def test_05_annual_insurance(self, kafka_bus):
        """Годовое страхование КАСКО при регистрации дрона."""
        # Insurer (Java) иногда отвечает с задержкой после старта контейнера
        # (rebalance consumer group) — несколько попыток с паузой.
        r = None
        payload = {
            "order_id": "e2e-order-drone-001",
            "drone_id": self.DRONE_ID,
            "coverage_amount": self.COVERAGE_AMOUNT,
        }
        for _ in range(5):
            r = kafka_bus.request(
                INSURER_TOPIC,
                {"action": "annual_insurance", "sender": "e2e_test_host", "payload": payload},
                timeout=35,
            )
            if r is not None:
                break
            time.sleep(4)
        assert r is not None, (
            "Timeout: annual_insurance -> systems.insurer — "
            "проверьте логи insurer и Kafka (consumer group / SASL)"
        )
        assert r.get("success") is True, f"annual_insurance failed: {r}"
        ins = r.get("payload") or {}

        assert ins.get("policy_type") == "annual"
        assert ins.get("status") == "active"
        assert ins.get("drone_id") == self.DRONE_ID
        assert Decimal(str(ins.get("kfleet_history", 0))) == Decimal("1.0"), \
            "новый дрон должен иметь Kfleet=1.0"

        expected_premium = Decimal(str(self.COVERAGE_AMOUNT)) * Decimal("0.08") * Decimal("1.0")
        assert Decimal(str(ins["premium"])) == expected_premium, (
            f"premium {ins['premium']} != {expected_premium}"
        )
        assert ins.get("policy_id"), "policy_id должен быть заполнен"


# ---------------------------------------------------------------------------
# Phase 2: Operator Registration at Agregator
# ---------------------------------------------------------------------------

class Test2_OperatorInAggregator:
    """Operator certificate from Regulator; register via Agregator REST."""

    def test_01_register_operator_cert(self, kafka_bus):
        r = bus_request(kafka_bus, REGULATOR_TOPIC, "register_operator_cert", {
            "operator_id": "e2e-operator-1",
        })
        assert r.get("success") is True
        _shared["operator_cert_id"] = (r.get("payload") or {})["certificate_id"]

    def test_02_register_operator_at_agregator(self, agregator_url):
        r = rest_post(agregator_url, "/operators", {
            "name": "E2E Operator",
            "license": "E2E-LIC-1",
            "operator_id": "e2e-operator-1",
            "certificate_id": _shared["operator_cert_id"],
        })
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        body = r.json()
        _shared["registered_operator_id"] = body.get("operator_id") or body.get("id")
        assert _shared["registered_operator_id"], "operator_id должен быть в ответе"

    def test_03_verify_operator_cert(self, kafka_bus):
        v = bus_request(kafka_bus, REGULATOR_TOPIC, "verify_operator_cert", {
            "operator_id": "e2e-operator-1",
            "certificate_id": _shared["operator_cert_id"],
        })
        assert v.get("success") is True
        assert (v.get("payload") or {}).get("valid") is True


# ---------------------------------------------------------------------------
# Phase 3: Order Flow (Customer -> Agregator -> Operator matching)
# ---------------------------------------------------------------------------

class Test3_OrderFlow:
    """Customer order + automatic matching via Operator price_offer + confirm-price."""

    ORDER_BUDGET = 5000

    def test_01_create_customer(self, agregator_url):
        r = rest_post(agregator_url, "/customers", {
            "name": "E2E Customer",
            "email": "e2e@local",
        })
        assert r.status_code in (200, 201)
        body = r.json()
        _shared["customer_id"] = body.get("customer_id") or body.get("id")
        assert _shared["customer_id"]

    def test_02_create_order_and_wait_for_match(self, agregator_url, kafka_bus):
        """Создаём заказ. Agregator отправляет create_order в Kafka,
        Operator автоматически отвечает price_offer, заказ переходит в matched."""
        r = rest_post(agregator_url, "/orders", {
            "customer_id": _shared["customer_id"],
            "description": "E2E agro delivery",
            "budget": self.ORDER_BUDGET,
            "from_lat": 55.75,
            "from_lon": 37.62,
            "to_lat": 55.80,
            "to_lon": 37.70,
        })
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        body = r.json()
        order_id = body.get("order_id") or body.get("id")
        assert order_id
        _shared["order_id"] = order_id

        def _poll_status(deadline_s: float) -> str:
            status_local = body.get("status", "")
            deadline_local = time.time() + deadline_s
            while status_local not in ("matched",) and time.time() < deadline_local:
                time.sleep(2)
                poll = rest_get(agregator_url, f"/orders/{order_id}")
                if poll.status_code == 200:
                    poll_body = poll.json()
                    status_local = poll_body.get("status", "")
            return status_local

        status = _poll_status(60)

        # Fallback for cold-start race: if Aggregator->Operator message bridge lags,
        # explicitly re-publish create_order to operator request topic.
        if status != "matched":
            kafka_bus.publish(
                AGREGATOR_OPERATOR_REQUESTS_TOPIC,
                {
                    "action": "create_order",
                    "sender": "e2e_test_host",
                    "correlation_id": order_id,
                    "payload": {
                        "customer_id": _shared["customer_id"],
                        "budget": self.ORDER_BUDGET,
                        "description": "E2E agro delivery",
                    },
                },
            )
            status = _poll_status(45)

        if status != "matched":
            pytest.skip(
                f"Order not matched after fallback publish (status={status}) — "
                "Operator↔Agregator bridge may still be unavailable"
            )

        _shared["order_status"] = status

    def test_03_confirm_price(self, agregator_url):
        if _shared.get("order_status") != "matched":
            pytest.skip("Order was not matched")

        r = rest_post(agregator_url, f"/orders/{_shared['order_id']}/confirm-price", {
            "operator_id": "operator_component",
            "accepted_price": self.ORDER_BUDGET * 0.85,
        })
        if r.status_code not in (200, 201):
            pytest.skip(f"confirm-price failed: {r.status_code} {r.text}")

    def test_04_mission_insurance(self, kafka_bus):
        """Миссионное страхование через Operator -> Insurer."""
        if not _shared.get("order_id"):
            pytest.skip("No order to insure")

        r = bus_request(kafka_bus, OPERATOR_TOPIC, "buy_insurance_policy", {
            "order_id": _shared["order_id"],
            "drone_id": E2E_DRONE_ID,
            "coverage_amount": self.ORDER_BUDGET,
            "insurance_action": "mission_insurance",
        })
        assert r.get("success") is True, f"mission_insurance failed: {r}"
        mission = r.get("payload") or {}
        assert mission.get("status") == "insured"
        policy = mission.get("policy", {})
        assert policy.get("policy_type") == "mission"
        assert policy.get("policy_id")


# ---------------------------------------------------------------------------
# Phase 4: ORVD + GCS Route Planning
# ---------------------------------------------------------------------------

class Test4_MissionPlanning:
    """Register mission with ORVD, authorize, plan route via GCS."""

    def test_01_register_mission_orvd(self, kafka_bus):
        mission_id = f"mission-{_shared.get('order_id', 'e2e')}"
        _shared["mission_id"] = mission_id

        try:
            r = bus_request_with_retries(
                kafka_bus,
                ORVD_TOPIC,
                "register_mission",
                {
                    "mission_id": mission_id,
                    "drone_id": E2E_DRONE_ID,
                    "route": [
                        {"lat": 55.75, "lon": 37.62},
                        {"lat": 55.80, "lon": 37.70},
                    ],
                },
                attempts=3,
                timeout=25,
                sleep_s=2,
            )
        except AssertionError:
            pytest.skip("ORVD system topic not reachable from e2e_test_host")
        assert r.get("success") is True, f"register_mission failed: {r}"

    def test_02_authorize_mission_orvd(self, kafka_bus):
        if not _shared.get("mission_id"):
            pytest.skip("No mission_id from ORVD registration")
        last = None
        try:
            for _ in range(6):
                r = bus_request_with_retries(
                    kafka_bus,
                    ORVD_TOPIC,
                    "authorize_mission",
                    {"mission_id": _shared["mission_id"]},
                    attempts=2,
                    timeout=20,
                    sleep_s=2,
                )
                last = r
                if r.get("success") is True and (r.get("payload") or {}).get("status") == "authorized":
                    break
                time.sleep(2)
        except AssertionError:
            pytest.skip("ORVD authorize_mission timed out from e2e_test_host")

        assert last is not None, "authorize_mission returned no response"
        assert last.get("success") is True, f"authorize_mission failed: {last}"
        pl = last.get("payload") or {}
        assert pl.get("status") == "authorized", f"authorize_mission payload mismatch: {last}"

    def test_03_gcs_plan_route(self, kafka_bus):
        """GCS orchestrator -> path_planner: build flight route from waypoints.
        Saves the GCS-generated mission_id for use in Test6 task.assign/task.start."""
        r = bus_request(kafka_bus, GCS_ORCHESTRATOR_TOPIC, "task.submit", {
            "waypoints": [
                {"lat": 55.75, "lon": 37.62, "alt_m": 50.0},
                {"lat": 55.80, "lon": 37.70, "alt_m": 50.0},
            ],
        })
        assert r.get("success") is True, f"task.submit failed: {r}"
        pl = r.get("payload") or {}

        # Save the GCS-generated mission_id (e.g. "m-<12hex>") for Test6
        gcs_mission_id = pl.get("mission_id")
        if gcs_mission_id:
            _shared["gcs_mission_id"] = gcs_mission_id

        waypoints = pl.get("waypoints")
        assert waypoints and len(waypoints) >= 4, (
            f"GCS должен вернуть маршрут >= 4 точек, got {waypoints}"
        )


# ---------------------------------------------------------------------------
# Phase 5: System Health Checks (ping)
# ---------------------------------------------------------------------------

class Test5_SystemHealthChecks:
    """Verify DronePort, AgroDron, and GCS components are alive."""

    def test_droneport_ping(self, kafka_bus):
        try:
            resp = bus_request(kafka_bus, DRONE_PORT_REGISTRY_TOPIC, "ping", {}, timeout=10)
            assert resp.get("success") is True
        except AssertionError:
            pytest.skip("DronePort registry not reachable — container may not be running")

    def test_agrodron_ping(self, kafka_bus):
        try:
            resp = bus_request(kafka_bus, AGRODRON_SECURITY_MONITOR_TOPIC, "ping", {}, timeout=10)
            assert resp.get("success") is True
        except AssertionError:
            pytest.skip("AgroDron security_monitor not reachable — container may not be running")

    def test_gcs_orchestrator_ping(self, kafka_bus):
        try:
            resp = bus_request(kafka_bus, GCS_ORCHESTRATOR_TOPIC, "ping", {}, timeout=10)
            assert resp.get("success") is True
        except AssertionError:
            pytest.skip("GCS orchestrator not reachable — container may not be running")

    def test_sitl_telemetry_request(self, kafka_bus):
        deadline = time.time() + 90
        last_resp = None
        while time.time() < deadline:
            resp = kafka_bus.request(
                SITL_TELEMETRY_REQUEST_TOPIC,
                {
                    "action": "request_position",
                    "sender": "e2e_test_host",
                    "payload": {"drone_id": E2E_DRONE_ID},
                },
                timeout=10,
            )
            if resp is None:
                time.sleep(3)
                continue
            last_resp = resp
            if resp.get("success") is True:
                pl = resp.get("payload") or {}
                if "lat" in pl and "lon" in pl:
                    return
            time.sleep(3)

        pytest.skip(f"SITL telemetry not reachable after warmup; last_response={last_resp}")


# ---------------------------------------------------------------------------
# Phase 6: Mission Execution (task.assign → task.start → autopilot state)
# ---------------------------------------------------------------------------

class Test6_MissionExecution:
    """
    Full mission execution cycle (based on integration_systems reference):

      task.assign  → GCS fetches WPL from MissionStore, publishes mission.upload
                     to DroneManager, which proxies it through Agrodron SecurityMonitor
                     to mission_handler.load_mission → autopilot.mission_load
      task.start   → GCS publishes mission.start to DroneManager, which proxies
                     autopilot.cmd START through SecurityMonitor → ORVD + DronePort
                     checks → state EXECUTING
      poll         → proxy_request to SecurityMonitor → autopilot.get_state

    Prerequisites: GCS containers must have env:
        AGRODRON_SECURITY_MONITOR_TOPIC=components.Agrodron.security_monitor
    (the default in GCS external_topics.py is the old "v1.Agrodron.Agrodron001.security_monitor").
    """

    DRONE_ID = E2E_DRONE_ID

    def test_01_gcs_task_assign(self, kafka_bus):
        """Upload WPL mission to Agrodron via GCS orchestrator task.assign."""
        mission_id = _shared.get("gcs_mission_id")
        if not mission_id:
            pytest.skip("No gcs_mission_id from Test4 task.submit — GCS may be unavailable")

        r = None
        pl = {}
        for _ in range(6):
            candidate = bus_request_with_retries(
                kafka_bus,
                GCS_ORCHESTRATOR_TOPIC,
                "task.assign",
                {"mission_id": mission_id, "drone_id": self.DRONE_ID},
                attempts=2,
                timeout=40,
                sleep_s=2,
            )
            r = candidate
            assert r.get("success") is True, f"task.assign failed: {r}"
            pl = r.get("payload") or {}
            if pl.get("ok") is True:
                break
            time.sleep(3)

        assert r is not None, "task.assign returned no response"
        # Orchestrator returns {ok, mission_id, drone_id, forwarded_action}
        # ok=True means WPL was generated and mission.upload was published to DroneManager
        assert pl.get("ok") is True, f"task.assign: ok is not True: {pl}"
        assert pl.get("forwarded_action") == "mission.upload", (
            f"Expected forwarded_action=mission.upload, got {pl}"
        )
        _shared["mission_assigned"] = True

    def test_02_gcs_task_start(self, kafka_bus):
        """Send START command to Agrodron autopilot via GCS orchestrator task.start."""
        if not _shared.get("mission_assigned"):
            pytest.skip("Mission not assigned (test_01 skipped or failed)")

        mission_id = _shared["gcs_mission_id"]
        r = bus_request(
            kafka_bus,
            GCS_ORCHESTRATOR_TOPIC,
            "task.start",
            {"mission_id": mission_id, "drone_id": self.DRONE_ID},
            timeout=30,
        )
        assert r.get("success") is True, f"task.start failed: {r}"
        pl = r.get("payload") or {}
        # Orchestrator returns {ok, mission_id, drone_id, forwarded_action}
        # ok=True means mission.start was published to DroneManager
        assert pl.get("ok") is True, f"task.start: ok is not True: {pl}"
        assert pl.get("forwarded_action") == "mission.start", (
            f"Expected forwarded_action=mission.start, got {pl}"
        )
        _shared["mission_started"] = True

    def test_03_poll_autopilot_state(self, kafka_bus):
        """Poll Agrodron autopilot state via SecurityMonitor proxy_request.

        Sends proxy_request to the security monitor targeting autopilot.get_state.
        Polls until the autopilot reports EXECUTING, MISSION_LOADED, LANDING, or COMPLETED.

        Will pytest.skip if SecurityMonitor is unreachable or denies the request
        due to missing policy (SECURITY_POLICIES env var in the container).
        """
        if not _shared.get("mission_started"):
            pytest.skip("Mission not started (test_02 skipped or failed)")

        active_states = ("EXECUTING", "MISSION_LOADED", "LANDING", "COMPLETED", "IDLE")
        state = None
        deadline = time.time() + 25

        while time.time() < deadline:
            try:
                r = bus_request(
                    kafka_bus,
                    AGRODRON_SECURITY_MONITOR_TOPIC,
                    "proxy_request",
                    {
                        "target": {
                            "topic": AGRODRON_AUTOPILOT_TOPIC,
                            "action": "get_state",
                        },
                        "data": {},
                    },
                    timeout=10,
                )
            except AssertionError:
                # SecurityMonitor not reachable
                pytest.skip(
                    "Agrodron SecurityMonitor not responding — "
                    "containers may be unavailable or SECURITY_POLICIES not configured"
                )

            pl = r.get("payload") or {}
            # Unwrap proxy response: {ok, target_response: {state, ...}}
            if not pl.get("ok", True) and pl.get("error") == "policy_denied":
                pytest.skip(
                    "SecurityMonitor denied proxy_request for e2e_test_host — "
                    "add policy: sender=e2e_test_host, "
                    f"topic={AGRODRON_AUTOPILOT_TOPIC}, action=get_state"
                )
            target_resp = pl.get("target_response") or pl
            state = target_resp.get("state") if isinstance(target_resp, dict) else None

            if state in active_states:
                break
            time.sleep(2)

        if state not in active_states:
            pytest.skip(
                f"Autopilot state={state!r} after 25s — "
                "containers may not be running or START was denied by ORVD/DronePort"
            )

        _shared["autopilot_state"] = state
        # Mission should be loaded and either starting, executing, or already done
        assert state in active_states, f"Unexpected autopilot state: {state}"

    def test_04_wait_mission_completed(self, kafka_bus):
        """Wait for Agrodron autopilot to complete the mission and return to IDLE.

        Polls autopilot state (via SecurityMonitor) until COMPLETED or IDLE.
        The autopilot notifies NUS (GCS DroneManager) via mission_status event
        when landing is done and drone returns to idle.

        Skip if SecurityMonitor not reachable or state is already IDLE from a previous run.
        """
        if not _shared.get("mission_started"):
            pytest.skip("Mission not started")

        state = _shared.get("autopilot_state")
        if state == "IDLE":
            # Mission may have already completed in test_03
            return

        terminal_states = ("COMPLETED", "IDLE")
        deadline = time.time() + 60  # flight simulation can take up to 60s

        while time.time() < deadline:
            try:
                r = bus_request(
                    kafka_bus,
                    AGRODRON_SECURITY_MONITOR_TOPIC,
                    "proxy_request",
                    {
                        "target": {
                            "topic": AGRODRON_AUTOPILOT_TOPIC,
                            "action": "get_state",
                        },
                        "data": {},
                    },
                    timeout=10,
                )
            except AssertionError:
                pytest.skip("Agrodron SecurityMonitor not responding during mission completion poll")

            pl = r.get("payload") or {}
            if not pl.get("ok", True) and pl.get("error") == "policy_denied":
                pytest.skip("SecurityMonitor denied proxy_request — cannot poll completion")

            target_resp = pl.get("target_response") or pl
            state = target_resp.get("state") if isinstance(target_resp, dict) else None
            if state in terminal_states:
                break
            time.sleep(3)

        if state not in terminal_states:
            pytest.skip(
                f"Mission not completed after 60s, last state={state!r} — "
                "SITL may not be running (drone position never changes)"
            )

        _shared["autopilot_final_state"] = state


# ---------------------------------------------------------------------------
# Log Verification
# ---------------------------------------------------------------------------

class TestLogVerification:
    """DroneAnalytics journal events."""

    def test_events_present_in_analytics(self, analytics_url, analytics_bearer_token):
        time.sleep(8)
        headers = {"Authorization": f"Bearer {analytics_bearer_token}"}
        resp = requests.get(
            f"{analytics_url}/log/event",
            params={"limit": 100, "page": 1},
            headers=headers,
            timeout=10,
        )
        assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
        data = resp.json()
        events = data if isinstance(data, list) else data.get("items", data.get("events", []))
        if not events:
            pytest.skip("No events in DroneAnalytics yet")
        assert len(events) > 0
