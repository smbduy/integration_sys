# Quick Start

Брокер (Kafka/MQTT) + SDK. Шаблоны: `components/dummy_component`, `systems/dummy_system`.

## Структура

```
broker/              SystemBus, MQTTSystemBus, KafkaSystemBus
sdk/                 BaseComponent, topic_utils
components/          Standalone-компоненты
agrodron/            Система AgroDron (10 компонентов)
docker/              Брокер (kafka, mosquitto)
scripts/             prepare_system.py
config/              Pipfile, pyproject.toml
docs/                Документация (SYSTEM.md, EXTERNAL_API.md)
```

## Команды (из корня репозитория)

```bash
make init          # pipenv + зависимости
make unit-test     # Unit тесты
make docker-up     # Брокер (kafka/mqtt)
make docker-down
```

## AgroDron

```bash
cd agrodron
make prepare       # Собрать .generated/
make test          # Unit + integration тесты
make docker-up     # Брокер + все компоненты
make docker-ps     # Статус контейнеров
make docker-logs   # Логи
make docker-down   # Остановить
```

## Протокол сообщений

Все сообщения — JSON с полями: `action`, `payload`, `sender`, `correlation_id`, `reply_to`.

- **Топики**: `v1.{SystemName}.{InstanceID}.{component}` (например `v1.Agrodron.Agrodron001.autopilot`)
- **sender**: полный топик отправителя (не короткое имя)
- **action**: всегда lowercase (`get_state`, `set_target`, `log_event`)

## Правило доступа компонентов

Все компоненты (кроме МБ) принимают запросы **только от монитора безопасности**. Сообщения от любого другого sender игнорируются. МБ проксирует запросы от своего топика, поэтому целевой компонент видит `sender = v1.Agrodron.Agrodron001.security_monitor`.

Поток:

1. Клиент отправляет `proxy_request` / `proxy_publish` на топик security_monitor
2. МБ проверяет политику `(sender, topic, action)`
3. МБ проксирует сообщение к целевому компоненту от своего sender
4. Целевой компонент проверяет sender и обрабатывает запрос

## Docker

```bash
cp docker/example.env docker/.env
# BROKER_TYPE=kafka или mqtt
make docker-up
```

| Переменная | Описание |
|---|---|
| BROKER_TYPE | kafka / mqtt |
| ADMIN_USER, ADMIN_PASSWORD | Админ брокера |
| TOPIC_VERSION, SYSTEM_NAME, INSTANCE_ID | Параметры формирования топиков |

## Документация

- [docs/SYSTEM.md](SYSTEM.md) — полная документация системы AgroDron
- [docs/EXTERNAL_API.md](EXTERNAL_API.md) — API для внешних систем (НУС, ОРВД, Дронопорт, SITL)
