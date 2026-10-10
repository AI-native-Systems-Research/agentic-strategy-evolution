#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpfr.h>
#include <gmp.h>

/* Float-path helper (hardware cos) */
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
 * Computes: 2 * sum(cos(pi/(12*j) * (D[i] + neg24n * h[i]))) + [unpaired cos]
 *
 * Returns mantissa string in out_mantissa buffer, exponent in out_exponent.
 * Result is mantissa * 2^exponent.
 */
void kloosterman_sum_mpfr(
    const long* h_vals, const long* D_vals, int count,
    long neg24n, int j_val, int prec,
    long h_unpaired, long D_unpaired, int has_unpaired,
    char* out_mantissa, int out_mantissa_size, long* out_exponent)
{
    mpfr_t sum, pi, factor, val, cosval;
    int wp = prec + 10;

    mpfr_init2(sum, wp);
    mpfr_init2(pi, wp);
    mpfr_init2(factor, wp);
    mpfr_init2(val, wp);
    mpfr_init2(cosval, wp);

    mpfr_set_zero(sum, 1);
    mpfr_const_pi(pi, MPFR_RNDN);
    mpfr_div_ui(factor, pi, (unsigned long)(12 * j_val), MPFR_RNDN);

    for (int i = 0; i < count; i++) {
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
}

int main() {
    long h[] = {1, 3, 7, 9};
    long D[] = {0, 12, -8, 4};
    char mant[2048];
    long exp;
    kloosterman_sum_mpfr(h, D, 4, -24000000, 10, 100, 0, 0, 0, mant, 2048, &exp);
    printf("mantissa=%s, exp=%ld\n", mant, exp);

    double r = kloosterman_sum_float(h, D, 4, -24000000, 3.14159265358979/(12.0*10), 0, 0, 0);
    printf("float result=%f\n", r);
    return 0;
}
