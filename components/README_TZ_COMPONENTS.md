# Обобщённое ТЗ по компонентам системы `agrodron`

Цель: все компоненты реализуются единообразно и безопасно: **любой вход и любая межкомпонентная связь — только через Монитор Безопасности (МБ / `security_monitor`)**.

---

## 1) Единый топик компонента (ровно один)

Каждый компонент имеет **ровно один** входящий топик:

- формат: `SYSTEM_NAME.COMPONENT_NAME`
- для системы: `agrodron.<component_name>`

Компонент **подписывается только на свой топик**.

Настройка через окружение:

- `SYSTEM_NAME=agrodron` (в примерах допускается `components`)
- опционально `COMPONENT_TOPIC` — если нужно переопределить топик полностью

---

## 2) Обязательная проверка входа (без исключений)

**Любое** входящее сообщение (любой `action`) компонент принимает **только от МБ**.

Рекомендованный шаблон:

```python
def _is_trusted_sender(message: dict) -> bool:
    sender = message.get("sender")
    return isinstance(sender, str) and sender.startswith("security_monitor")

def handler(message: dict):
    if not _is_trusted_sender(message):
        return None
```

Если `sender` не доверенный — компонент **молча игнорирует** запрос (возвращает `None`, не отвечает).

---

## 3) Межкомпонентная связь — только через МБ (proxy)

Компонентам запрещено:

- делать `bus.request()` / `bus.publish()` напрямую в чужие топики;
- подписываться на чужие топики.

Разрешено только:

- отправлять запросы/публикации **в топик МБ**:
  - `proxy_request` — если нужен ответ (основной способ межкомпонентного взаимодействия);
  - `proxy_publish` — команда без ответа (МБ публикует её в топик целевого компонента).

Важно: `publish` **не бесполезен**, он используется как транспорт доставки команды в **топик получателя** (получатель подписан на свой единственный топик), но **“ивент‑потоки” между компонентами не строятся** (см. пункт 4).

---

## 4) Модель данных: нет подписок на чужие топики ⇒ только request/polling

Так как компоненты **не подписываются на чужие топики**, “push‑модель” (navigation непрерывно шлёт, autopilot слушает) в этой архитектуре запрещена.

Вместо этого любой обмен данными реализуется так:

- компонент‑потребитель (например `autopilot`) **периодически** делает `proxy_request` в компонент‑источник (например `navigation`);
- компонент‑источник отвечает “снимком состояния” (snapshot) в ответ на запрос.

Пример (логически):

- `autopilot` раз в \(N\) секунд делает `proxy_request`:
  - target: `agrodron.navigation`
  - action: `GET_STATE` / `GET_LAST_STATE`
- `navigation` возвращает `{lat, lon, alt_m, ...}`.

Частоты polling должны быть настраиваемыми (например `NAV_POLL_INTERVAL_S`), а ответы — максимально компактными.

---

## 5) Формат proxy_request / proxy_publish

### 5.1) `proxy_request` (RPC через МБ)

Отправитель → МБ:

```json
{
  "action": "proxy_request",
  "sender": "autopilot",
  "payload": {
    "target": { "topic": "agrodron.navigation", "action": "GET_STATE" },
    "data": { "fields": ["lat", "lon", "alt_m"] }
  }
}
```

МБ → navigation (проксирует от своего имени):

```json
{
  "action": "GET_STATE",
  "sender": "security_monitor",
  "payload": { "fields": ["lat", "lon", "alt_m"] }
}
```

### 5.2) `proxy_publish` (команда без ответа)

Отправитель → МБ:

```json
{
  "action": "proxy_publish",
  "sender": "autopilot",
  "payload": {
    "target": { "topic": "agrodron.motors", "action": "SET_TARGET" },
    "data": { "heading_deg": 90.0, "ground_speed_mps": 5.0, "alt_m": 5.0 }
  }
}
```

МБ → motors:

```json
{
  "action": "SET_TARGET",
  "sender": "security_monitor",
  "payload": { "heading_deg": 90.0, "ground_speed_mps": 5.0, "alt_m": 5.0 }
}
```

---

## 6) Политики МБ (ACL) — только JSON

МБ проверяет доступ по тройке:

`(sender, target.topic, target.action)`

Политики задаются переменной окружения `SECURITY_POLICIES` **в JSON‑формате**:

```json
[
  { "sender": "autopilot", "topic": "agrodron.navigation", "action": "GET_STATE" },
  { "sender": "autopilot", "topic": "agrodron.motors", "action": "SET_TARGET" },
  { "sender": "autopilot", "topic": "agrodron.sprayer", "action": "SET_SPRAY" }
]
```

Режим по умолчанию: **deny-all**.

---

## 7) Изоляция (emergency / isolation mode)

МБ поддерживает команду `ISOLATION_START`, которая переводит систему в режим изоляции:

- текущие политики заменяются на фиксированный аварийный набор;
- в изоляции разрешены только минимально необходимые действия (например, `emergensy → motors.LAND`, `emergensy → sprayer.SET_SPRAY`, логирование).

---

## 8) Требования к структуре компонента (шаблон)

```
components/<component>/
├── src/<component>.py        # BaseComponent + handlers
├── config.py                 # чтение SYSTEM_NAME и сборка топиков
├── __main__.py               # запуск
├── topics.py                 # список actions (строки), без жестких топиков
├── .env.example              # SYSTEM_NAME, COMPONENT_ID, креды брокера
├── docker/Dockerfile
└── tests/
```

---

## 9) Конфигурация компонента — только через `.env` (env-driven)

Все параметры, влияющие на поведение компонента, должны настраиваться через переменные окружения
(в системе — через `.env` / docker env), включая:

- частоты polling (например `NAV_POLL_INTERVAL_S`);
- таймауты запросов (например `REQUEST_TIMEOUT_S`);
- пороги/лимиты (например `MAX_DISTANCE_FROM_PATH_M`);
- пути к файлам/каталогам (например `JOURNAL_FILE_PATH`);
- включение/выключение режимов (feature flags).

### 9.1) Где читать env в коде

Требование: **чтение env не должно быть размазано по бизнес‑логике**.

Рекомендуемая архитектура (вариант A):

- в `components/<component>/config.py`:
  - собрать топики из `SYSTEM_NAME`;
  - считать все численные/булевы параметры;
  - применить значения по умолчанию;
  - выполнить базовую валидацию (диапазоны, неотрицательность).
- в `components/<component>/src/<component>.py`:
  - использовать только готовые значения из `config.py`;
  - не обращаться к `os.environ` напрямую.

### 9.2) Правила именования переменных

- `SYSTEM_NAME` — имя системы (`agrodron`).
- `<COMPONENT>_*` — параметры конкретного компонента (например `AUTOPILOT_CONTROL_INTERVAL_S`).
- `REQUEST_TIMEOUT_S` / `SECURITY_MONITOR_TOPIC` — общесистемные параметры, если применимо.

### 9.3) МБ (security_monitor) тоже env-driven

Так как МБ — полноценный компонент системы, на него распространяются те же правила:

- таймауты реальных `request` к целевым компонентам (например `SECURITY_MONITOR_PROXY_REQUEST_TIMEOUT_S`);
- параметры режима изоляции (если добавляются);
- стартовые политики `SECURITY_POLICIES` (только JSON);
- административные параметры (`POLICY_ADMIN_SENDER`).


