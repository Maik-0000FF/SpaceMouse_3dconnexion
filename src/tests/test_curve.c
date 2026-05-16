/* Tests for apply_curve() — the non-linear axis response. */

#include "spacemouse-core.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>

static int near(double a, double b)
{
	return fabs(a - b) < 1e-9;
}

int main(void)
{
	/* Inside the deadzone (strict less-than): returns exactly 0. */
	assert(apply_curve(0, 15, 2.0, 1.0) == 0.0);
	assert(apply_curve(14, 15, 2.0, 1.0) == 0.0);
	assert(apply_curve(-14, 15, 2.0, 1.0) == 0.0);

	/* Exactly at the deadzone boundary the curve becomes active.
	 * norm = (15 - 15) / (350 - 15) = 0, output = 0 * scale = 0. */
	assert(apply_curve(15, 15, 2.0, 1.0) == 0.0);

	/* Symmetry: negative input produces negative output of equal magnitude. */
	double pos = apply_curve(200, 15, 2.0, 1.0);
	double neg = apply_curve(-200, 15, 2.0, 1.0);
	assert(near(pos, -neg));
	assert(pos > 0);

	/* At full deflection (raw == 350) the curve saturates: norm = 1,
	 * 1^exp = 1, output = scale. */
	assert(near(apply_curve(350, 15, 2.0, 3.0), 3.0));
	assert(near(apply_curve(-350, 15, 2.0, 3.0), -3.0));

	/* Above full deflection is clamped to scale. */
	assert(near(apply_curve(9999, 15, 2.0, 3.0), 3.0));

	/* Exponent shape: at midpoint (raw=183, deadzone=15 → norm≈0.5),
	 * exponent=1 (linear) gives larger magnitude than exponent=2 (squared). */
	double lin  = apply_curve(183, 15, 1.0, 1.0);
	double quad = apply_curve(183, 15, 2.0, 1.0);
	assert(lin > quad);

	/* Zero deadzone is allowed and shifts the curve to start at 0. */
	assert(near(apply_curve(350, 0, 1.0, 1.0), 1.0));

	printf("test_curve: all assertions passed\n");
	return 0;
}
