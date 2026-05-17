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
	tests/test_scroll_acc \
	tests/test_kinput_state \
	tests/test_command_socket

all: $(TARGETS)

DAEMON_OBJS = spacemouse-core.o config.o command_socket.o kernel_input.o uinput.o \
              dbus_actions.o desktop_actions.o

spacemouse-core.o: spacemouse-core.c spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

config.o: config.c config.h spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) $(JSON_CFLAGS) -c -o $@ $<

command_socket.o: command_socket.c command_socket.h config.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

kernel_input.o: kernel_input.c kernel_input.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

uinput.o: uinput.c uinput.h spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

dbus_actions.o: dbus_actions.c dbus_actions.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) $(DBUS_CFLAGS) -c -o $@ $<

desktop_actions.o: desktop_actions.c desktop_actions.h dbus_actions.h uinput.h spacemouse-core.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -c -o $@ $<

spacemouse-desktop: spacemouse-desktop.c $(DAEMON_OBJS) spacemouse-core.h config.h \
                    command_socket.h kernel_input.h uinput.h dbus_actions.h desktop_actions.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) $(JSON_CFLAGS) \
		-o $@ spacemouse-desktop.c $(DAEMON_OBJS) \
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

# Specific override: this test exercises kernel_input.c, not spacemouse-core.
tests/test_kinput_state: tests/test_kinput_state.c kernel_input.o kernel_input.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -I. -o $@ $< kernel_input.o $(EXTRA_LDFLAGS)

# Specific override: this test exercises command_socket.c and uses
# the profile globals defined in config.c. spacemouse-core.o is pulled
# in because config.c calls lookup_key() at link time.
tests/test_command_socket: tests/test_command_socket.c command_socket.o config.o spacemouse-core.o \
                            command_socket.h config.h
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) $(JSON_CFLAGS) -I. -o $@ $< \
		command_socket.o config.o spacemouse-core.o \
		-lm $(JSON_LIBS) $(EXTRA_LDFLAGS)

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
	clang-tidy --quiet spacemouse-desktop.c spacemouse-core.c config.c command_socket.c kernel_input.c uinput.c dbus_actions.c desktop_actions.c -- $$CFLAGS_TIDY; \
	clang-tidy --quiet tests/test_*.c -- -I. -std=gnu11

# clang-format check: fail if any source needs reformatting. Counterpart
# to `make format` at the repo root which actually applies the changes.
C_SOURCES = spacemouse-desktop.c spacemouse-core.c spacemouse-core.h config.c config.h \
            command_socket.c command_socket.h kernel_input.c kernel_input.h \
            uinput.c uinput.h dbus_actions.c dbus_actions.h \
            desktop_actions.c desktop_actions.h \
            tests/test_curve.c tests/test_key_lookup.c tests/test_de_detect.c \
            tests/test_scroll_acc.c tests/test_kinput_state.c \
            tests/test_command_socket.c

format-check:
	clang-format --dry-run --Werror $(C_SOURCES)

format:
	clang-format -i $(C_SOURCES)

clean:
	rm -f $(TARGETS) $(DAEMON_OBJS) $(TEST_BINS)

install: all
	install -Dm755 spacemouse-desktop $(DESTDIR)$(HOME)/.local/bin/spacemouse-desktop
	install -Dm755 spacemouse-test $(DESTDIR)$(HOME)/.local/bin/spacemouse-test
	install -Dm755 ../gui/spacemouse-config.py $(DESTDIR)$(HOME)/.local/bin/spacemouse-config.py

.PHONY: all clean install test lint-c format format-check
