.PHONY: test test-integration test-all

# Default: fast unit suite only. tests/integration/ is excluded by the
# addopts entry in pyproject.toml, so a bare `pytest tests/` picks up
# only the unit tests even if invoked directly.
test:
	PYTHONPATH=src python3 -m pytest tests/

# Integration tier. The hook-execution harness (real `sh` against generated
# hook scripts) lives in kento-core, where hook.sh ships; kento-cli has no
# integration tests of its own. No-op gracefully when the directory is absent
# so `test-all` and the release CI's tier-2 step stay green.
test-integration:
	@if [ -d tests/integration ]; then \
		PYTHONPATH=src python3 -m pytest tests/integration/ -v; \
	else \
		echo "kento-cli has no tests/integration/ (hook integration tests live in kento-core); skipping."; \
	fi

# Both suites, unit first.
test-all: test test-integration
