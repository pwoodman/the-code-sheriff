.PHONY: doctor detect format lint dry security compile ui version review check test install hooks

install:
	python3 -m pip install -e ".[dev]"

doctor:
	quality doctor

detect:
	quality detect

format:
	quality format --check

lint:
	quality lint

dry:
	quality dry

security:
	quality security

compile:
	quality compile

ui:
	quality ui

version:
	quality version

review:
	quality review --base origin/main || quality review

check:
	quality run --skip review

test:
	pytest
	ruff check src tests
	ruff format --check src tests

hooks:
	pre-commit install --hook-type pre-commit --hook-type pre-push
