# Security Monitor Component

`SecurityMonitorComponent` — шлюз безопасности для проксирования запросов к целевым компонентам по policy-модели.

В архитектуре **остальные компоненты принимают запросы только от монитора** (проверка `sender`). Клиенты обращаются к монитору; монитор по политике проксирует запрос к целевому компоненту от своего имени.

По умолчанию монитор работает в режиме **deny-all**: если политика не задана, доступ запрещен.

## Quick Start

1. Скопируйте шаблон env:

```bash
cp components/security_monitor/.env.example components/security_monitor/.env
```

2. Укажите admin sender и стартовые политики в `.env`:

- `POLICY_ADMIN_SENDER=security_monitor_admin`
- `SECURITY_POLICIES=` (пусто = deny-all)

3. В составе системы поднимите сервисы:

```bash
cd systems/dummy_system
make prepare
make docker-up
```

4. Базовая проверка логики:

- `proxy_request` без policy -> `None` (запрещено)
- `set_policy` от `POLICY_ADMIN_SENDER` -> `updated: true`
- `proxy_request` после `set_policy` -> разрешено

## Переменные окружения

- `COMPONENT_ID` — идентификатор компонента (по умолчанию `security_monitor_standalone` в standalone entrypoint).
- `POLICY_ADMIN_SENDER` — sender, которому разрешено менять политики (`set/remove/clear`).
- `SECURITY_POLICIES` — стартовые политики.

Для быстрого старта используйте `components/security_monitor/.env.example`
и скопируйте его в `.env`.

### Формат `SECURITY_POLICIES`

Поддерживаются два формата:

1. JSON-список:

```json
[{"sender":"client_a","topic":"components.dummy_component_a","action":"echo"}]
```

2. Строка с `;` и `,`:

```text
client_a,components.dummy_component_a,echo;client_a,components.dummy_component_a,increment
```

## Поддерживаемые actions

- `proxy_request` — request/response прокси на целевой топик.
- `proxy_publish` — fire-and-forget publish на целевой топик.
- `set_policy` — добавить разрешение (только `POLICY_ADMIN_SENDER`).
- `remove_policy` — удалить разрешение (только `POLICY_ADMIN_SENDER`).
- `clear_policies` — очистить все разрешения (только `POLICY_ADMIN_SENDER`).
- `list_policies` — вернуть текущие политики.

## Формат proxy-запроса

```json
{
  "action": "proxy_request",
  "sender": "client_a",
  "payload": {
    "target": {
      "topic": "components.dummy_component_a",
      "action": "echo"
    },
    "data": {
      "message": "hello"
    }
  }
}
```

Разрешение проверяется по тройке:

`(sender, target.topic, target.action)`

## Формат policy-операций

### Добавить policy

```json
{
  "action": "set_policy",
  "sender": "security_monitor_admin",
  "payload": {
    "sender": "client_a",
    "topic": "components.dummy_component_a",
    "action": "echo"
  }
}
```

### Удалить policy

```json
{
  "action": "remove_policy",
  "sender": "security_monitor_admin",
  "payload": {
    "sender": "client_a",
    "topic": "components.dummy_component_a",
    "action": "echo"
  }
}
```

### Очистить все policy

```json
{
  "action": "clear_policies",
  "sender": "security_monitor_admin",
  "payload": {}
}
```

### Посмотреть policy

```json
{
  "action": "list_policies",
  "sender": "any_sender",
  "payload": {}
}
```

## Запуск

### Standalone (без брокера)

```bash
python -m components.security_monitor
```

### В составе системы (через broker)

Используйте версию в `systems/<system>/src/security_monitor` и передавайте переменные:

- `COMPONENT_ID`
- `POLICY_ADMIN_SENDER`
- `SECURITY_POLICIES`
- параметры подключения к broker (`BROKER_TYPE`, `MQTT_*` / `KAFKA_*`, `BROKER_USER`, `BROKER_PASSWORD`)

---

## Роль монитора безопасности в агродроне

В системе агродрона `SecurityMonitorComponent` выступает как **доверительная вычислительная база (TCB)**:

- все бизнес‑запросы между компонентами должны проходить **только через монитор**;
- остальные компоненты принимают бизнес‑действия только от `sender`, начинающихся с `security_monitor` (см. `components/README.MD`);
- монитор реализует:
  - политику доступа между компонентами;
  - режимы изоляции (напр. по команде из компонента `emergensy`);
  - аудит ключевых событий безопасности.

### Политика доступа

- Базовый принцип — **deny‑all**: если явной policy нет, запрос запрещён.
- Единица политики — тройка:

  ```json
  {
    "sender": "components.emergensy",
    "topic": "components.motors",
    "action": "LAND"
  }
  ```

- Только `POLICY_ADMIN_SENDER` может изменять политики (`set/remove/clear`).
- Клиенты отправляют свои запросы в монитор, используя actions `proxy_request` и `proxy_publish`.
- Монитор проверяет `(sender, target.topic, target.action)` и:
  - при успехе публикует запрос на `target.topic` от имени `security_monitor`;
  - при отказе возвращает `None`/ошибку и пишет событие в журнал.

### Тематическое пространство для агродрона

Рекомендуемые топики:

- `agrodron.security_monitor.proxy` — вход для `proxy_request` / `proxy_publish`;
- `agrodron.security_monitor.control` — управление политиками и режимами (в т.ч. `ISOLATION_START`);
- `agrodron.security_monitor.event` — события безопасности и изоляции.

Примеры:

```json
{
  "action": "proxy_request",
  "sender": "ground_station",
  "payload": {
    "target": {
      "topic": "components.autopilot",
      "action": "CMD"
    },
    "data": {
      "command": "START",
      "mission_id": "mission-1"
    }
  }
}
```

```json
{
  "action": "ISOLATION_START",
  "sender": "components.emergensy",
  "payload": {
    "reason": "LIMITER_EMERGENCY",
    "mission_id": "mission-1"
  }
}
```

При `ISOLATION_START` монитор может перевести систему в режим, где:

- блокируются все новые `proxy_request`/`proxy_publish` для «опасных» целей;
- разрешаются только команды, необходимые для безопасной посадки/завершения полёта.

Событие изоляции публикуется в `agrodron.security_monitor.event`:

```json
{
  "timestamp": "2026-03-10T12:00:00Z",
  "event": "ISOLATION_STARTED",
  "reason": "LIMITER_EMERGENCY",
  "initiator": "components.emergensy"
}
```

### Протокол изоляции (аварийный набор политик)

При активации изоляции (`ISOLATION_START`) монитор:

1. **Стирает все текущие политики** (внутренний `clear_policies`).
2. **Загружает фиксированный аварийный набор политик**, который:
   - разрешает только взаимодействия, необходимые для безопасной посадки;
   - полностью запрещает любое прямое общение с `emergensy`, приводами и опрыскивателем (кроме через монитор).

Рекомендуемый аварийный набор политик (JSON‑список для `SECURITY_POLICIES` или `set_policy`):

```json
[
  {
    "sender": "components.emergensy",
    "topic": "components.navigation",
    "action": "GET_LAST_STATE"
  },
  {
    "sender": "components.emergensy",
    "topic": "components.motors",
    "action": "LAND"
  },
  {
    "sender": "components.emergensy",
    "topic": "components.sprayer",
    "action": "SET_SPRAY"
  },
  {
    "sender": "components.emergensy",
    "topic": "components.journal",
    "action": "LOG_EVENT"
  },
  {
    "sender": "components.emergensy",
    "topic": "components.security_monitor",
    "action": "ISOLATION_STATUS"
  }
]
```

Свойства этого набора:

- **Только `components.emergensy`** имеет право:
  - запросить у навигации последнюю позицию (`GET_LAST_STATE`);
  - отдать команду посадки приводам (`LAND`);
  - выключить распыление (`SET_SPRAY`);
  - зафиксировать события в журнале (`LOG_EVENT`);
  - при необходимости общаться с самим монитором (`ISOLATION_STATUS`).
- **Ни один другой `sender`** не имеет прав доступа к `components.emergensy`, `components.motors`, `components.sprayer`:
  - в аварийном режиме никто не может «самостоятельно» командовать приводами, опрыскивателем или `emergensy`;
  - любые попытки будут отклонены из‑за отсутствия policy.

Выход из режима изоляции (например, `ISOLATION_STOP` от администратора) может быть реализован как:

- восстановление предыдущего набора политик из устойчивого хранилища;
- или полный перезапуск монитора с базовым конфигом `SECURITY_POLICIES`.
