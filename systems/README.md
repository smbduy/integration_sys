# Системы

Шаблон: `systems/dummy_system/`

## Правило доступа

Компоненты системы, кроме монитора безопасности, должны принимать входящие запросы **только от security_monitor**. Прямые запросы от других sender — игнорировать. Подробнее: `components/README.MD` (раздел «Политика для остальных компонентов»).

## Создать свою систему

1. Скопировать `dummy_system` → `systems/my_system/`
2. В `src/` — полные копии компонентов: `my_system/src/my_component_a/`, `my_system/src/my_component_b/`
3. Каждый компонент: `src/`, `topics.py`, `.env`, `__main__.py`, `docker/Dockerfile`
4. `docker-compose.yml` — только сервисы компонентов (без брокера)
5. `make prepare` — собирает .generated/ (брокер + компоненты)
6. `make docker-up` — запуск

## Структура

```
systems/my_system/
├── src/
│   ├── my_component_a/
│   │   ├── src/
│   │   ├── topics.py
│   │   ├── .env            # COMPONENT_ID, BROKER_USER, BROKER_PASSWORD
│   │   ├── __main__.py
│   │   └── docker/Dockerfile
│   └── my_component_b/
├── docker-compose.yml
├── .generated/
├── tests/
└── Makefile
```

## Команды

```bash
cd systems/my_system
make prepare
make docker-up
make unit-test
make integration-test
```

## .env и иерархия переменных

Источник правды для компонентных переменных — `systems/<system>/src/<component>/.env`.

- В `.env` компонента задаются минимум:
  - `COMPONENT_ID`
  - `BROKER_USER`
  - `BROKER_PASSWORD`
- Для специфичных компонентов можно добавлять свои ключи
  (например, `POLICY_ADMIN_SENDER`, `SECURITY_POLICIES` для security monitor).
- `scripts/prepare_system.py` автоматически экспортирует значения в `.generated/.env`
  с префиксом имени сервиса:
  - `dummy_component_a` -> `DUMMY_COMPONENT_A_*`
  - `security_monitor` -> `SECURITY_MONITOR_*`
- В `systems/<system>/docker-compose.yml` сервисы читают эти префиксные переменные.
- В компонентных `.env` не нужно задавать инфраструктурные параметры (`BROKER_TYPE`,
  хосты/порты Kafka/MQTT, `ADMIN_*`): они остаются на уровне `docker/.env`.
