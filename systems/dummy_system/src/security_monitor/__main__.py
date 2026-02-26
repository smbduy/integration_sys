"""Точка входа для security_monitor в составе dummy_system."""
import os
import sys
import signal
import time

from broker.bus_factory import create_system_bus
from systems.dummy_system.src.security_monitor.src.security_monitor import SecurityMonitorComponent
from systems.dummy_system.src.security_monitor.topics import ComponentTopics


def main():
    component_id = os.environ.get("COMPONENT_ID", "security_monitor")

    bus = create_system_bus(client_id=component_id)
    component = SecurityMonitorComponent(
        component_id=component_id,
        bus=bus,
        topic=ComponentTopics.SECURITY_MONITOR,
    )
    component.start()

    print(f"[{component_id}] Running. Press Ctrl+C to stop.")

    def signal_handler(sig, frame):
        print(f"\n[{component_id}] Received signal {sig}, shutting down...")
        component.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while component._running:
            signal.pause()
    except AttributeError:
        while component._running:
            time.sleep(1)


if __name__ == "__main__":
    main()
