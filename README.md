# Avito Test Service

Сервис для управления командами, пользователями и Pull Request-ами с назначением ревьюеров.  

---

## Содержание
- [Описание]
- [Технологии]
- [Запуск проекта]
- [Тестирование]
- [Makefile]
- [API Endpoints]
- [Примеры curl]

---

## Описание
Сервис позволяет:
- Добавлять команды и пользователей
- Управлять активностью пользователей
- Создавать Pull Request и назначать ревьюеров
- Переназначать ревьюеров и сливать PR
- Сбрасывать базу данных (для локальной разработки)
- Получать статистику распределения PR по пользователям

---

## Технологии
- Python 3.11
- FastAPI
- SQLAlchemy + PostgreSQL
- Pytest для тестов
- Docker / Docker Compose (для локального запуска)
- flake8, black, isort (для линтинга и форматирования)

---

## Запуск проекта

### Локально без Docker:
1. Создать виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
Установить зависимости:
pip install -r requirements.txt
Запустить сервис:
make run

Через Docker:
docker-compose up --build
Сервис будет доступен на http://localhost:8080.

## Тестирование
Запуск тестов через pytest:
make test


## Makefile
make run — запуск сервиса

make test — запуск тестов

make lint — проверка стиля кода (flake8, black, isort)

make format — автоматическое форматирование кода


## API Endpoints
Команды
POST /team/add — добавить команду с пользователями

GET /team/get?team_name=... — получить команду

POST /team/deactivate_members?team_name=... — массовая деактивация пользователей

Пользователи
POST /users/setIsActive — установить активность пользователя

GET /users/getReview?user_id=... — получить PR, где пользователь ревьюер

Pull Request
POST /pullRequest/create — создать PR

POST /pullRequest/merge — слить PR

POST /pullRequest/reassign — переназначить ревьюера

Dev Only
POST /reset — сброс базы данных (только для локальной разработки)

## Примеры curl
Добавить команду:
curl -X POST http://localhost:8080/team/add \
-H "Content-Type: application/json" \
-d '{"team_name":"backend","members":[{"user_id":"u1","username":"Alice","is_active":true}]}'

Получить команду:
curl -X GET "http://localhost:8080/team/get?team_name=backend"

Установить активность пользователя:
curl -X POST http://localhost:8080/users/setIsActive \
-H "Content-Type: application/json" \
-d '{"user_id":"u1","is_active":false}'

Создать Pull Request:
curl -X POST http://localhost:8080/pullRequest/create \
-H "Content-Type: application/json" \
-d '{"pull_request_id":"pr-1","pull_request_name":"Feature X","author_id":"u1"}'

Слить PR:
curl -X POST http://localhost:8080/pullRequest/merge \
-H "Content-Type: application/json" \
-d '{"pull_request_id":"pr-1"}'

Переназначить ревьюера:
curl -X POST http://localhost:8080/pullRequest/reassign \
-H "Content-Type: application/json" \
-d '{"pull_request_id":"pr-1","old_reviewer_id":"u1"}'

Получить PR для ревью:
curl -X GET "http://localhost:8080/users/getReview?user_id=u1"

Получить статистику распределения PR:
curl -X GET http://localhost:8080/stats/user_assignments

Массовая деактивация участников команды:
curl -X POST "http://localhost:8080/team/deactivate_members?team_name=backend"

Сброс базы данных (dev only):
curl -X POST http://localhost:8080/reset