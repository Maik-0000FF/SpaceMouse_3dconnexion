/*
 * test_spnav_busyloop.c — 30-second CPU stress demo for FreeCAD #17809
 *
 * Phase 1 (15s): Simulates the BUG — select() busy loop on EOF socket (100% CPU)
 * Phase 2 (15s): Applies the FIX — recv(MSG_PEEK) detects EOF, loop stops (0% CPU)
 *
 * Watch with: btop, htop, or top
 * Build:  gcc -O2 -o test_spnav_busyloop test_spnav_busyloop.c
 */

#include <errno.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

int main(void)
{
    int sv[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) < 0) {
        perror("socketpair");
        return 1;
    }

    int client_fd = sv[0];

    /* Simulate spacenavd dying */
    close(sv[1]);

    printf("=== Phase 1: BUG — select() busy loop on dead socket ===\n");
    printf(">>> Erwarte 100%% CPU auf einem Kern — beobachte btop! <<<\n");
    printf("Läuft 10 Sekunden...\n\n");
    fflush(stdout);

    struct timeval start, now;
    long wakeups = 0;

    gettimeofday(&start, NULL);
    for (;;) {
        gettimeofday(&now, NULL);
        long elapsed = (now.tv_sec - start.tv_sec);
        if (elapsed >= 10) {
            break;
        }

        /* This is exactly what FreeCAD does via QSocketNotifier + pollSpacenav():
         * select() says "readable" because EOF is always readable,
         * spnav_poll_event() returns 0 (no events), cycle repeats. */
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(client_fd, &rfds);
        struct timeval tv = {0, 0};

        if (select(client_fd + 1, &rfds, NULL, NULL, &tv) > 0) {
            /* Simulate spnav_poll_event() returning 0 — it can't detect EOF */
            wakeups++;
        }
    }

    printf("Phase 1 beendet: %ld Wakeups in 10s (Busy Loop!)\n\n", wakeups);

    /* ---- Now apply the fix ---- */
    printf("=== Phase 2: FIX — recv(MSG_PEEK) erkennt EOF, Loop stoppt ===\n");
    printf(">>> Erwarte 0%% CPU — beobachte btop! <<<\n");
    printf("Läuft 10 Sekunden...\n\n");
    fflush(stdout);

    /* The fix: detect EOF with recv(MSG_PEEK) */
    char buf;
    ssize_t ret = recv(client_fd, &buf, 1, MSG_PEEK | MSG_DONTWAIT);
    if (ret == 0) {
        printf("recv(MSG_PEEK) = 0 → EOF erkannt! Socket ist tot.\n");
        printf("→ Notifier wird deaktiviert, spnav_close() aufgerufen.\n");
        printf("→ Kein Busy Loop mehr. Warte 10s als Beweis...\n\n");
        fflush(stdout);

        /* Simulate "notifier disabled" — just sleep, no CPU usage */
        sleep(10);
    }

    close(client_fd);

    printf("=== Fertig ===\n");
    printf("Phase 1: 100%% CPU (Bug)  → %ld select()-Wakeups\n", wakeups);
    printf("Phase 2:   0%% CPU (Fix)  → recv(MSG_PEEK) hat EOF erkannt\n");

    return 0;
}
