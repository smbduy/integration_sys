# События журнала (логирование в journal)

Компоненты отправляют события в journal через монитор безопасности: `proxy_publish` → топик journal, `LOG_EVENT`. Исключение: security_monitor публикует в journal напрямую (доверенный отправитель).

## Реализованные события

| Компонент          | Событие                            | Когда |
|--------------------|------------------------------------|-------|
| mission_handler    | MISSION_HANDLER_VALIDATION_ERROR   | Ошибка валидации WPL/миссии |
| mission_handler    | MISSION_HANDLER_MISSION_RECEIVED   | Миссия успешно распаршена |
| mission_handler    | MISSION_HANDLER_AUTOPILOT_ERROR    | Ошибка при загрузке миссии в автопилот |
| mission_handler    | MISSION_HANDLER_MISSION_SENT_TO_AUTOPILOT | Миссия передана в автопилот |
| autopilot          | AUTOPILOT_MISSION_LOADED           | Успешная загрузка миссии |
| autopilot          | AUTOPILOT_STATE_CHANGE             | Смена состояния (команда START/PAUSE/RESUME/ABORT/RESET и т.д.) |
| autopilot          | AUTOPILOT_MISSION_COMPLETED       | Миссия завершена (все точки пройдены) |
| autopilot          | AUTOPILOT_EMERGENCY_STOP           | Получена команда EMERGENCY_STOP |
| autopilot          | AUTOPILOT_KOVER_ACTIVE             | Включён режим «Ковер» |
| autopilot          | AUTOPILOT_KOVER_LANDED             | Посадка в режиме «Ковер» завершена |
| limiter            | LIMITER_DEVIATION_WARNING          | Отклонение в зону предупреждения (state → WARNING) |
| limiter            | LIMITER_EMERGENCY_LAND_REQUIRED    | Превышен порог, отправка аварии в emergensy |
| emergensy           | EMERGENCY_PROTOCOL_STARTED         | Запущен аварийный протокол |
| navigation         | NAVIGATION_GPS_DEGRADED            | Деградация GPS (gps_valid=false) |
| security_monitor   | SECURITY_MONITOR_ISOLATION_ACTIVATED | Включён режим изоляции (ISOLATION_START) |

## Политики МБ для journal

Чтобы autopilot и limiter могли писать в журнал, в **SECURITY_POLICIES** должны быть разрешения на `proxy_publish` в journal с действием `LOG_EVENT`. Пример (подставьте свой топик журнала, например `agrodron.journal`):

- `autopilot,<JOURNAL_TOPIC>,LOG_EVENT`
- `limiter,<JOURNAL_TOPIC>,LOG_EVENT`

mission_handler, navigation, emergensy уже должны быть прописаны в политиках, если вы используете их логирование.
