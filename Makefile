# Top-level orchestrator. The C build still lives in src/Makefile;
# this file glues the formatters and linters across all three languages
# behind one set of make targets so contributors don't have to learn
# clang-format, ruff and shfmt invocations separately.

PY_SOURCES = .
SHELL_SOURCES = install.sh uninstall.sh freecad/scripts/*.sh

.PHONY: format format-check lint test help

help:
	@echo 'Targets:'
	@echo '  format         Apply clang-format, ruff format and shfmt across the tree'
	@echo '  format-check   Verify formatters would not change anything (CI gate)'
	@echo '  lint           Run ruff check, shellcheck and clang-tidy'
	@echo '  test           Run C unit tests and the pytest suite'

format:
	$(MAKE) -C src format
	ruff format $(PY_SOURCES)
	ruff check --fix $(PY_SOURCES)
	shfmt -w -i 4 -ci -bn $(SHELL_SOURCES)

format-check:
	$(MAKE) -C src format-check
	ruff format --check $(PY_SOURCES)
	shfmt -d -i 4 -ci -bn $(SHELL_SOURCES)

lint:
	ruff check $(PY_SOURCES)
	shellcheck --severity=warning $(SHELL_SOURCES)
	$(MAKE) -C src lint-c

test:
	$(MAKE) -C src test
	pytest tests/
