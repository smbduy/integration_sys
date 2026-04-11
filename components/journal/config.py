"""Конфигурация компонента journal.

Чтение SYSTEM_NAME, топиков и параметров через переменные окружения.
"""
import os

from sdk.topic_utils import topic_for, system_name


def component_topic() -> str:
    return (os.environ.get("COMPONENT_TOPIC") or topic_for("journal")).strip()


def security_monitor_topic() -> str:
    return (os.environ.get("SECURITY_MONITOR_TOPIC") or topic_for("security_monitor")).strip()


def journal_file_path() -> str:
    return (os.environ.get("JOURNAL_FILE_PATH") or "/data/agrodron_journal.ndjson").strip()
