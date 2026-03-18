# API внешних систем

Формат топиков: `v1.{SystemName}.{InstanceID}.{component}`

Все сообщения передаются через брокер (MQTT/Kafka) в JSON-формате.
Структура сообщения:

```json
{
  "action": "<имя_действия>",
  "sender": "<полный_топик_отправителя>",
  "payload": { ... }
}
```

Поле `sender` всегда содержит полный топик отправителя (например, `v1.NUS.NUS001.main` или `v1.Agrodron.Agrodron001.security_monitor`). Все сообщения от дрона к внешним системам проходят через монитор безопасности, поэтому sender будет равен топику security_monitor.

---

## НУС (Наземная Управляющая Система)

**Топик**: `v1.NUS.NUS001.main` (переменная `NUS_TOPIC`)

### Действия НУС -> Дрон

#### load_mission

Загрузка миссии в mission_handler. Формат — WPL (QGC WPL 110).

Топик назначения: `v1.Agrodron.Agrodron001.mission_handler`

```json
{
  "action": "load_mission",
  "sender": "v1.NUS.NUS001.main",
  "payload": {
    "wpl_content": "QGC WPL 110\n0\t1\t0\t16\t0\t0\t0\t0\t60.0\t30.0\t5.0\t1",
    "mission_id": "mission-001"
  }
}
```

Ответ:

```json
{ "ok": true }
```

или

```json
{ "ok": false, "error": "wpl_parse_failed" }
```

#### validate_only

Проверка миссии без загрузки.

Топик назначения: `v1.Agrodron.Agrodron001.mission_handler`

```json
{
  "action": "validate_only",
  "sender": "v1.NUS.NUS001.main",
  "payload": {
    "wpl_content": "QGC WPL 110\n..."
  }
}
```

#### cmd (start)

Команда запуска выполнения загруженной миссии.

Топик назначения: `v1.Agrodron.Agrodron001.autopilot`

```json
{
  "action": "cmd",
  "sender": "v1.NUS.NUS001.main",
  "payload": {
    "command": "START"
  }
}
```

Ответ при успехе:

```json
{ "ok": true, "state": "EXECUTING" }
```

Ответ при отказе ОРВД:

```json
{ "ok": false, "error": "orvd_departure_denied" }
```

Ответ при отказе Дронопорта:

```json
{ "ok": false, "error": "droneport_departure_denied" }
```

### Действия Дрон -> НУС

#### mission_status

Уведомление о статусе миссии.

Топик назначения: `v1.NUS.NUS001.main`

```json
{
  "action": "mission_status",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {
    "event": "mission_completed",
    "mission_id": "mission-001"
  }
}
```

Возможные события:
- `mission_completed` — миссия завершена
- `mission_rejected` — миссия невозможна (ОРВД или Дронопорт отказали)

---

## ОРВД (Организация Воздушного Движения)

**Топик**: `v1.ORVD.ORVD001.main` (переменная `ORVD_TOPIC`)

### Действия Дрон -> ОРВД

#### request_takeoff

Запрос разрешения на взлёт.

```json
{
  "action": "request_takeoff",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {
    "drone_id": "Agrodron001",
    "mission_id": "mission-001",
    "time": "2026-03-18T12:00:00Z"
  }
}
```

Ожидаемый ответ:

```json
{ "status": "takeoff_authorized" }
```

или

```json
{ "status": "rejected", "reason": "airspace_restricted" }
```

### Действия ОРВД -> Дрон

#### load_mission / validate_only

ОРВД может также загружать миссии напрямую (топик `v1.Agrodron.Agrodron001.mission_handler`), аналогично НУС.

---

## Дронопорт

**Топик**: `v1.Droneport.DP001.main` (переменная `DRONEPORT_TOPIC`)

### Действия Дрон -> Дронопорт

#### request_departure

Запрос разрешения на вылет с площадки.

```json
{
  "action": "request_departure",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {
    "mission_id": "mission-001"
  }
}
```

Ожидаемый ответ:

```json
{ "approved": true }
```

#### request_landing

Запрос разрешения на посадку.

```json
{
  "action": "request_landing",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {}
}
```

Ожидаемый ответ:

```json
{ "approved": true }
```

#### request_maintenance

Запрос обслуживания после посадки.

```json
{
  "action": "request_maintenance",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {
    "diagnostics_ok": true,
    "component_id": "autopilot"
  }
}
```

---

## SITL (Симулятор / Цифровой двойник)

SITL использует **RAW-протокол**: сообщения **без** поля `action` и без обёртки `{action, sender, payload}`.

Reply/response делается через `reply_to` + `correlation_id`, которые добавляет клиент (в нашем случае — `SystemBus.request()` внутри security_monitor).

### Топики

- **Команды приводов**: `sitl.commands` (переменная `SITL_COMMANDS_TOPIC`)
- **Запрос навигации/телеметрии**: `sitl.telemetry.request` (переменная `SITL_TELEMETRY_REQUEST_TOPIC`)

### Действия Дрон -> SITL

#### Команды приводов (motors -> SITL)

Отправка команды управления (от компонента motors). RAW JSON по схеме SITL.

```json
{
  "drone_id": "drone_001",
  "vx": 1.5,
  "vy": 0.0,
  "vz": 0.0,
  "mag_heading": 90.0
}
```

#### set_home

Установка домашней точки (от mission_handler при загрузке миссии).

```json
{
  "action": "set_home",
  "sender": "v1.Agrodron.Agrodron001.security_monitor",
  "payload": {
    "drone_id": "drone_001",
    "derived": {
      "lat_decimal": 60.0,
      "lon_decimal": 30.0,
      "altitude_msl": 5.0,
      "gps_valid": true
    }
  }
}
```

### Действия SITL -> Дрон

#### Ответ на запрос телеметрии/навигации (SITL -> reply_to)

SITL отвечает в `reply_to` и повторяет `correlation_id` из запроса.

```json
{
  "correlation_id": "e2e4f10a-3a7d-4bdb-9b2f-4a3ad4a02d2c",
  "lat": 59.938623,
  "lon": 30.316534,
  "alt": 100.2
}
```

#### Запрос навигации/телеметрии (navigation -> SITL)

RAW request в `SITL_TELEMETRY_REQUEST_TOPIC`:

```json
{
  "drone_id": ["drone_001"]
}
```

---

## Последовательность выполнения миссии

```
НУС -> mission_handler : load_mission (WPL)
НУС -> autopilot       : cmd START
  autopilot -> ОРВД    : request_takeoff
  autopilot -> Дронопорт: request_departure
  [при отказе] autopilot -> НУС: mission_rejected
  [при успехе] autopilot выполняет миссию
  [по завершении]
    autopilot -> Дронопорт: request_landing
    autopilot -> motors: land (посадка)
    autopilot: self_diagnostics()
    autopilot -> Дронопорт: request_maintenance
    autopilot -> НУС: mission_completed
```
