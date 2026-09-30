/*
 * Optimized C npartitions(n) using MPFR.
 *
 * Key optimizations over naive C:
 * 1. Preallocate all mpfr temporaries (no alloc/free in loop)
 * 2. Precompute constants once at max precision
 * 3. Two-phase: serial d, then _a + accumulate in single pass
 * 4. For float-path _a: use hardware cos directly
 * 5. Reuse pi value (computed once, MPFR rounds correctly at lower prec)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpfr.h>
#include <gmp.h>

static long d_dedekind(long h, long k) {
    if (k <= 2) return 0;
    h = h % k;
    if (h < 0) h += k;
    if (h == 0) return 0;
    if (h == 1) return (k - 1) * (k - 2);
    return (h*h + k*k + 1 - 3*h*k - k * d_dedekind(k % h, h)) / h;
}

static long gcd_l(long a, long b) {
    while (b) { long t = b; b = a % b; a = t; }
    return a;
}

typedef struct {
    long *h_paired;
    long *D_paired;
    int n_paired;
    long h_unpaired;
    long D_unpaired;
    int has_unpaired;
} coprime_entry_t;

int npartitions_c(long n, char* out_str, int out_str_size) {
    if (n < 0) { snprintf(out_str, out_str_size, "0"); return 0; }
    if (n <= 5) {
        int vals[] = {1, 1, 2, 3, 5, 7};
        snprintf(out_str, out_str_size, "%d", vals[n]);
        return 0;
    }

    double pbits = (M_PI * sqrt(2.0 * n / 3.0) - log(4.0 * n)) / log(10.0) + 1.0;
    pbits *= log(10.0) / log(2.0);
    long prec = (long)(pbits * 1.1 + 100);
    long M = (long)(0.24 * sqrt((double)n) + 4);
    if (M < 6) M = 6;
    long num_terms = M - 1;
    long neg24n = -24 * n;

    /* Precompute coprime data */
    coprime_entry_t *coprime = (coprime_entry_t*)calloc(M, sizeof(coprime_entry_t));
    for (long j = 2; j < M; j++) {
        long half_j = (j - 1) / 2;
        int cnt = 0;
        for (long h = 1; h <= half_j; h++)
            if (gcd_l(h, j) == 1) cnt++;

        if (j == 2) {
            coprime[j].n_paired = 0;
            coprime[j].has_unpaired = 1;
            coprime[j].h_unpaired = 1;
            coprime[j].D_unpaired = d_dedekind(1, 2);
        } else {
            coprime[j].n_paired = cnt;
            coprime[j].h_paired = (long*)malloc(cnt * sizeof(long));
            coprime[j].D_paired = (long*)malloc(cnt * sizeof(long));
            int idx = 0;
            for (long h = 1; h <= half_j; h++) {
                if (gcd_l(h, j) == 1) {
                    coprime[j].h_paired[idx] = h;
                    coprime[j].D_paired[idx] = d_dedekind(h, j);
                    idx++;
                }
            }
            coprime[j].has_unpaired = 0;
        }
    }

    long max_wp = prec + 50;

    /* Precompute constants at max precision */
    mpfr_t pi, sq23pi, sqrt8, b_val, sqrtb;
    mpfr_init2(pi, max_wp);
    mpfr_init2(sq23pi, max_wp);
    mpfr_init2(sqrt8, max_wp);
    mpfr_init2(b_val, max_wp);
    mpfr_init2(sqrtb, max_wp);

    mpfr_const_pi(pi, MPFR_RNDN);
    {
        mpfr_t t; mpfr_init2(t, max_wp);
        mpfr_set_ui(t, 2, MPFR_RNDN);
        mpfr_div_ui(t, t, 3, MPFR_RNDN);
        mpfr_sqrt(sq23pi, t, MPFR_RNDN);
        mpfr_mul(sq23pi, sq23pi, pi, MPFR_RNDN);
        mpfr_clear(t);
    }
    mpfr_set_ui(sqrt8, 8, MPFR_RNDN);
    mpfr_sqrt(sqrt8, sqrt8, MPFR_RNDN);
    mpfr_set_si(b_val, n, MPFR_RNDN);
    {
        mpfr_t t; mpfr_init2(t, max_wp);
        mpfr_set_ui(t, 1, MPFR_RNDN);
        mpfr_div_ui(t, t, 24, MPFR_RNDN);
        mpfr_sub(b_val, b_val, t, MPFR_RNDN);
        mpfr_clear(t);
    }
    mpfr_sqrt(sqrtb, b_val, MPFR_RNDN);

    /* Preallocate reusable temporaries (avoid alloc/free in loop) */
    mpfr_t d_val, a_val, s, term;
    mpfr_t j_m, a_d, ac, ch, sh, D_d, E_d, tmp, tmp2;
    mpfr_t factor, cos_v, cos_sum_v;

    mpfr_init2(d_val, max_wp);
    mpfr_init2(a_val, max_wp);
    mpfr_init2(s, prec + 100);
    mpfr_init2(term, prec + 100);
    mpfr_init2(j_m, max_wp);
    mpfr_init2(a_d, max_wp);
    mpfr_init2(ac, max_wp);
    mpfr_init2(ch, max_wp);
    mpfr_init2(sh, max_wp);
    mpfr_init2(D_d, max_wp);
    mpfr_init2(E_d, max_wp);
    mpfr_init2(tmp, max_wp);
    mpfr_init2(tmp2, max_wp);
    mpfr_init2(factor, max_wp);
    mpfr_init2(cos_v, max_wp);
    mpfr_init2(cos_sum_v, max_wp);

    mpfr_set_zero(s, 1);
    long p = prec;

    /* Main loop: compute _d, _a, accumulate */
    for (long q = 1; q < M; q++) {
        long wp;

        /* === Compute _a === */
        if (q == 1) {
            mpfr_set_ui(a_val, 1, MPFR_RNDN);
        } else {
            coprime_entry_t *ce = &coprime[q];

            if (p <= 53) {
                double fac = M_PI / (12.0 * q);
                double fsum = 0.0;
                for (int k = 0; k < ce->n_paired; k++) {
                    fsum += cos(fac * ((double)ce->D_paired[k] + (double)neg24n * (double)ce->h_paired[k]));
                }
                fsum *= 2.0;
                if (ce->has_unpaired) {
                    fsum += cos(fac * ((double)ce->D_unpaired + (double)neg24n * (double)ce->h_unpaired));
                }
                mpfr_set_d(a_val, fsum, MPFR_RNDN);
            } else {
                wp = p + 10;
                /* Use preallocated vars — just adjust precision for the cos computation */
                mpfr_set_prec(factor, wp);
                mpfr_set_prec(cos_v, wp);
                mpfr_set_prec(cos_sum_v, wp);
                mpfr_set_prec(tmp, wp);

                mpfr_const_pi(factor, MPFR_RNDN);
                mpfr_div_ui(factor, factor, (unsigned long)(12 * q), MPFR_RNDN);
                mpfr_set_zero(cos_sum_v, 1);

                for (int k = 0; k < ce->n_paired; k++) {
                    mpfr_set_si(tmp, neg24n, MPFR_RNDN);
                    mpfr_mul_si(tmp, tmp, ce->h_paired[k], MPFR_RNDN);
                    mpfr_add_si(tmp, tmp, ce->D_paired[k], MPFR_RNDN);
                    mpfr_mul(tmp, factor, tmp, MPFR_RNDN);
                    mpfr_cos(cos_v, tmp, MPFR_RNDN);
                    mpfr_add(cos_sum_v, cos_sum_v, cos_v, MPFR_RNDN);
                }
                mpfr_mul_ui(cos_sum_v, cos_sum_v, 2, MPFR_RNDN);

                if (ce->has_unpaired) {
                    mpfr_set_si(tmp, neg24n, MPFR_RNDN);
                    mpfr_mul_si(tmp, tmp, ce->h_unpaired, MPFR_RNDN);
                    mpfr_add_si(tmp, tmp, ce->D_unpaired, MPFR_RNDN);
                    mpfr_mul(tmp, factor, tmp, MPFR_RNDN);
                    mpfr_cos(cos_v, tmp, MPFR_RNDN);
                    mpfr_add(cos_sum_v, cos_sum_v, cos_v, MPFR_RNDN);
                }
                mpfr_set(a_val, cos_sum_v, MPFR_RNDN);
            }
        }

        /* === Compute _d === */
        wp = p + 50;
        mpfr_set_prec(j_m, wp);
        mpfr_set_prec(a_d, wp);
        mpfr_set_prec(ac, wp);
        mpfr_set_prec(ch, wp);
        mpfr_set_prec(sh, wp);
        mpfr_set_prec(D_d, wp);
        mpfr_set_prec(E_d, wp);
        mpfr_set_prec(tmp, wp);

        mpfr_set_si(j_m, q, MPFR_RNDN);
        mpfr_div(a_d, sq23pi, j_m, MPFR_RNDN);
        mpfr_mul(ac, a_d, sqrtb, MPFR_RNDN);
        mpfr_cosh(ch, ac, MPFR_RNDN);
        mpfr_sinh(sh, ac, MPFR_RNDN);
        mpfr_sqrt(D_d, j_m, MPFR_RNDN);
        mpfr_mul(tmp, sqrt8, b_val, MPFR_RNDN);
        mpfr_mul(tmp, tmp, pi, MPFR_RNDN);
        mpfr_div(D_d, D_d, tmp, MPFR_RNDN);
        mpfr_mul(E_d, a_d, ch, MPFR_RNDN);
        mpfr_div(tmp, sh, sqrtb, MPFR_RNDN);
        mpfr_sub(E_d, E_d, tmp, MPFR_RNDN);
        mpfr_mul(d_val, D_d, E_d, MPFR_RNDN);

        /* Accumulate: s += a * d */
        mpfr_mul(term, a_val, d_val, MPFR_RNDN);
        mpfr_add(s, s, term, MPFR_RNDN);

        /* Precision reduction */
        {
            mpz_t z_d;
            mpz_init(z_d);
            mpfr_get_z(z_d, d_val, MPFR_RNDZ);
            mpz_abs(z_d, z_d);
            size_t bits = (mpz_sgn(z_d) == 0) ? 0 : mpz_sizeinbase(z_d, 2);
            p = (long)bits + 50;
            mpz_clear(z_d);
        }
    }

    /* Round to nearest integer */
    mpfr_set_d(term, 0.5, MPFR_RNDN);
    mpfr_add(s, s, term, MPFR_RNDN);

    mpz_t result_z;
    mpz_init(result_z);
    mpfr_get_z(result_z, s, MPFR_RNDZ);
    gmp_snprintf(out_str, out_str_size, "%Zd", result_z);

    /* Cleanup */
    mpz_clear(result_z);
    mpfr_clear(d_val); mpfr_clear(a_val); mpfr_clear(s); mpfr_clear(term);
    mpfr_clear(j_m); mpfr_clear(a_d); mpfr_clear(ac);
    mpfr_clear(ch); mpfr_clear(sh);
    mpfr_clear(D_d); mpfr_clear(E_d); mpfr_clear(tmp); mpfr_clear(tmp2);
    mpfr_clear(factor); mpfr_clear(cos_v); mpfr_clear(cos_sum_v);
    mpfr_clear(pi); mpfr_clear(sq23pi); mpfr_clear(sqrt8);
    mpfr_clear(b_val); mpfr_clear(sqrtb);
    for (long j = 2; j < M; j++) {
        free(coprime[j].h_paired);
        free(coprime[j].D_paired);
    }
    free(coprime);

    return 0;
}
