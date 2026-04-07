"""
Разбор ответа bus.request после цепочки proxy_request → security_monitor → целевой компонент.

В MQTT клиент получает полное сообщение (create_response): полезная нагрузка МБ лежит в
``payload.target_response``, а не в корне ``target_response``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def unwrap_proxy_target_response(response: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Возвращает внутренний dict ответа целевого компонента (target_response)."""
    if not isinstance(response, dict):
        return None
    outer = response.get("payload")
    if isinstance(outer, dict) and "target_response" in outer:
        tr = outer.get("target_response")
        return tr if isinstance(tr, dict) else None
    tr = response.get("target_response")
    return tr if isinstance(tr, dict) else None
