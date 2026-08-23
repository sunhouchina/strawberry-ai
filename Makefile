PYTHON ?= python

run:
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload

test:
	cd backend && $(PYTHON) -m pytest

lint:
	cd backend && $(PYTHON) -m ruff check app tests

format:
	cd backend && $(PYTHON) -m ruff format app tests

migrate:
	cd backend && $(PYTHON) -m alembic upgrade head
