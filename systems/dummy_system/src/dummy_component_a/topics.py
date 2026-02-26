"""Топики и actions для DummyComponent в составе dummy_system."""


class ComponentTopics:
    DUMMY_COMPONENT_A = "components.dummy_component_a"

    @classmethod
    def all(cls) -> list:
        return [cls.DUMMY_COMPONENT_A]


class DummyComponentActions:
    ECHO = "echo"
    INCREMENT = "increment"
    GET_STATE = "get_state"
