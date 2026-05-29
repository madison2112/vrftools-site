.PHONY: lint format test dev install-dev deploy-codetest deploy-tranesubishi visual-test visual-baseline

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

visual-test:
	pytest tests/test_visual_regression.py -v

visual-baseline:
	VISUAL_BASELINE=1 pytest tests/test_visual_regression.py -v
	@echo "Baselines written to tests/baselines/. Review and commit."

dev:
	python -m flask --app web.app run --debug

deploy-codetest:
	./deploy-codetest.sh

deploy-tranesubishi:
	./deploy-tranesubishi.sh
