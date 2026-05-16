CC ?= gcc
CFLAGS ?= -Wall -Wextra -O2 -std=gnu11
LDFLAGS_SPNAV = -lspnav -lm

# Sanitizer / coverage builds can override via `make SANITIZE=1` etc.
EXTRA_CFLAGS ?=
EXTRA_LDFLAGS ?=

# dbus-1 flags via pkg-config
DBUS_CFLAGS = $(shell pkg-config --cflags dbus-1)
DBUS_LIBS = $(shell pkg-config --libs dbus-1)

# json-c flags via pkg-config
JSON_CFLAGS = $(shell pkg-config --cflags json-c)
JSON_LIBS = $(shell pkg-config --libs json-c)

TARGETS = spacemouse-desktop spacemouse-test spnav_example

TEST_BINS = \
	tests/test_curve \
	tests/test_key_lookup \
	tests/test_de_detect \
	tests/test_scroll_acc

all: $(TARGETS)

spacemouse-core.o: spacemouse-core.c spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

spacemouse-desktop: spacemouse-desktop.c spacemouse-core.o spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) $(DBUS_CFLAGS) $(JSON_CFLAGS) \
		-o $@ spacemouse-desktop.c spacemouse-core.o \
		-lm $(DBUS_LIBS) $(JSON_LIBS) $(EXTRA_LDFLAGS)

spacemouse-test: spacemouse-test.c
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -o $@ $< $(LDFLAGS_SPNAV) $(EXTRA_LDFLAGS)

spnav_example: spnav_example.c
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -o $@ $< $(LDFLAGS_SPNAV) $(EXTRA_LDFLAGS)

# ── Unit tests ────────────────────────────────────────────────────────
#
# Each test binary links only against spacemouse-core.o and exercises one
# module via assert(). A non-zero exit code from any binary fails the
# `test` target. Sanitizer builds reuse the same rule via EXTRA_CFLAGS.

tests/test_%: tests/test_%.c spacemouse-core.o spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -I. -o $@ $< spacemouse-core.o -lm $(EXTRA_LDFLAGS)

test: $(TEST_BINS)
	@fail=0; \
	for t in $(TEST_BINS); do \
		printf '  RUN  %s ... ' "$$t"; \
		if ./$$t; then \
			printf 'ok\n'; \
		else \
			printf 'FAIL (exit %d)\n' $$?; \
			fail=1; \
		fi; \
	done; \
	exit $$fail

# clang-tidy reads .clang-tidy at the repo root. Pulling include flags
# in directly avoids the need for a compile_commands.json — the daemon
# is a single file and clang-tidy is fine with command-line -I args.
lint-c:
	@CFLAGS_TIDY="$$(pkg-config --cflags dbus-1) $$(pkg-config --cflags json-c) -I. -std=gnu11"; \
	clang-tidy --quiet spacemouse-desktop.c spacemouse-core.c -- $$CFLAGS_TIDY; \
	clang-tidy --quiet tests/test_*.c -- -I. -std=gnu11

# clang-format check: fail if any source needs reformatting. Counterpart
# to `make format` at the repo root which actually applies the changes.
format-check:
	clang-format --dry-run --Werror spacemouse-desktop.c spacemouse-core.c spacemouse-core.h tests/test_*.c

format:
	clang-format -i spacemouse-desktop.c spacemouse-core.c spacemouse-core.h tests/test_*.c

clean:
	rm -f $(TARGETS) spacemouse-core.o $(TEST_BINS)

install: all
	install -Dm755 spacemouse-desktop $(DESTDIR)$(HOME)/.local/bin/spacemouse-desktop
	install -Dm755 spacemouse-test $(DESTDIR)$(HOME)/.local/bin/spacemouse-test
	install -Dm755 ../gui/spacemouse-config.py $(DESTDIR)$(HOME)/.local/bin/spacemouse-config.py

.PHONY: all clean install test lint-c format format-check
