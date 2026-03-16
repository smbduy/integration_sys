# Система AgroDron

## 1. Обзор

**AgroDron** — система управления сельскохозяйственным дроном. Все компоненты общаются исключительно через **монитор безопасности (МБ)** — прямой обмен между компонентами запрещён. МБ проверяет каждое сообщение по таблице политик `(sender, topic, action)` и проксирует разрешённые.

### Формат топиков

```
v1.{SystemName}.{InstanceID}.{component}
```

Пример: `v1.Agrodron.Agrodron001.autopilot`

Параметры задаются через переменные окружения: `TOPIC_VERSION`, `SYSTEM_NAME`, `INSTANCE_ID`.

### Формат сообщений

```json
{
  "action": "имя_действия",
  "sender": "полный_топик_отправителя",
  "payload": { },
  "correlation_id": "uuid (для request/response)",
  "reply_to": "топик_для_ответа (для request/response)"
}
```

Поле `sender` содержит полный топик отправителя, например `v1.Agrodron.Agrodron001.autopilot`. Все действия — **lowercase**.

---

## 2. Компоненты

| Компонент | Топик | Назначение |
|---|---|---|
| security_monitor | `…security_monitor` | Шлюз безопасности: проксирует запросы по политикам |
| autopilot | `…autopilot` | Хранение миссии, расчёт управления, взаимодействие с ОРВД/Дронопорт/НУС |
| mission_handler | `…mission_handler` | Загрузка WPL-миссий, валидация, передача в autopilot |
| navigation | `…navigation` | Получение навигации от SITL, нормализация, выдача по запросу |
| motors | `…motors` | Приводы: приём set_target/land, публикация команд в SITL |
| sprayer | `…sprayer` | Опрыскиватель: set_spray, учёт состояния |
| limiter | `…limiter` | Контроль отклонений от маршрута, вызов emergensy при срабатывании |
| emergensy | `…emergensy` | Аварийный протокол: land, закрытие sprayer, изоляция |
| telemetry | `…telemetry` | Агрегация состояния motors, sprayer и navigation |
| journal | `…journal` | Логирование событий в NDJSON-файл |

### Внешние системы

| Система | Топик (по умолчанию) | Переменная |
|---|---|---|
| НУС (наземная управляющая) | `v1.NUS.NUS001.main` | `NUS_TOPIC` |
| ОРВД (воздушное движение) | `v1.ORVD.ORVD001.main` | `ORVD_TOPIC` |
| Дронопорт | `v1.Droneport.DP001.main` | `DRONEPORT_TOPIC` |
| SITL (симулятор) | `v1.SITL.SITL001.main` | `SITL_TOPIC` |

---

## 3. Монитор безопасности (МБ)

Топик: `v1.Agrodron.Agrodron001.security_monitor`

МБ — единственный компонент, через который проходят все межкомпонентные сообщения. Остальные компоненты принимают сообщения **только** от МБ (проверка `sender == topic security_monitor`).

### Действия МБ

| Action | Тип | Описание |
|---|---|---|
| `proxy_request` | RPC | Проксирование запроса к целевому компоненту с ожиданием ответа |
| `proxy_publish` | fire-and-forget | Проксирование сообщения к целевому компоненту без ответа |
| `set_policy` | admin | Добавить политику (только `POLICY_ADMIN_SENDER`) |
| `remove_policy` | admin | Удалить политику |
| `clear_policies` | admin | Сброс всех политик |
| `list_policies` | admin | Список текущих политик |
| `isolation_start` | emergency | Режим изоляции (аварийный набор политик) |
| `isolation_status` | query | Текущий статус изоляции |

### proxy_request

```json
{
  "action": "proxy_request",
  "sender": "v1.Agrodron.Agrodron001.autopilot",
  "payload": {
    "target": {
      "topic": "v1.Agrodron.Agrodron001.navigation",
      "action": "get_state"
    },
    "data": {}
  }
}
```

Ответ:

```json
{
  "target_topic": "v1.Agrodron.Agrodron001.navigation",
  "target_action": "get_state",
  "target_response": { "nav_state": { "lat": 60.0, "lon": 30.0, "alt_m": 5.0, "..." : "..." } }
}
```

### proxy_publish

```json
{
  "action": "proxy_publish",
  "sender": "v1.Agrodron.Agrodron001.autopilot",
  "payload": {
    "target": {
      "topic": "v1.Agrodron.Agrodron001.motors",
      "action": "set_target"
    },
    "data": { "vx": 0.5, "vy": 0.3, "vz": 0.0 }
  }
}
```

---

## 4. API компонентов

Все запросы к компонентам доставляет МБ. Компонент получает сообщение с `sender` = топик security_monitor.

### 4.1. autopilot

| Action | Описание |
|---|---|
| `mission_load` | Загрузить миссию (от mission_handler) |
| `cmd` | Команда управления: `START`, `PAUSE`, `RESUME`, `ABORT` |
| `get_state` | Текущее состояние автопилота |

`cmd` с `command: "START"` запускает последовательность:
1. Запрос `request_departure` к ОРВД
2. Запрос `request_departure` к Дронопорту
3. При отказе — уведомление `mission_rejected` в НУС
4. При успехе — выполнение миссии
5. По завершении — `request_landing`, самодиагностика, `request_maintenance`, уведомление `mission_completed` в НУС

### 4.2. mission_handler

| Action | Описание |
|---|---|
| `load_mission` | Загрузить миссию в формате WPL (QGC WPL 110) |
| `validate_only` | Валидация WPL без загрузки |
| `get_state` | Текущее состояние обработчика |

Payload `load_mission`:

```json
{
  "wpl_content": "QGC WPL 110\n0\t1\t0\t16\t0\t0\t0\t0\t60.0\t30.0\t5.0\t1",
  "mission_id": "mission-001"
}
```

При успешной загрузке mission_handler автоматически передаёт миссию в autopilot (`mission_load`) и limiter (`mission_load`), а также отправляет `set_home` в SITL.

### 4.3. navigation

| Action | Описание |
|---|---|
| `get_state` | Текущее навигационное состояние (NAV_STATE) |
| `nav_state` | Обновить навигационное состояние |
| `update_config` | Обновить конфигурацию (drone_id и т.п.) |

navigation периодически опрашивает SITL через `get_nav_state` и хранит актуальное состояние.

### 4.4. motors

| Action | Описание |
|---|---|
| `set_target` | Целевой вектор скорости (vx, vy, vz) или heading/speed |
| `land` | Аварийная посадка |
| `get_state` | Текущее состояние приводов (mode, last_target, temperature) |

При получении `set_target` или `land` motors отправляет команду `command` в SITL.

### 4.5. sprayer

| Action | Описание |
|---|---|
| `set_spray` | Вкл/выкл опрыскивание (`payload: { "spray": true }`) |
| `get_state` | Текущее состояние (state, temperature, tank_level) |

### 4.6. limiter

| Action | Описание |
|---|---|
| `mission_load` | Синхронизация миссии с autopilot |
| `nav_state` | Обновление навигации для проверки отклонений |
| `update_config` | Обновление лимитов (max_distance, max_alt_deviation) |
| `get_state` | Текущее состояние (state, violations) |

limiter периодически опрашивает navigation и telemetry. При критическом отклонении от маршрута отправляет `limiter_event` в emergensy.

### 4.7. emergensy

| Action | Описание |
|---|---|
| `limiter_event` | Событие от limiter (авария) |
| `get_state` | Текущее состояние (active) |

При получении `limiter_event` emergensy запускает аварийный протокол:
1. `isolation_start` в security_monitor (переключение на аварийные политики)
2. `set_spray: false` в sprayer (закрытие распыления)
3. `land` в motors (посадка)
4. `log_event` в journal (логирование)

### 4.8. telemetry

| Action | Описание |
|---|---|
| `get_state` | Агрегат состояния motors + sprayer + navigation |

telemetry периодически опрашивает motors, sprayer и navigation, кэширует результаты и отдаёт по запросу.

### 4.9. journal

| Action | Описание |
|---|---|
| `log_event` | Записать событие в NDJSON-файл |

Payload:

```json
{
  "event": "MISSION_STARTED",
  "source": "autopilot",
  "mission_id": "mission-001",
  "details": {}
}
```

---

## 5. Политики безопасности

Политики задаются JSON-массивом в переменной `SECURITY_POLICIES`. Каждая запись — тройка `(sender, topic, action)`, где sender и topic — **полные топики**.

В `.env` используются подстановки: `${SYSTEM_NAME}` раскрывается в `v1.{SystemName}.{InstanceID}`, а `${NUS_TOPIC}`, `${ORVD_TOPIC}` и т.д. — в соответствующие топики внешних систем.

Пример записи:

```json
{"sender": "${SYSTEM_NAME}.autopilot", "topic": "${SYSTEM_NAME}.navigation", "action": "get_state"}
```

Раскрывается в:

```json
{"sender": "v1.Agrodron.Agrodron001.autopilot", "topic": "v1.Agrodron.Agrodron001.navigation", "action": "get_state"}
```

При активации изоляции (`isolation_start`) политики заменяются на аварийный набор, разрешающий только emergensy.

---

## 6. Конфигурация

### Системный `.env` (agrodron/.env)

```ini
TOPIC_VERSION=v1
SYSTEM_NAME=Agrodron
INSTANCE_ID=Agrodron001

ORVD_TOPIC=v1.ORVD.ORVD001.main
NUS_TOPIC=v1.NUS.NUS001.main
DRONEPORT_TOPIC=v1.Droneport.DP001.main
SITL_TOPIC=v1.SITL.SITL001.main
```

### Компонентные `.env`

Каждый компонент имеет свой `components/<name>/.env` с параметрами: `COMPONENT_ID`, `BROKER_USER`, `BROKER_PASSWORD`, и компонентно-специфичные настройки (интервалы опроса, таймауты, лимиты).

### Генерация

Скрипт `scripts/prepare_system.py` объединяет брокерный и системный docker-compose, мержит все `.env` файлы и раскрывает подстановки в политиках:

```bash
cd agrodron && make prepare
```

Результат: `agrodron/.generated/docker-compose.yml` и `agrodron/.generated/.env`.

---

## 7. Запуск и проверка

### Тесты (без Docker)

```bash
cd agrodron

make test                # Все тесты (unit + integration)
make unit-test           # 44 unit-теста компонентов
make integration-test    # 12 интеграционных тестов (in-process)
```

### Docker

```bash
cd agrodron

make docker-up           # Собрать и запустить все контейнеры
make docker-ps           # Статус контейнеров
make docker-logs         # Логи всех сервисов
make docker-logs-security_monitor   # Логи конкретного сервиса
make docker-down         # Остановить
```

Переменная `BROKER_TYPE` (по умолчанию `mqtt`) определяет используемый брокер: `mqtt` или `kafka`.

### Полный цикл

```bash
make status              # prepare + test + docker-up + docker-ps
```

### На что смотреть в логах

- Каждый компонент должен вывести: `Started. Listening on topic: v1.Agrodron.Agrodron001.<component>`
- security_monitor логирует загрузку политик и каждый proxy_request/proxy_publish
- Не должно быть сообщений `denied by policy` при штатной работе

---

## 8. Последовательность выполнения миссии

```
НУС -> security_monitor : proxy_request -> mission_handler : load_mission (WPL)
  mission_handler -> autopilot : mission_load
  mission_handler -> limiter   : mission_load
  mission_handler -> SITL      : set_home

НУС -> security_monitor : proxy_request -> autopilot : cmd START
  autopilot -> ОРВД      : request_departure
  autopilot -> Дронопорт : request_departure
  [при отказе]
    autopilot -> НУС : mission_status (mission_rejected)
  [при успехе]
    autopilot выполняет миссию (цикл: get_state navigation, set_target motors, set_spray sprayer)
  [по завершении]
    autopilot -> Дронопорт : request_landing
    autopilot -> motors    : land
    autopilot : self_diagnostics()
    autopilot -> Дронопорт : request_maintenance
    autopilot -> НУС       : mission_status (mission_completed)
```

### Аварийный сценарий

```
limiter обнаруживает отклонение от маршрута
  limiter -> emergensy : limiter_event
    emergensy -> security_monitor : isolation_start
    emergensy -> sprayer : set_spray (off)
    emergensy -> motors  : land
    emergensy -> journal : log_event
```

---

## 9. Структура проекта

```
agrodron/
  .env                          Системные параметры (топики, имя системы)
  docker-compose.yml            Сервисы компонентов
  Makefile                      Команды сборки, тестирования, запуска
  .generated/                   Сгенерированные docker-compose.yml и .env
  components/
    autopilot/                  Автопилот
    emergensy/                  Аварийный протокол
    journal/                    Журнал событий
    limiter/                    Контроль отклонений
    mission_handler/            Загрузка миссий (WPL)
    motors/                     Приводы
    navigation/                 Навигация (SITL)
    security_monitor/           Монитор безопасности
    sprayer/                    Опрыскиватель
    telemetry/                  Телеметрия
  tests/
    integration/                Интеграционные тесты (in-process)

sdk/                            BaseComponent, topic_utils
broker/                         SystemBus, MQTTSystemBus, KafkaSystemBus
docker/                         Брокер (Kafka, MQTT), docker-compose
scripts/                        prepare_system.py
config/                         Pipfile, pyproject.toml
docs/
  SYSTEM.md                     Эта документация
  EXTERNAL_API.md               API для внешних систем (НУС, ОРВД, Дронопорт, SITL)
```
