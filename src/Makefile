CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=gnu11
LDFLAGS_SPNAV = -lspnav -lm

# dbus-1 flags via pkg-config
DBUS_CFLAGS = $(shell pkg-config --cflags dbus-1)
DBUS_LIBS = $(shell pkg-config --libs dbus-1)

# json-c flags via pkg-config
JSON_CFLAGS = $(shell pkg-config --cflags json-c)
JSON_LIBS = $(shell pkg-config --libs json-c)

TARGETS = spacemouse-desktop spacemouse-test spnav_example

all: $(TARGETS)

spacemouse-desktop: spacemouse-desktop.c
	$(CC) $(CFLAGS) $(DBUS_CFLAGS) $(JSON_CFLAGS) -o $@ $< $(LDFLAGS_SPNAV) $(DBUS_LIBS) $(JSON_LIBS)

spacemouse-test: spacemouse-test.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS_SPNAV)

spnav_example: spnav_example.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS_SPNAV)

clean:
	rm -f $(TARGETS)

install: all
	install -Dm755 spacemouse-desktop $(DESTDIR)$(HOME)/.local/bin/spacemouse-desktop
	install -Dm755 spacemouse-test $(DESTDIR)$(HOME)/.local/bin/spacemouse-test
	install -Dm755 ../gui/spacemouse-config.py $(DESTDIR)$(HOME)/.local/bin/spacemouse-config.py

.PHONY: all clean install
