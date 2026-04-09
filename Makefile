# Точка входа интеграции: НУС/Дронопорт — DronePortGCS-integration_drone; SITL — SITL-module-main/SITL-module-main; дрон — agrodron.

NUS_DIR := DronePortGCS-integration_drone
SITL_DIR := SITL-module-main/SITL-module-main
AGRODRON_DIR := $(if $(wildcard cyber_drons/agrodron/Makefile),cyber_drons/agrodron,$(if $(wildcard agrodron/Makefile),agrodron,Agrodron-master/agrodron))

.PHONY: help stack-up stack-down docker-net web-nus agrodron-up agrodron-down full-stack-up full-stack-down mission-demo-up purge-all-containers purge-project-containers

help:
	@echo "Интеграция (корень Integ):"
	@echo "  make stack-up       — брокер + НУС + Дронопорт + SITL (дрон НЕ входит в эту команду)"
	@echo "  make agrodron-up    — контейнеры Агродрона к уже запущенному mosquitto (после stack-up)"
	@echo "  make full-stack-up  — stack-up, затем agrodron-up"
	@echo "  make mission-demo-up — agrodron up -> SITL up -> GCS up -> DronePort up -> web-nus"
	@echo "  make agrodron-down  — остановить только сервисы Агродрона"
	@echo "  make stack-down     — остановить НУС/Дронопорт/SITL/брокер"
	@echo "  make full-stack-down — agrodron-down + stack-down"
	@echo "  make purge-all-containers — удалить все Docker-контейнеры на хосте"
	@echo "  make purge-project-containers — удалить контейнеры только наших стеков"
	@echo "  make docker-net     — создать внешнюю сеть drones_net (если ещё нет)"
	@echo "  make web-nus        — веб НУС после stack-up (порт 8000)"
	@echo "НУС: $(NUS_DIR)  |  Дрон: $(AGRODRON_DIR)"

stack-up:
	@$(MAKE) -C $(NUS_DIR) stack-with-sitl-up

stack-down:
	@$(MAKE) -C $(NUS_DIR) stack-with-sitl-down

docker-net:
	@$(MAKE) -C $(NUS_DIR) docker-net

web-nus:
	@$(MAKE) -C $(NUS_DIR) web-nus

agrodron-up:
	@echo "[agrodron] Нужны сеть drones_net и брокер mosquitto (сначала: make stack-up или make docker-net)"
	@$(MAKE) -C $(AGRODRON_DIR) docker-up-components

agrodron-down:
	@$(MAKE) -C $(AGRODRON_DIR) docker-down

full-stack-up: stack-up agrodron-up

full-stack-down: agrodron-down stack-down

# Последовательный запуск для демонстрации миссии:
# 1) agrodron (mqtt, make docker-up)
# 2) SITL (make sitl-up)
# 3) GCS
# 4) DronePort
# 5) веб-интерфейс НУС (web-nus запускается в foreground)
mission-demo-up:
	@echo "[1/5] Поднимаем AgroDron (docker-up-components)"
	@cd "$(AGRODRON_DIR)" && make docker-up-components
	@echo "[2/5] Поднимаем SITL (sitl-up)"
	@cd "$(SITL_DIR)" && make sitl-up
	@echo "[3/5] Поднимаем GCS (gcs-system-up)"
	@cd "$(NUS_DIR)" && make gcs-system-up
	@echo "[4/5] Поднимаем DronePort (drone-port-system-up)"
	@cd "$(NUS_DIR)" && make drone-port-system-up
	@echo "[5/5] Запускаем веб-интерфейс НУС (web-nus)"
	@cd "$(NUS_DIR)" && make web-nus

purge-all-containers:
	@echo "[docker] Удаляю все контейнеры (running + stopped)..."
	-@docker rm -f $$(docker ps -aq) 2>/dev/null || true
	@echo "[docker] Готово."

purge-project-containers:
	@echo "[docker] Удаляю контейнеры наших стеков (drones/gcs/drone-port/sitl)..."
	-@ids=$$(docker ps -aq --filter "name=^drones-" --filter "name=^gcs-" --filter "name=^drone-port-" --filter "name=^sitl-"); \
	  if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "[docker] Подходящих контейнеров не найдено."; fi
	@echo "[docker] Готово."
