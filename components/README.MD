# Компоненты

Шаблон: `components/dummy_component/`

## Обязательное правило (все компоненты кроме монитора)

**Все компоненты, кроме `security_monitor`, должны принимать входящие запросы только от монитора безопасности.**  
Прямые запросы от других sender должны игнорироваться (например, возвращать `None` в handler). Реализация — проверка `message["sender"]` в начале каждого бизнес-handler’а (см. раздел «Политика для остальных компонентов» ниже).

## Создать свой компонент

1. Скопировать `dummy_component` → `components/my_component/`
2. В `src/my_component.py`: наследоваться от `BaseComponent`, реализовать `_register_handlers()`
3. `__main__.py` — точка входа (standalone без брокера)
4. `docker/Dockerfile` — `CMD ["python", "-m", "components.my_component"]`
5. `Makefile`: `docker-build`, `docker-up`, `unit-test`

## Структура

```
components/my_component/
├── src/
│   └── my_component.py    # Класс от BaseComponent
├── __main__.py            # Запуск standalone
├── docker/Dockerfile
├── tests/
└── Makefile
```

## Класс

```python
from sdk.base_component import BaseComponent

class MyComponent(BaseComponent):
    def __init__(self, component_id: str, name: str, bus: SystemBus, topic: str = "components.my_component"):
        super().__init__(component_id=component_id, component_type="my_component", topic=topic, bus=bus)

    def _register_handlers(self):
        self.register_handler("action_name", self._handle_action)
```

## В составе системы

Компонент копируется целиком в `systems/my_system/src/my_component_a/`. Добавляются `topics.py`, `.env` (COMPONENT_ID, BROKER_USER, BROKER_PASSWORD), `__main__.py` с подключением к брокеру.

## Политика для остальных компонентов

Все компоненты, кроме монитора, принимают бизнес-действия **только от монитора** (sender вида `security_monitor` или `security_monitor_*`). Остальные sender — блокировать.

Рекомендуемый базовый шаблон в компоненте:

```python
def _is_trusted_sender(self, message: dict) -> bool:
    sender = message.get("sender")
    return isinstance(sender, str) and sender.startswith("security_monitor")
```

И в handler-ах:

```python
if not self._is_trusted_sender(message):
    return None
```

## Security Monitor

Для монитора безопасности см. `components/security_monitor/README.md`:

- переменные `POLICY_ADMIN_SENDER`, `SECURITY_POLICIES`
- actions `proxy_request`, `proxy_publish`, `set_policy`, `remove_policy`, `clear_policies`, `list_policies`
- примеры запросов и policy-форматов
