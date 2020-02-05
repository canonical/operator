test: lint
	@python3 -m unittest

lint:
	@flake8

.PHONY: lint test
