test: lint
	@python3 -m unittest

lint:
	@autopep8 -r --aggressive --diff --exit-code .
	@flake8 --config=.flake8

.PHONY: lint test
