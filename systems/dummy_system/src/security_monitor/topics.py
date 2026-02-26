"""Топики и actions для SecurityMonitor в составе dummy_system."""


class ComponentTopics:
    SECURITY_MONITOR = "components.security_monitor"
    DUMMY_COMPONENT_A = "components.dummy_component_a"


class SecurityMonitorActions:
    PROXY_REQUEST = "proxy_request"
    PROXY_PUBLISH = "proxy_publish"
    SET_POLICY = "set_policy"
    REMOVE_POLICY = "remove_policy"
    CLEAR_POLICIES = "clear_policies"
    LIST_POLICIES = "list_policies"
