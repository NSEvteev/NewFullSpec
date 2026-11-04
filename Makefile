# Makefile — команды проекта
# Подробнее: README.md
# Стандарт кода: architecture/standards/code.md

COMPOSE_FILE ?= platform/docker/docker-compose.yml
PACKAGES = $(wildcard src/*) $(wildcard shared/*)

.PHONY: dev stop build test test-tools lint map clean setup init help

# === Запуск (если сервисы подняты через docker compose) ===

dev:  ## Запустить для разработки
	docker compose -f $(COMPOSE_FILE) up

stop:  ## Остановить сервисы
	docker compose -f $(COMPOSE_FILE) down

build:  ## Собрать образы
	docker compose -f $(COMPOSE_FILE) build

# === Проверки ===

test: test-tools  ## Тесты инструментов карты и всех пакетов на Python: по одному, с потолком памяти
	@EXIT=0; \
	for pkg in $(PACKAGES); do \
		if [ -d "$$pkg/tests" ]; then \
			echo ">>> $$pkg"; \
			python scripts/test_limited.py "$$pkg" || EXIT=$$?; \
		fi; \
	done; \
	exit $$EXIT

test-tools:  ## Тесты инструментов карты
	python -m pytest architecture/tools/tests -q -p no:cacheprovider

lint:  ## Линтинг пакетов на Python: ruff check и ruff format --check
	@EXIT=0; \
	for pkg in $(PACKAGES); do \
		if [ -f "$$pkg/pyproject.toml" ]; then \
			echo ">>> ruff $$pkg"; \
			(cd "$$pkg" && ruff check . && ruff format --check .) || EXIT=1; \
		fi; \
	done; \
	exit $$EXIT

map:  ## Проверить карту, ничего не записывая
	python architecture/tools/build.py --check

# === Утилиты ===

clean:  ## Остановить сервисы и стереть их данные
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans

# === Настройка ===

setup:  ## Первоначальная настройка: зависимости инструментов и хуки pre-commit
	@python --version || (echo "Python не найден: https://python.org" && exit 1)
	pip install -r architecture/tools/requirements.txt pre-commit pytest
	pre-commit install
	pre-commit install --hook-type commit-msg
	@gh --version >/dev/null 2>&1 || echo "GitHub CLI не найден: нужен для PR и merge — https://cli.github.com/"
	@echo "Готово. Дальше: Claude Code, /new-project (подробнее — README.md)"

init:  ## Полная инициализация: setup, метки GitHub, прогон всех хуков
	@$(MAKE) setup
	@python .github/.instructions/.scripts/sync-labels.py --apply --force 2>/dev/null || echo "Метки: gh не доступен или не авторизован"
	@pre-commit run --all-files || true

# === Справка ===

help:  ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
