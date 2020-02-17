test: lint
	@python3 -m unittest

lint: quotelint
	@autopep8 -r --aggressive --diff --exit-code .
	@flake8 --config=.flake8

quotelint:
	@x=$$(grep -rnH --include \*.py "\\\\[\"']");                         \
	if [ "$$x" ]; then                                                    \
		echo "Please fix the quoting to avoid spurious backslashes:"; \
		echo "$$x";                                                   \
		exit 1;                                                       \
	fi >&2



.PHONY: lint test
