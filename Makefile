# The framework is subject to its own rules: detection finds these targets, and the gate
# runs them like any other project's.
.PHONY: test lint check

test:
	python3 -m unittest discover -s tests -v

lint:
	python3 -m compileall -q scripts/aegis/aegis_cli tests

check: lint test
	./scripts/aegis/aegis gate --stage bootstrap --no-run
