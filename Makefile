.PHONY: run test lint

run:
	uvicorn server:app --reload --port 8080

test:
	pytest -v --disable-warnings

lint:
	flake8 server.py test_endpoints.py
	black --check server.py test_endpoints.py
	isort --check-only server.py test_endpoints.py
