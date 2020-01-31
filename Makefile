lint:
	@flake8

test: lint
	@python3 -m unittest

.PHONY: test
