/*
 * test_spnav_disconnect.c — Reproducer for FreeCAD issue #17809
 *
 * Demonstrates that when spacenavd closes the Unix socket, select()/poll()
 * fires continuously (EOF is always "readable"), and a naive event loop
 * spins at 100% CPU. Then verifies that recv(MSG_PEEK) correctly detects
 * the dead connection.
 *
 * No hardware, spacenavd, or FreeCAD required — uses socketpair().
 *
 * Build:  gcc -o test_spnav_disconnect test_spnav_disconnect.c
 * Run:    ./test_spnav_disconnect
 *
 * Expected output: all 5 tests PASS.
 */

#include <errno.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

/* ---------- helpers ---------- */

static int passed = 0;
static int failed = 0;

#define TEST(name, cond)                                        \
    do {                                                        \
        if (cond) {                                             \
            printf("  PASS: %s\n", name);                       \
            passed++;                                           \
        }                                                       \
        else {                                                  \
            printf("  FAIL: %s\n", name);                       \
            failed++;                                           \
        }                                                       \
    } while (0)

/* Count how many times select() reports the fd as readable within a
 * short time window (ms). A healthy idle socket: 0. EOF socket: thousands. */
static int count_select_wakeups(int fd, int duration_ms)
{
    int count = 0;
    struct timeval start, now;
    gettimeofday(&start, NULL);

    for (;;) {
        gettimeofday(&now, NULL);
        long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000
                        + (now.tv_usec - start.tv_usec) / 1000;
        if (elapsed_ms >= duration_ms) {
            break;
        }

        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(fd, &rfds);

        /* Zero timeout = non-blocking check */
        struct timeval tv = {0, 0};
        int ret = select(fd + 1, &rfds, NULL, NULL, &tv);
        if (ret > 0 && FD_ISSET(fd, &rfds)) {
            count++;
        }
    }
    return count;
}

/* Simulate spnav_poll_event(): try to read but don't consume real data.
 * Returns 1 if an "event" was available, 0 otherwise — same as libspnav. */
static int fake_spnav_poll_event(int fd)
{
    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(fd, &rfds);
    struct timeval tv = {0, 0};

    if (select(fd + 1, &rfds, NULL, NULL, &tv) > 0) {
        char buf[64];
        ssize_t n = recv(fd, buf, sizeof(buf), MSG_DONTWAIT);
        if (n > 0) {
            return 1;  /* Got an event */
        }
        /* n == 0 (EOF) or n < 0 (error): libspnav returns 0 here too */
    }
    return 0;
}

/* ---------- tests ---------- */

/*
 * Test 1: Prove that select() fires continuously on an EOF socket.
 *         This is the root cause of the 100% CPU bug.
 */
static void test_eof_causes_busy_loop(void)
{
    printf("\nTest 1: EOF causes select() busy loop (the bug)\n");

    int sv[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) < 0) {
        perror("socketpair");
        failed++;
        return;
    }

    int client_fd = sv[0];  /* "FreeCAD" side */
    int server_fd = sv[1];  /* "spacenavd" side */

    /* Before close: idle socket, select should NOT fire */
    int wakeups_before = count_select_wakeups(client_fd, 50);
    TEST("idle socket: select does not fire", wakeups_before == 0);

    /* Simulate spacenavd dying */
    close(server_fd);

    /* After close: EOF socket, select fires on every call */
    int wakeups_after = count_select_wakeups(client_fd, 50);
    TEST("EOF socket: select fires continuously (>1000 wakeups in 50ms)",
         wakeups_after > 1000);

    close(client_fd);
}

/*
 * Test 2: Prove that a naive poll loop (like FreeCAD's pollSpacenav)
 *         cannot distinguish EOF from "no events".
 */
static void test_poll_event_blind_to_eof(void)
{
    printf("\nTest 2: spnav_poll_event() is blind to EOF\n");

    int sv[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sv);
    int client_fd = sv[0];

    /* Close the server side → EOF */
    close(sv[1]);

    /* fake_spnav_poll_event returns 0 for both "no events" and "EOF" */
    int result = fake_spnav_poll_event(client_fd);
    TEST("spnav_poll_event returns 0 on EOF (same as 'no events')", result == 0);

    close(client_fd);
}

/*
 * Test 3: Prove that recv(MSG_PEEK) correctly detects EOF.
 *         This is the core of our fix.
 */
static void test_recv_peek_detects_eof(void)
{
    printf("\nTest 3: recv(MSG_PEEK) detects EOF (the fix)\n");

    int sv[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sv);
    int client_fd = sv[0];

    /* Close the server side → EOF */
    close(sv[1]);

    char buf;
    ssize_t ret = recv(client_fd, &buf, 1, MSG_PEEK | MSG_DONTWAIT);
    TEST("recv(MSG_PEEK) returns 0 on EOF", ret == 0);

    close(client_fd);
}

/*
 * Test 4: Prove that recv(MSG_PEEK) does NOT false-positive on a
 *         healthy idle socket.
 */
static void test_recv_peek_no_false_positive(void)
{
    printf("\nTest 4: recv(MSG_PEEK) does not false-positive on healthy socket\n");

    int sv[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sv);

    char buf;
    ssize_t ret = recv(sv[0], &buf, 1, MSG_PEEK | MSG_DONTWAIT);
    TEST("recv(MSG_PEEK) returns -1/EAGAIN on healthy idle socket",
         ret == -1 && (errno == EAGAIN || errno == EWOULDBLOCK));

    close(sv[0]);
    close(sv[1]);
}

/*
 * Test 5: Full integration — simulate pollSpacenav() with the fix applied.
 *         After EOF, the "notifier" is disabled and the loop stops.
 */
static void test_full_fix_integration(void)
{
    printf("\nTest 5: Full fix integration — EOF detected, notifier disabled\n");

    int sv[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sv);
    int client_fd = sv[0];

    /* Send one "event" from the server side, then close */
    const char fake_event[] = "MOTION";
    write(sv[1], fake_event, sizeof(fake_event));
    close(sv[1]);

    /* --- Simulated pollSpacenav() with fix --- */
    int notifier_enabled = 1;
    int events_processed = 0;
    int disconnect_detected = 0;
    int poll_calls = 0;

    while (notifier_enabled && poll_calls < 100) {
        poll_calls++;

        /* Check if select says "readable" (simulates QSocketNotifier) */
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(client_fd, &rfds);
        struct timeval tv = {0, 0};
        if (select(client_fd + 1, &rfds, NULL, NULL, &tv) <= 0) {
            break;  /* Nothing to do */
        }

        /* --- pollSpacenav() body with fix --- */
        int got_event = 0;

        /* Drain loop (like FreeCAD's while(spnav_poll_event)) */
        char buf[64];
        ssize_t n;
        while ((n = recv(client_fd, buf, sizeof(buf), MSG_DONTWAIT)) > 0) {
            got_event = 1;
            events_processed++;
        }

        /* THE FIX: check for EOF after empty poll */
        if (!got_event) {
            char peek;
            ssize_t ret = recv(client_fd, &peek, 1, MSG_PEEK | MSG_DONTWAIT);
            if (ret == 0 || (ret < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
                /* EOF — spacenavd disconnected */
                disconnect_detected = 1;
                notifier_enabled = 0;  /* Disable "QSocketNotifier" */
            }
        }
    }

    /* The event was processed */
    TEST("event processed before disconnect", events_processed > 0);

    /* The disconnect was detected (not stuck in infinite loop) */
    TEST("disconnect detected via recv(MSG_PEEK)", disconnect_detected == 1);

    /* The loop ended quickly (not 100 iterations = would be stuck) */
    TEST("loop ended after few iterations (not stuck)", poll_calls < 10);

    close(client_fd);
}

/* ---------- main ---------- */

int main(void)
{
    printf("=== spnav disconnect reproducer (FreeCAD #17809) ===\n");
    printf("Verifies the bug and the recv(MSG_PEEK) fix without hardware.\n");

    test_eof_causes_busy_loop();
    test_poll_event_blind_to_eof();
    test_recv_peek_detects_eof();
    test_recv_peek_no_false_positive();
    test_full_fix_integration();

    printf("\n=== Results: %d passed, %d failed ===\n", passed, failed);
    return failed > 0 ? 1 : 0;
}
