.PHONY: lint format test dev install-dev deploy-codetest deploy-tranesubishi

install-dev:
	pip install -r requirements.txt -r requirements-dev.txt
	pre-commit install

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest

dev:
	python -m flask --app web.app run --debug

deploy-codetest:
	./deploy-codetest.sh

deploy-tranesubishi:
	./deploy-tranesubishi.sh
