/* Tests for scroll_acc_reset() and scroll_acc_consume(). */

#include "spacemouse-core.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
	struct scroll_acc sa;

	/* Reset zeros all three components. */
	sa.acc_x = 7.5; sa.acc_y = -3.2; sa.acc_z = 0.9;
	scroll_acc_reset(&sa);
	assert(sa.acc_x == 0.0);
	assert(sa.acc_y == 0.0);
	assert(sa.acc_z == 0.0);

	/* consume returns the integer part and leaves the fractional remainder.
	 * This is how the daemon emits discrete wheel ticks while preserving
	 * sub-tick accumulation across iterations. */
	double acc = 2.7;
	assert(scroll_acc_consume(&acc) == 2);
	assert(acc > 0.69 && acc < 0.71);

	/* Repeated calls keep draining as the accumulator grows. */
	acc = 0.4;
	assert(scroll_acc_consume(&acc) == 0);
	assert(acc > 0.39 && acc < 0.41);
	acc += 0.7;       /* 1.1 total */
	assert(scroll_acc_consume(&acc) == 1);
	assert(acc > 0.09 && acc < 0.11);

	/* Negative accumulation works symmetrically — needed for reverse
	 * scroll directions. (int) cast truncates toward zero in C99+, so
	 * -2.7 → -2 with remainder -0.7. */
	acc = -2.7;
	assert(scroll_acc_consume(&acc) == -2);
	assert(acc > -0.71 && acc < -0.69);

	/* Sub-unit values never emit a tick but accumulate. */
	acc = 0.0;
	for (int i = 0; i < 10; i++) {
		acc += 0.05;
		assert(scroll_acc_consume(&acc) == 0);
	}
	/* 10 * 0.05 = 0.5, still no tick. */
	assert(acc > 0.49 && acc < 0.51);

	/* Twenty more pushes it past 1.0 and emits exactly one tick. */
	for (int i = 0; i < 11; i++)
		acc += 0.05;
	/* acc now ≈ 1.05 */
	assert(scroll_acc_consume(&acc) == 1);

	printf("test_scroll_acc: all assertions passed\n");
	return 0;
}
