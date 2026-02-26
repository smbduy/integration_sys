"""
Точка входа: python -m components.security_monitor

Простой standalone-режим без подключения к брокеру.
"""
import os


def main():
    component_id = os.environ.get("COMPONENT_ID", "security_monitor_standalone")
    name = os.environ.get("COMPONENT_NAME", component_id.replace("_", " ").title())

    print(f"[{component_id}] Starting SecurityMonitorComponent in standalone mode (no broker)")
    print(f"[{component_id}] SecurityMonitorComponent '{name}' ready")
    print(f"[{component_id}] Note: to run with broker, include this component in a system")


if __name__ == "__main__":
    main()

