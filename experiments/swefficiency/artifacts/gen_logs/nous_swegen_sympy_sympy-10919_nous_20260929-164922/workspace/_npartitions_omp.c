/*
 * Parallelized npartitions(n) using MPFR + OpenMP.
 *
 * Strategy: three phases
 * 1. Serial: compute all d_q values and determine precision schedule
 * 2. Parallel (OpenMP): compute all a_q values using known precisions
 * 3. Serial: accumulate s = sum(a_q * d_q)
 *
 * This eliminates ALL Python overhead and parallelizes the dominant
 * _a computation (66% of runtime) across available CPU cores.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpfr.h>
#include <gmp.h>
#ifdef _OPENMP
#include <omp.h>
#endif

/* Dedekind sum: D(h,k) = 12*k*s(h,k) */
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

/* Coprime data */
typedef struct {
    long *h_paired;
    long *D_paired;
    int n_paired;
    long h_unpaired;
    long D_unpaired;
    int has_unpaired;
} coprime_entry_t;

/* Per-term result */
typedef struct {
    mpfr_t value;  /* The _a or _d value as mpfr */
    long prec;     /* precision used */
} term_result_t;

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
    long num_terms = M - 1;  /* q runs from 1 to M-1 */

    /* === Precompute coprime data === */
    coprime_entry_t *coprime = (coprime_entry_t*)calloc(M, sizeof(coprime_entry_t));
    for (long j = 2; j < M; j++) {
        long half_j = (j - 1) / 2;
        int cnt = 0;
        for (long h = 1; h <= half_j; h++)
            if (gcd_l(h, j) == 1) cnt++;

        if (j == 2) {
            coprime[j].n_paired = 0;
            coprime[j].h_paired = NULL;
            coprime[j].D_paired = NULL;
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

    /* Precompute high-precision constants (at max precision + guard) */
    long max_wp = prec + 50;

    mpfr_t pi, sq23pi, sqrt8, b_val, sqrtb;
    mpfr_init2(pi, max_wp);
    mpfr_init2(sq23pi, max_wp);
    mpfr_init2(sqrt8, max_wp);
    mpfr_init2(b_val, max_wp);
    mpfr_init2(sqrtb, max_wp);

    mpfr_const_pi(pi, MPFR_RNDN);
    {
        mpfr_t t;
        mpfr_init2(t, max_wp);
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
        mpfr_t t;
        mpfr_init2(t, max_wp);
        mpfr_set_ui(t, 1, MPFR_RNDN);
        mpfr_div_ui(t, t, 24, MPFR_RNDN);
        mpfr_sub(b_val, b_val, t, MPFR_RNDN);
        mpfr_clear(t);
    }
    mpfr_sqrt(sqrtb, b_val, MPFR_RNDN);

    /* Allocate arrays for d values and precision schedule */
    mpfr_t *d_vals = (mpfr_t*)malloc(num_terms * sizeof(mpfr_t));
    long *p_schedule = (long*)malloc(num_terms * sizeof(long));

    for (long i = 0; i < num_terms; i++) {
        mpfr_init2(d_vals[i], prec + 100);
    }

    /* === Phase 1: Serial — compute all d_q and precision schedule === */
    long p = prec;
    long neg24n = -24 * n;

    for (long i = 0; i < num_terms; i++) {
        long q = i + 1;
        p_schedule[i] = p;

        long wp = p + 50;
        mpfr_t j_m, a_d, ac, ch, sh, D_d, E_d, tmp;
        mpfr_init2(j_m, wp);
        mpfr_init2(a_d, wp);
        mpfr_init2(ac, wp);
        mpfr_init2(ch, wp);
        mpfr_init2(sh, wp);
        mpfr_init2(D_d, wp);
        mpfr_init2(E_d, wp);
        mpfr_init2(tmp, wp);

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
        mpfr_mul(d_vals[i], D_d, E_d, MPFR_RNDN);

        /* Precision reduction: p = bitcount(|int(d)|) + 50 */
        mpz_t z_d;
        mpz_init(z_d);
        mpfr_get_z(z_d, d_vals[i], MPFR_RNDZ);
        mpz_abs(z_d, z_d);
        size_t bits = (mpz_sgn(z_d) == 0) ? 0 : mpz_sizeinbase(z_d, 2);
        p = (long)bits + 50;
        mpz_clear(z_d);

        mpfr_clear(j_m); mpfr_clear(a_d); mpfr_clear(ac);
        mpfr_clear(ch); mpfr_clear(sh);
        mpfr_clear(D_d); mpfr_clear(E_d); mpfr_clear(tmp);
    }

    /* === Phase 2: Parallel — compute all a_q === */
    mpfr_t *a_vals = (mpfr_t*)malloc(num_terms * sizeof(mpfr_t));
    for (long i = 0; i < num_terms; i++) {
        mpfr_init2(a_vals[i], prec + 100);
    }

    /* q=1 is special: a = 1 */
    mpfr_set_ui(a_vals[0], 1, MPFR_RNDN);

    #pragma omp parallel for schedule(dynamic, 4)
    for (long i = 1; i < num_terms; i++) {
        long q = i + 1;
        long p_q = p_schedule[i];
        coprime_entry_t *ce = &coprime[q];

        if (p_q <= 53) {
            /* Float path */
            double fac = M_PI / (12.0 * q);
            double fsum = 0.0;
            for (int k = 0; k < ce->n_paired; k++) {
                fsum += cos(fac * ((double)ce->D_paired[k] + (double)neg24n * (double)ce->h_paired[k]));
            }
            fsum *= 2.0;
            if (ce->has_unpaired) {
                fsum += cos(fac * ((double)ce->D_unpaired + (double)neg24n * (double)ce->h_unpaired));
            }
            mpfr_set_d(a_vals[i], fsum, MPFR_RNDN);
        } else {
            /* MPFR cos path */
            long wp = p_q + 10;
            mpfr_t factor, cos_v, cos_sum_v, tmp_v;
            mpfr_init2(factor, wp);
            mpfr_init2(cos_v, wp);
            mpfr_init2(cos_sum_v, wp);
            mpfr_init2(tmp_v, wp);

            mpfr_const_pi(factor, MPFR_RNDN);
            mpfr_div_ui(factor, factor, (unsigned long)(12 * q), MPFR_RNDN);
            mpfr_set_zero(cos_sum_v, 1);

            for (int k = 0; k < ce->n_paired; k++) {
                mpfr_set_si(tmp_v, neg24n, MPFR_RNDN);
                mpfr_mul_si(tmp_v, tmp_v, ce->h_paired[k], MPFR_RNDN);
                mpfr_add_si(tmp_v, tmp_v, ce->D_paired[k], MPFR_RNDN);
                mpfr_mul(tmp_v, factor, tmp_v, MPFR_RNDN);
                mpfr_cos(cos_v, tmp_v, MPFR_RNDN);
                mpfr_add(cos_sum_v, cos_sum_v, cos_v, MPFR_RNDN);
            }
            mpfr_mul_ui(cos_sum_v, cos_sum_v, 2, MPFR_RNDN);

            if (ce->has_unpaired) {
                mpfr_set_si(tmp_v, neg24n, MPFR_RNDN);
                mpfr_mul_si(tmp_v, tmp_v, ce->h_unpaired, MPFR_RNDN);
                mpfr_add_si(tmp_v, tmp_v, ce->D_unpaired, MPFR_RNDN);
                mpfr_mul(tmp_v, factor, tmp_v, MPFR_RNDN);
                mpfr_cos(cos_v, tmp_v, MPFR_RNDN);
                mpfr_add(cos_sum_v, cos_sum_v, cos_v, MPFR_RNDN);
            }

            mpfr_set(a_vals[i], cos_sum_v, MPFR_RNDN);

            mpfr_clear(factor); mpfr_clear(cos_v);
            mpfr_clear(cos_sum_v); mpfr_clear(tmp_v);
        }
    }

    /* === Phase 3: Serial — accumulate s = sum(a_q * d_q) === */
    mpfr_t s, term;
    mpfr_init2(s, prec + 100);
    mpfr_init2(term, prec + 100);
    mpfr_set_zero(s, 1);

    for (long i = 0; i < num_terms; i++) {
        mpfr_mul(term, a_vals[i], d_vals[i], MPFR_RNDN);
        mpfr_add(s, s, term, MPFR_RNDN);
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
    mpfr_clear(s); mpfr_clear(term);
    for (long i = 0; i < num_terms; i++) {
        mpfr_clear(a_vals[i]);
        mpfr_clear(d_vals[i]);
    }
    free(a_vals);
    free(d_vals);
    free(p_schedule);
    mpfr_clear(pi); mpfr_clear(sq23pi); mpfr_clear(sqrt8);
    mpfr_clear(b_val); mpfr_clear(sqrtb);
    for (long j = 2; j < M; j++) {
        free(coprime[j].h_paired);
        free(coprime[j].D_paired);
    }
    free(coprime);

    return 0;
}
