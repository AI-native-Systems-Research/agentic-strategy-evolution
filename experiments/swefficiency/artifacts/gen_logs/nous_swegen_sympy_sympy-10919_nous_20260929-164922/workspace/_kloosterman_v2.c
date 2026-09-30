#include <math.h>
#include <mpfr.h>
#include <gmp.h>
#include <string.h>
#include <stdlib.h>

/*
 * Combined Kloosterman sum helper for npartitions HRR formula.
 *
 * Float path: hardware double cos (prec <= 53)
 * MPFR path: batch MPFR cos (prec > 53)
 *
 * Both paths compute:
 *   2 * sum_{i=0}^{count-1} cos(pi/(12*j) * (D[i] + neg24n*h[i]))
 *   + [optional unpaired term: cos(pi/(12*j) * (D_u + neg24n*h_u))]
 */

/* Float-path: hardware cos */
double kloosterman_sum_float(
    const long* h_vals, const long* D_vals, int count,
    long neg24n, double factor,
    long h_unpaired, long D_unpaired, int has_unpaired)
{
    double sum = 0.0;
    for (int i = 0; i < count; i++) {
        sum += cos(factor * ((double)D_vals[i] + (double)neg24n * (double)h_vals[i]));
    }
    sum *= 2.0;
    if (has_unpaired) {
        sum += cos(factor * ((double)D_unpaired + (double)neg24n * (double)h_unpaired));
    }
    return sum;
}

/*
 * MPFR batch Kloosterman sum.
 *
 * Computes the sum in MPFR at working precision wp = prec + 10.
 * Returns the result as mantissa (written to out_mantissa) and exponent.
 *
 * The mantissa is written as a decimal string via gmp_snprintf.
 * Result semantics: mantissa * 2^exponent
 *
 * Returns 0 on success.
 */
int kloosterman_sum_mpfr(
    const long* h_vals, const long* D_vals, int count,
    long neg24n, int j_val, int prec,
    long h_unpaired, long D_unpaired, int has_unpaired,
    char* out_mantissa, int out_mantissa_size, long* out_exponent)
{
    int wp = prec + 10;
    mpfr_t sum, pi, factor, val, cosval;

    mpfr_init2(sum, wp);
    mpfr_init2(pi, wp);
    mpfr_init2(factor, wp);
    mpfr_init2(val, wp);
    mpfr_init2(cosval, wp);

    mpfr_set_zero(sum, 1);
    mpfr_const_pi(pi, MPFR_RNDN);
    /* factor = pi / (12 * j) */
    mpfr_div_ui(factor, pi, (unsigned long)(12 * j_val), MPFR_RNDN);

    for (int i = 0; i < count; i++) {
        /* val = factor * (D[i] + neg24n * h[i]) */
        mpfr_set_si(val, neg24n, MPFR_RNDN);
        mpfr_mul_si(val, val, h_vals[i], MPFR_RNDN);
        mpfr_add_si(val, val, D_vals[i], MPFR_RNDN);
        mpfr_mul(val, factor, val, MPFR_RNDN);
        mpfr_cos(cosval, val, MPFR_RNDN);
        mpfr_add(sum, sum, cosval, MPFR_RNDN);
    }

    mpfr_mul_ui(sum, sum, 2, MPFR_RNDN);

    if (has_unpaired) {
        mpfr_set_si(val, neg24n, MPFR_RNDN);
        mpfr_mul_si(val, val, h_unpaired, MPFR_RNDN);
        mpfr_add_si(val, val, D_unpaired, MPFR_RNDN);
        mpfr_mul(val, factor, val, MPFR_RNDN);
        mpfr_cos(cosval, val, MPFR_RNDN);
        mpfr_add(sum, sum, cosval, MPFR_RNDN);
    }

    /* Export as integer mantissa * 2^exponent */
    mpz_t z;
    mpz_init(z);
    mpfr_exp_t z_exp = mpfr_get_z_2exp(z, sum);

    gmp_snprintf(out_mantissa, out_mantissa_size, "%Zd", z);
    *out_exponent = (long)z_exp;

    mpz_clear(z);
    mpfr_clear(sum);
    mpfr_clear(pi);
    mpfr_clear(factor);
    mpfr_clear(val);
    mpfr_clear(cosval);

    return 0;
}

/*
 * Batch compute _d (sinh term) using MPFR.
 *
 * d(n, j, prec) = D * E where:
 *   a = sqrt(2/3) * pi / j
 *   b = n - 1/24
 *   c = sqrt(b)
 *   ch, sh = cosh(a*c), sinh(a*c)
 *   D = sqrt(j) / (sqrt(8) * b * pi)
 *   E = a * ch - sh/c
 *   result = D * E
 *
 * Returns mantissa * 2^exponent.
 */
int compute_d_mpfr(
    int n, int j_val, int prec,
    char* out_mantissa, int out_mantissa_size, long* out_exponent)
{
    int wp = prec + 50;
    mpfr_t pi, sq23pi, sqrt8, j_m, a, b, c, ch, sh, D, E, result;
    mpfr_t two, three, eight, one, twentyfour, n_m;

    mpfr_init2(pi, wp);
    mpfr_init2(sq23pi, wp);
    mpfr_init2(sqrt8, wp);
    mpfr_init2(j_m, wp);
    mpfr_init2(a, wp);
    mpfr_init2(b, wp);
    mpfr_init2(c, wp);
    mpfr_init2(ch, wp);
    mpfr_init2(sh, wp);
    mpfr_init2(D, wp);
    mpfr_init2(E, wp);
    mpfr_init2(result, wp);
    mpfr_init2(two, wp);
    mpfr_init2(three, wp);
    mpfr_init2(eight, wp);
    mpfr_init2(one, wp);
    mpfr_init2(twentyfour, wp);
    mpfr_init2(n_m, wp);

    mpfr_const_pi(pi, MPFR_RNDN);
    mpfr_set_ui(two, 2, MPFR_RNDN);
    mpfr_set_ui(three, 3, MPFR_RNDN);
    mpfr_set_ui(eight, 8, MPFR_RNDN);
    mpfr_set_ui(one, 1, MPFR_RNDN);
    mpfr_set_ui(twentyfour, 24, MPFR_RNDN);
    mpfr_set_si(n_m, n, MPFR_RNDN);

    /* sq23pi = sqrt(2/3) * pi */
    mpfr_div(sq23pi, two, three, MPFR_RNDN);
    mpfr_sqrt(sq23pi, sq23pi, MPFR_RNDN);
    mpfr_mul(sq23pi, sq23pi, pi, MPFR_RNDN);

    /* sqrt8 = sqrt(8) */
    mpfr_sqrt(sqrt8, eight, MPFR_RNDN);

    /* j_m = j */
    mpfr_set_si(j_m, j_val, MPFR_RNDN);

    /* a = sq23pi / j */
    mpfr_div(a, sq23pi, j_m, MPFR_RNDN);

    /* b = n - 1/24 */
    mpfr_div(b, one, twentyfour, MPFR_RNDN);
    mpfr_sub(b, n_m, b, MPFR_RNDN);

    /* c = sqrt(b) */
    mpfr_sqrt(c, b, MPFR_RNDN);

    /* ch = cosh(a*c), sh = sinh(a*c) */
    mpfr_mul(E, a, c, MPFR_RNDN); /* reuse E as temp */
    mpfr_cosh(ch, E, MPFR_RNDN);
    mpfr_sinh(sh, E, MPFR_RNDN);

    /* D = sqrt(j) / (sqrt8 * b * pi) */
    mpfr_sqrt(D, j_m, MPFR_RNDN);
    mpfr_mul(E, sqrt8, b, MPFR_RNDN);
    mpfr_mul(E, E, pi, MPFR_RNDN);
    mpfr_div(D, D, E, MPFR_RNDN);

    /* E = a * ch - sh/c */
    mpfr_mul(E, a, ch, MPFR_RNDN);
    mpfr_div(result, sh, c, MPFR_RNDN);
    mpfr_sub(E, E, result, MPFR_RNDN);

    /* result = D * E */
    mpfr_mul(result, D, E, MPFR_RNDN);

    /* Export */
    mpz_t z;
    mpz_init(z);
    mpfr_exp_t z_exp = mpfr_get_z_2exp(z, result);
    gmp_snprintf(out_mantissa, out_mantissa_size, "%Zd", z);
    *out_exponent = (long)z_exp;

    mpz_clear(z);
    mpfr_clear(pi);  mpfr_clear(sq23pi); mpfr_clear(sqrt8);
    mpfr_clear(j_m); mpfr_clear(a);      mpfr_clear(b);
    mpfr_clear(c);   mpfr_clear(ch);     mpfr_clear(sh);
    mpfr_clear(D);   mpfr_clear(E);      mpfr_clear(result);
    mpfr_clear(two); mpfr_clear(three);  mpfr_clear(eight);
    mpfr_clear(one); mpfr_clear(twentyfour); mpfr_clear(n_m);

    return 0;
}
