PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: install api web test dev clean

install: api-install web-install

api-install:
	python3.12 -m venv apps/api/.venv
	$(PIP) install -r apps/api/requirements.txt

web-install:
	cd apps/web && npm install

api:
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	cd apps/api && .venv/bin/python -m pytest -q

dev:
	./scripts/dev.sh

clean:
	rm -rf apps/api/data apps/api/.pytest_cache apps/api/**/__pycache__ apps/web/.next
