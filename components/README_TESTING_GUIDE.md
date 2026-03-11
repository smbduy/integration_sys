# Гайд по тестированию компонентов `agrodron`

Этот документ — справка для команды по тому, **как и что тестировать** в нашей архитектуре компонентов (`autopilot`, `limiter`, `emergensy`, `security_monitor`, и будущие `navigation`, `motors`, `sprayer`, `mission_handler`, `journal`).

Ориентируемся на то, что:

- каждый компонент имеет **один входной топик** `agrodron.<component>`;
- все входящие запросы приходят **только через Монитор Безопасности (МБ)**;
- межкомпонентное взаимодействие — **только через `proxy_request` / `proxy_publish`**;
- любой обмен данными (`navigation`, `telemetry`) — это **polling через МБ**, без подписок на чужие топики;
- все параметры — **через `.env`** и `config.py`.

Ниже — виды тестов, зачем они нужны, и примерные сценарии для каждого компонента.

---

## 1. Какие бывают тесты (простым языком)

### 1.1. Unit‑тесты (юнит‑тесты)

**Цель:** проверить *логику одного класса/функции в изоляции*.

- тестируем конкретный метод (`_handle_cmd`, `_recalculate`, `_poll_navigation_if_due`, …);
- вместо реального брокера / Redis / SITL — моки (заглушки);
- быстрые, запускаются при каждом изменении кода.

Примеры:

- `LimiterComponent._recalculate` правильно ставит `NORMAL/WARNING/EMERGENCY`;
- `EmergenseyComponent._handle_limiter_event` при `EMERGENCY_LAND_REQUIRED` шлёт правильные команды.

### 1.2. Интеграционные тесты

**Цель:** проверить *как несколько компонентов работают вместе*.

- запускаем несколько реальных компонентов (`autopilot + security_monitor + navigation_stub`);
- используем in‑memory `SystemBus` вместо реального MQTT/Kafka;
- проверяем, что сообщения проходят через МБ, политики работают, пайплайны не ломаются.

Примеры:

- `limiter → emergensy → security_monitor` запускают аварийную посадку;
- `autopilot` реально делает `proxy_request` к `navigation` и `proxy_publish` к `motors`.

### 1.3. End‑to‑End (E2E) / системные тесты

**Цель:** проверить *цепочку целиком*, максимально близко к боевому запуску.

- поднимаем все нужные сервисы в Docker (MQTT/Kafka, Redis, SITL, наши компоненты);
- прогоняем “живые” сценарии: запустить миссию, дрон летит по маршруту, при нарушении ограничений срабатывает авария.

E2E‑тесты долговременные (минуты), их обычно гоняют не на каждый коммит, а:

- перед релизом;
- каждую ночь;
- по кнопке (“smoke/acceptance tests”).

### 1.4. Smoke‑тесты

**Цель:** “жив ли сервис вообще”.

- простые проверки:
  - компонент стартует;
  - отвечает на `ping`/`get_status` (через МБ);
  - может обработать одну тестовую команду без ошибок.

Smoke‑тесты полезно запускать:

- после деплоя;
- при ручной проверке новой конфигурации.

---

## 2. Общие принципы тестирования наших компонентов

1. **Все входы — через сообщения**
   - Не вызываем методы компонентов напрямую (кроме unit‑тестов на приватную логику).
   - В интеграции и выше отправляем dict‑сообщения в `SystemBus` / МБ.

2. **Проверка безопасности**
   - Юнит: `_is_trusted_sender` + проверка, что при неверном `sender` handler возвращает `None`.
   - Интеграция: прямые сообщения в топик компонента (мимо МБ) должны игнорироваться.

3. **Нет подписок на чужие топики**
   - Navigation / telemetry только через polling.
   - В тестах важно проверить, что компонент **сам** вызывает `proxy_request` (через МБ), а не ждёт “ивентов”.

4. **Параметры — через `.env`**
   - В тестах можно:
     - подставлять env‑переменные (через `os.environ` или фикстуры pytest);
     - проверять поведение при разных значениях (например, уменьшенный `*_INTERVAL_S` для ускорения теста).

---

## 3. Unit‑тесты по компонентам

### 3.1. Autopilot

**Что тестировать:**

1. **Загрузка миссии (`_handle_mission_load`)**
   - неверный `sender` → `None`;
   - `mission` не dict → `{"ok": False, "error": "invalid_mission"}`;
   - корректная миссия:
     - `_mission` сохранён;
     - `_current_step_index` = 0;
     - `_state = "MISSION_LOADED"`.

2. **Команды (`_handle_cmd`)**
   - все варианты: `START/PAUSE/RESUME/ABORT/RESET/EMERGENCY_STOP/KOVER`:
     - без миссии `START` даёт ошибку `no_mission`;
     - переходы состояний:
       - `MISSION_LOADED` + `START` → `EXECUTING`;
       - `EXECUTING` + `PAUSE` → `PAUSED`;
       - `PAUSED` + `RESUME` → `EXECUTING`;
       - `RESET` очищает `_mission` и ставит `IDLE`;
       - `EMERGENCY_STOP` → `EMERGENCY_STOP`;
       - `KOVER` включает `_kover_active` и (если надо) переводит в `EXECUTING`.

3. **Состояние (`_handle_get_state`)**
   - возвращает:
     - `state` — текущее состояние;
     - `mission_id`;
     - `current_step_index`, `total_steps`;
     - `sprayer_state`, `last_nav_state`.

4. **Управляющий цикл (`_step_control`)**
   - без навигации (`_last_nav_state is None`) — ничего не делает;
   - при движении:
     - при расстоянии > порога — отправляет `SET_TARGET` + `SET_SPRAY(step.spray)`;
     - при достижении точки:
       - переходит к следующему шагу;
       - при последнем шаге:
         - ставит `COMPLETED`;
         - посылает `SET_TARGET` с `speed=0`;
         - `SET_SPRAY(False)`.
   - в `PAUSED` всегда отправляет “удержание” (скорость 0, спрей OFF).

5. **Режим `KOVER`**
   - при `_kover_active=True`:
     - каждое `_step_control()`:
       - целится на `alt_m = 0.0`;
       - скорость 0;
       - спрей OFF;
     - когда высота близка к 0 → `_kover_active=False`, `_state="PAUSED"`.

6. **Polling навигации (`_poll_navigation_if_due`)**
   - если интервал ещё не прошёл — не вызывает `bus.request`;
   - если прошёл:
     - собирает сообщение `proxy_request` к `navigation`;
     - вызывает `bus.request(security_monitor_topic, msg, timeout=...)`;
     - при удачном ответе:
       - забирает `payload.target_response.payload` и кладёт в `_last_nav_state`.

### 3.2. Limiter

**Что тестировать:**

1. **mission_load**
   - аналогично автопилоту: неверный `sender` → `None`, невалидная миссия → ошибка, валидная — сохраняется.

2. **update_config**
   - изменение `max_distance_from_path_m` и `max_alt_deviation_m`:
     - проверка новых значений в возвращаемом dict;
     - влияние на `_recalculate()` (см. ниже).

3. **get_state**
   - возвращает `state` и актуальные пороги.

4. **_recalculate**
   - сценарии:
     - нет миссии или навигации → ничего не делает;
     - расстояние и высота в норме → `state="NORMAL"`;
     - около порогов → `state="WARNING"`;
     - выше порога → `state="EMERGENCY"` и вызов `_publish_emergency(...)` **один раз** для каждого входа в emergency.

5. **_publish_emergency**
   - замокать `bus.publish`:
     - проверка, что отправляется `proxy_publish` в МБ с:
       - `target.topic = agrodron.emergensy`;
       - `target.action = "limiter_event"`;
       - `data.event = "EMERGENCY_LAND_REQUIRED"`, `data.details` с правильными полями.

6. **Polling навигации/телеметрии**
   - `_poll_navigation_if_due`, `_poll_telemetry_if_due`:
     - интервал;
     - сборки `proxy_request`;
     - разбор успешного ответа (как у автопилота).

### 3.3. Emergensey

**Что тестировать:**

1. **limiter_event**
   - неверный `sender` → `None`;
   - `event` ≠ `EMERGENCY_LAND_REQUIRED`:
     - возвращает `{"ok": False, "ignored": True}`;
   - корректный event:
     - `_active=True`;
     - в МБ уходят:
       - `ISOLATION_START` с правильным `reason`/`mission_id`;
       - `proxy_publish` в `sprayer` / `SET_SPRAY(false)` с `reason="emergency"`;
       - `proxy_publish` в `motors` / `LAND` с `mode="AUTO_LAND"`;
       - `proxy_publish` в `journal` / `LOG_EVENT` с `event="EMERGENCY_PROTOCOL_STARTED"`.

2. **get_state**
   - `{active: bool}`.

### 3.4. Security Monitor

**Что тестировать:**

1. **_parse_policies**
   - пустая строка → пустой set;
   - валидный JSON‑список → корректный set;
   - некорректный JSON → fallback (у нас сейчас он пытается парсить строковый формат, но в системе используем только JSON).

2. **policy‑handlers (`set/remove/clear/list`)**
   - только `POLICY_ADMIN_SENDER` может менять политики;
   - корректность добавления/удаления;
   - `list_policies` возвращает отсортированный список.

3. **_is_allowed / proxy_request / proxy_publish**
   - без policy → `None`;
   - с policy:
     - собирает сообщение к целевому компоненту от имени МБ;
     - возвращает `target_response` (для `proxy_request`);
     - возвращает `{"published": True/False}` для `proxy_publish`.

4. **Изоляция**
   - `ISOLATION_START` от `emergensy`:
     - только sender с `emergensy`‑префиксом или admin может включить;
     - `_mode="ISOLATED"`;
     - `_policies` заменены аварийным набором (по `config.topic_for(...)`).
   - `isolation_status` возвращает `{mode: "NORMAL"|"ISOLATED"}`.

---

## 4. Интеграционные тесты (несколько компонентов вместе)

### 4.1. Limiter ↔ Emergensey ↔ SecurityMonitor

**Цель:** проверить аварийную цепочку.

1. Поднять in‑memory `SystemBus`.
2. Инициализировать:
   - `SecurityMonitorComponent` на `agrodron.security_monitor`;
   - `EmergenseyComponent` на `agrodron.emergensy`;
   - `LimiterComponent` на `agrodron.limiter`.
3. Настроить `SECURITY_POLICIES`, чтобы:
   - `limiter` мог `proxy_publish` в `agrodron.emergensy` / `limiter_event`;
   - `emergensy` мог слать:
     - `ISOLATION_START` в МБ;
     - `proxy_publish` в `motors/sprayer/journal`.
4. Сценарий:
   - передать миссию в limiter;
   - подставить навигацию так, чтобы `_recalculate` перевёл в `EMERGENCY`;
   - проверить:
     - `EmergenseyComponent` получил `limiter_event`;
     - МБ применил изоляцию (`isolation_status` → `ISOLATED`);
     - ушли команды `LAND`, `SET_SPRAY(false)`, `LOG_EVENT`.

### 4.2. Autopilot ↔ Navigation stub ↔ SecurityMonitor

**Цель:** проверить polling навигации.

1. Поднять in‑memory bus + МБ + Autopilot.
2. Добавить stub‑компонент `navigation`:
   - на `agrodron.navigation`;
   - handler `get_state` возвращает фиксированную позицию.
3. Политика:
   - `("autopilot", "agrodron.navigation", "get_state")`.
4. Проверка:
   - через некоторое время после старта у автопилота `_last_nav_state` заполняется данными stub‑компонента;
   - `proxy_request` реально проходит через МБ.

### 4.3. Autopilot ↔ Motors/Sprayer stub ↔ SecurityMonitor

**Цель:** проверить управление движением и опрыскиванием.

1. Stub‑компоненты:
   - `motors` на `agrodron.motors`;
   - `sprayer` на `agrodron.sprayer`;
   - каждый пишет последнее полученное сообщение во внутреннее поле для проверки.
2. Политики:
   - `("autopilot", "agrodron.motors", "SET_TARGET")`;
   - `("autopilot", "agrodron.sprayer", "SET_SPRAY")`.
3. Сценарий:
   - загрузить миссию с двумя шагами (`spray=false` и `spray=true`);
   - имитировать навигацию так, чтобы дрон последовательно приближался к точкам;
   - проверить:
     - изменение SET_TARGET в motors;
     - изменение SET_SPRAY в sprayer в нужные моменты.

---

## 5. E2E / системные тесты (на будущее, с SITL)

Когда будут готовы `navigation`, `motors`, `sprayer` и SITL:

1. **Smoke‑E2E “простая миссия”**
   - поднять:
     - MQTT/Kafka, Redis, SITL;
     - `security_monitor`, `autopilot`, `limiter`, `emergensy`, `navigation`, `motors`, `sprayer`, `telemetry`, `journal`;
   - загрузить простую миссию (2–3 точки);
   - убедиться по логам/журналу/NMEA, что:
     - дрон “летит” по маршруту;
     - `navigation` отдаёт консистентные координаты;
     - команды автопилота соответствуют траектории.

2. **E2E “ограничитель → авария”**
   - та же конфигурация;
   - задать пороги limiter так, чтобы отклонение гарантированно случилось;
   - в процессе полёта:
     - `limiter` публикует аварийное событие;
     - `emergensy` инициирует посадку;
     - SITL выдаёт событие `emergency_landing`;
     - все события записываются в `journal`.

3. **E2E “изоляция”**
   - проверить, что после `ISOLATION_START` МБ блокирует все новые proxy‑запросы, кроме аварийного набора политик.

---

## 6. Когда что запускать

- **При каждом изменении логики компонента**
  - Unit‑тесты для этого компонента.

- **Перед merge в основную ветку**
  - Unit‑тесты для всех компонентов;
  - Интеграционные тесты основных цепочек:
    - `limiter ↔ emergensy ↔ security_monitor`;
    - `autopilot ↔ navigation_stub ↔ security_monitor`.

- **Перед релизом / на nightly пайплайне**
  - Все unit+integration;
  - E2E‑сценарии с SITL (по мере их реализации).

Если что-то в этом плане кажется слишком сложным/абстрактным, можно по каждому разделу отдельно сделать “мини‑гайд с примерами теста на pytest” — но эта справка даёт именно “карту местности”: какие уровни тестов нужны и что они должны проверять в контексте вашей архитектуры. 

