.PHONY: install install-dev run test lint format clean

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

run:
	uvicorn server:app --host 0.0.0.0 --port 5000 --reload

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

clean:
	rm -rf __pycache__ nova/__pycache__ tests/__pycache__ .pytest_cache nova.db nova.db-wal nova.db-shm
