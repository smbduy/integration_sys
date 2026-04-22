"""Точка входа для gateway alt_insurer."""
import os

from broker.bus_factory import create_system_bus
from systems.alt_insurer.src.gateway.src.gateway import InsurerGateway


def main():
    system_id = os.environ.get("SYSTEM_ID", "alt_insurer")
    health_port = int(os.environ.get("HEALTH_PORT", "0")) or None

    bus = create_system_bus(client_id=system_id)
    gateway = InsurerGateway(system_id=system_id, bus=bus, health_port=health_port)
    gateway.run_forever()


if __name__ == "__main__":
    main()
