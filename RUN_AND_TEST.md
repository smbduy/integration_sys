# Запуск системы AgroDron и запуск тестов

## Требования

- **Python 3.12**
- **pipenv** (установка: `pip install pipenv`)
- **Docker** и **Docker Compose** (для запуска системы в контейнерах и для интеграционных тестов)
- На **Windows**: для команд `make` нужен WSL или Git Bash (либо выполняйте эквивалентные команды вручную из раздела ниже)

Зависимости проекта задаются в `config/Pipfile`. Из корня репозитория:

```bash
cd config
pipenv install
pipenv install --dev
cd ..
```

---

## 1. Поднять систему (Docker)

Все компоненты уже имеют рабочие `.env` в `components/<component>/.env` с топиками вида `<SYSTEM_NAME>.*`. Генератор собирает из них общий `.generated/.env` и единый `docker-compose`.

### 1.1. Выбор брокера

В `docker/.env` (или в окружении) задайте брокер:

- **Kafka**: `BROKER_TYPE=kafka`
- **MQTT**: `BROKER_TYPE=mqtt`

Если не задано, по умолчанию используется `kafka`.

### 1.2. Запуск из корня репозитория

```bash
make docker-up
```

Эта команда:

1. Выполняет **prepare** — скрипт `scripts/prepare_system.py cyber_drons` читает `.env` из каждого компонента в `components/`, собирает общий `.generated/docker-compose.yml` и `.generated/.env`.
2. Поднимает брокер (Kafka или Mosquitto) и все сервисы системы с профилем `kafka` или `mqtt`.

Эквивалент вручную (без make):

```bash
# из корня репозитория
cd config
pipenv run python ../scripts/prepare_system.py cyber_drons
cd ..
# подставить kafka или mqtt
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile mqtt up -d --build
```

### 1.3. Проверка, что всё запущено

```bash
docker ps
```

Должны быть контейнеры: брокер (kafka или mosquitto), security_monitor, journal, navigation, autopilot, limiter, emergensy, mission_handler, motors, sprayer, telemetry.

### 1.4. Логи

**Все контейнеры разом:**

```bash
make docker-logs
```

**Логи при интеграционных тестах (proxy_request, отладка):**

Логирование уже включено в коде (security_monitor, BaseComponent). Логи пишутся в stdout контейнеров. Чтобы их видеть:

1. Поднимите систему и **не останавливайте** контейнеры:
   ```bash
   make docker-up
   # подождите ~45 с
   ```

2. В **другом терминале** включите просмотр логов нужного сервиса:
   ```bash
   make docker-logs-security_monitor      # только security_monitor (входящие proxy_request, ответы/таймауты)
   # или
   make docker-logs-motors  # только motors (входящие запросы, отправка ответа)
   ```

3. В **первом терминале** запустите интеграционные тесты:
   ```bash
   set -a && . .generated/.env && set +a
   export MQTT_BROKER=localhost MQTT_PORT=1883 BROKER_TYPE=mqtt BROKER_USER=admin BROKER_PASSWORD=admin_secret_123
   pipenv run pytest -c config/pyproject.toml tests/test_full_system_run.py tests/test_integration.py -v -s
   ```

   В окне с `make docker-logs-security_monitor` появятся строки вида:
   - `[security_monitor] proxy_request: sender=telemetry -> Agrodron.motors action=get_state`
   - `[security_monitor] proxy_request -> bus.request(Agrodron.motors, timeout=10.0s)`
   - либо `proxy_request: no response from Agrodron.motors (timeout or error)`, либо `got response from Agrodron.motors, replying to client`.

**После прогона (контейнеры ещё запущены):**

```bash
# последние 200 строк security_monitor
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile mqtt logs --tail=200 security_monitor

# последние 100 строк motors
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile mqtt logs --tail=100 motors
```

Или через make (из корня репозитория):

```bash
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile mqtt logs --tail=200 security_monitor
```

**Как по логам понять, почему падают тесты**

Смотрите логи security_monitor (`make docker-logs-security_monitor`). Что искать:

| В логах | Что это значит | Что делать |
|--------|--------------------------------|------------|
| **`proxy_request denied by policy: sender=... topic=... action=...`** | Монитор отклонил запрос: в политиках нет правила для этой пары (sender, topic, action) или политики в контейнер не попали / подставились с ошибкой. | Проверить, что в `.generated/.env` есть `SECURITY_MONITOR_SECURITY_POLICIES` и что в нём подставлен `SYSTEM_NAME` (должно быть `Agrodron.navigation`, а не `.navigation`). Перегенерировать: `make prepare`, затем заново `make docker-up`. |
| **`proxy_request -> bus.request(Agrodron.motors, timeout=10.0s)`** и дальше **`no response from Agrodron.motors (timeout or error)`** | Политика разрешила запрос, но целевой компонент (motors) не ответил за 10 с. | Смотреть логи целевого контейнера (`make docker-logs-motors`): приходит ли запрос (`request action=get_state reply_to=...`), уходит ли ответ (`response sent to ...`). Если запрос не приходит — топики/сеть; если не уходит ответ — ошибка в компоненте или в reply_to. |
| **`got response from Agrodron.motors, replying to client`** | Монитор получил ответ от motors и отправил его тесту. | Если тест всё равно падает по таймауту — возможна потеря ответа до теста (топик reply, сеть). Проверить топики и что тест подписан на свой `replies/...`. |

Кратко: **`denied by policy`** → чинить политики (и подстановку SYSTEM_NAME); **`no response from X`** → чинить целевой компонент или доставку ответа до монитора.

**Важно:** после изменения `.generated/.env` (например после `make prepare` или правок политик) контейнеры продолжают работать со **старым** окружением. Чтобы применить новый `.env`, нужно перезапустить стек:

```bash
make docker-down
make docker-up
# подождать ~45 с, затем запускать тесты или смотреть логи
```

### 1.5. Остановка

```bash
make docker-down
```

При необходимости выполнить для обоих профилей:

```bash
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile kafka down
docker compose -f .generated/docker-compose.yml --env-file .generated/.env --profile mqtt down
```

---

## 2. Тесты

Запуск из **корня репозитория** (путь к Pipfile и pytest задаётся относительно него).

### 2.1. Проверка окружения для тестов

```bash
pipenv --version
pytest --version
```

Убедитесь, что доступны `pipenv` и `pytest` (через `config/Pipfile`).

### 2.2. Unit-тесты (без Docker)

Тесты компонентов лежат в `components/*/tests/`.

```bash
make unit-test
```

Эквивалент вручную:

```bash
PIPENV_PIPFILE=config/Pipfile pipenv run pytest -c config/pyproject.toml components -vv -rA -s
```

Будут выполнены, в том числе:

- `components/autopilot/tests/`
- `components/emergensy/tests/`
- `components/journal/tests/`
- `components/limiter/tests/`
- `components/mission_handler/tests/`
- `components/navigation/tests/`

### 2.3. Интеграционные тесты (in-process)

Запускают сценарии из `tests/integration/` (общая шина в памяти, без обязательного Docker):

```bash
make integration-test
```

Эквивалент: `pytest -c config/pyproject.toml tests/integration/ -v --tb=short`.

Если интеграционные тесты не нужны, ограничьтесь unit-тестами: `make unit-test`.

### 2.4. Все тесты (unit + integration)

```bash
make test
```

Сначала выполняются unit-тесты, затем интеграционные (in-process, каталог `tests/integration/`).

---

## 3. Полный цикл (Makefile)

Цель **`make status`** выполняет: `prepare` → unit- и интеграционные тесты → подъём Docker → краткая пауза → `docker-ps`.

```bash
make status
```

**Только тесты** (без Docker для интеграции in-process):

```bash
make test
```

---

## 4. Краткая шпаргалка


| Действие                                             | Команда (из корня репозитория) |
| ---------------------------------------------------- | -------------------------------- |
| **Тесты + подъём Docker (см. Makefile)**             | `make status`                    |
| Все тесты (unit + integration in-process)            | `make test`                      |
| Собрать .generated и поднять систему                 | `make docker-up`                 |
| Остановить систему                                   | `make docker-down`               |
| Логи контейнеров                                     | `make docker-logs`               |
| Только пересобрать .generated                        | `make prepare`                   |
| Unit-тесты                                           | `make unit-test`                 |
| Интеграционные тесты (Docker)                        | `make integration-test`          |
| Всё: unit + integration                              | `make test`                     |
| Справка по целям                                     | `make help`                      |


---

## 5. Переменные окружения при запуске

- **BROKER_TYPE** — `kafka` или `mqtt` (учитывается при `make docker-up` и `make docker-logs`).
- Конфигурация компонентов берётся из их `.env` в `components/<component>/.env` при каждом `make prepare`; итог попадает в `.generated/.env`.

Если вы меняли только `.env` компонентов, достаточно снова выполнить:

```bash
make prepare
make docker-up
```

