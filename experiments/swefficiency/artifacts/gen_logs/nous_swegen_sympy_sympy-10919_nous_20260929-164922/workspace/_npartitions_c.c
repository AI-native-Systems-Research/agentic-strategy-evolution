/*
 * Complete C implementation of npartitions(n) using MPFR.
 * Eliminates ALL Python loop overhead for the HRR formula.
 *
 * Algorithm: Hardy-Ramanujan-Rademacher formula with:
 *   - Dedekind sum via reciprocity (O(log k))
 *   - Hardware double cos for prec <= 53
 *   - MPFR cos for prec > 53
 *   - Dynamic precision reduction
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpfr.h>
#include <gmp.h>

/* Dedekind sum: D(h,k) = 12*k*s(h,k) */
static long d_dedekind(long h, long k) {
    if (k <= 2) return 0;
    h = h % k;
    if (h < 0) h += k;
    if (h == 0) return 0;
    if (h == 1) return (k - 1) * (k - 2);
    return (h*h + k*k + 1 - 3*h*k - k * d_dedekind(k % h, h)) / h;
}

/* GCD */
static long gcd(long a, long b) {
    while (b) { long t = b; b = a % b; a = t; }
    return a;
}

/* Coprime data for a single j */
typedef struct {
    long *h_paired;  /* h values for paired terms */
    long *D_paired;  /* D values for paired terms */
    int n_paired;
    long h_unpaired; /* unpaired h (for j=2) */
    long D_unpaired; /* unpaired D (for j=2) */
    int has_unpaired;
} coprime_entry_t;

/*
 * npartitions_c(n, out_str, out_str_size)
 *
 * Compute p(n) and write the result as a decimal string to out_str.
 * Returns 0 on success.
 */
int npartitions_c(long n, char* out_str, int out_str_size) {
    if (n < 0) {
        snprintf(out_str, out_str_size, "0");
        return 0;
    }
    if (n <= 5) {
        int vals[] = {1, 1, 2, 3, 5, 7};
        snprintf(out_str, out_str_size, "%d", vals[n]);
        return 0;
    }

    /* Estimate precision */
    double pbits = (M_PI * sqrt(2.0 * n / 3.0) - log(4.0 * n)) / log(10.0) + 1.0;
    pbits *= log(10.0) / log(2.0);
    long prec = (long)(pbits * 1.1 + 100);
    long p = prec;
    long M = (long)(0.24 * sqrt((double)n) + 4);
    if (M < 6) M = 6;

    /* Precompute coprime data */
    coprime_entry_t *coprime = (coprime_entry_t*)calloc(M, sizeof(coprime_entry_t));
    for (long j = 2; j < M; j++) {
        long half_j = (j - 1) / 2;
        /* Count coprimes first */
        int cnt = 0;
        for (long h = 1; h <= half_j; h++) {
            if (gcd(h, j) == 1) cnt++;
        }

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
                if (gcd(h, j) == 1) {
                    coprime[j].h_paired[idx] = h;
                    coprime[j].D_paired[idx] = d_dedekind(h, j);
                    idx++;
                }
            }
            coprime[j].has_unpaired = 0;
        }
    }

    /* Initialize MPFR accumulator */
    mpfr_t s, a_val, d_val, tmp, tmp2;
    mpfr_t pi, sq23pi, sqrt8, b, sqrtb;
    mpfr_t factor, cos_val, cos_sum;
    mpfr_t j_mpfr, a_d, ac, ch_val, sh_val, D_d, E_d, result_d;

    mpfr_init2(s, prec + 100);
    mpfr_init2(a_val, prec + 100);
    mpfr_init2(d_val, prec + 100);
    mpfr_init2(tmp, prec + 100);
    mpfr_init2(tmp2, prec + 100);

    /* These get re-initialized per precision level */
    mpfr_init2(pi, prec + 100);
    mpfr_init2(sq23pi, prec + 100);
    mpfr_init2(sqrt8, prec + 100);
    mpfr_init2(b, prec + 100);
    mpfr_init2(sqrtb, prec + 100);
    mpfr_init2(factor, prec + 100);
    mpfr_init2(cos_val, prec + 100);
    mpfr_init2(cos_sum, prec + 100);
    mpfr_init2(j_mpfr, prec + 100);
    mpfr_init2(a_d, prec + 100);
    mpfr_init2(ac, prec + 100);
    mpfr_init2(ch_val, prec + 100);
    mpfr_init2(sh_val, prec + 100);
    mpfr_init2(D_d, prec + 100);
    mpfr_init2(E_d, prec + 100);
    mpfr_init2(result_d, prec + 100);

    /* Precompute constants at max precision */
    long max_wp = prec + 50;
    mpfr_set_prec(pi, max_wp);
    mpfr_set_prec(sq23pi, max_wp);
    mpfr_set_prec(sqrt8, max_wp);
    mpfr_set_prec(b, max_wp);
    mpfr_set_prec(sqrtb, max_wp);

    mpfr_const_pi(pi, MPFR_RNDN);
    /* sq23pi = sqrt(2/3) * pi */
    mpfr_set_ui(tmp, 2, MPFR_RNDN);
    mpfr_div_ui(tmp, tmp, 3, MPFR_RNDN);
    mpfr_sqrt(sq23pi, tmp, MPFR_RNDN);
    mpfr_mul(sq23pi, sq23pi, pi, MPFR_RNDN);
    /* sqrt8 */
    mpfr_set_ui(sqrt8, 8, MPFR_RNDN);
    mpfr_sqrt(sqrt8, sqrt8, MPFR_RNDN);
    /* b = n - 1/24 */
    mpfr_set_si(b, n, MPFR_RNDN);
    mpfr_set_ui(tmp, 1, MPFR_RNDN);
    mpfr_div_ui(tmp, tmp, 24, MPFR_RNDN);
    mpfr_sub(b, b, tmp, MPFR_RNDN);
    /* sqrtb = sqrt(b) */
    mpfr_sqrt(sqrtb, b, MPFR_RNDN);

    mpfr_set_zero(s, 1);
    long neg24n = -24 * n;

    for (long q = 1; q < M; q++) {
        long wp;

        /* === Compute _a(n, q, p) === */
        if (q == 1) {
            mpfr_set_ui(a_val, 1, MPFR_RNDN);
        } else {
            coprime_entry_t *ce = &coprime[q];

            if (p <= 53) {
                /* Float path: hardware cos */
                double fac = M_PI / (12.0 * q);
                double fsum = 0.0;
                for (int i = 0; i < ce->n_paired; i++) {
                    fsum += cos(fac * ((double)ce->D_paired[i] + (double)neg24n * (double)ce->h_paired[i]));
                }
                fsum *= 2.0;
                if (ce->has_unpaired) {
                    fsum += cos(fac * ((double)ce->D_unpaired + (double)neg24n * (double)ce->h_unpaired));
                }
                if (fsum == 0.0) {
                    mpfr_set_zero(a_val, 1);
                } else {
                    mpfr_set_d(a_val, fsum, MPFR_RNDN);
                }
            } else {
                /* MPFR cos path */
                wp = p + 10;
                mpfr_set_prec(factor, wp);
                mpfr_set_prec(cos_val, wp);
                mpfr_set_prec(cos_sum, wp);
                mpfr_set_prec(tmp, wp);

                mpfr_const_pi(factor, MPFR_RNDN);
                mpfr_div_ui(factor, factor, (unsigned long)(12 * q), MPFR_RNDN);

                mpfr_set_zero(cos_sum, 1);
                for (int i = 0; i < ce->n_paired; i++) {
                    mpfr_set_si(tmp, neg24n, MPFR_RNDN);
                    mpfr_mul_si(tmp, tmp, ce->h_paired[i], MPFR_RNDN);
                    mpfr_add_si(tmp, tmp, ce->D_paired[i], MPFR_RNDN);
                    mpfr_mul(tmp, factor, tmp, MPFR_RNDN);
                    mpfr_cos(cos_val, tmp, MPFR_RNDN);
                    mpfr_add(cos_sum, cos_sum, cos_val, MPFR_RNDN);
                }
                mpfr_mul_ui(cos_sum, cos_sum, 2, MPFR_RNDN);

                if (ce->has_unpaired) {
                    mpfr_set_si(tmp, neg24n, MPFR_RNDN);
                    mpfr_mul_si(tmp, tmp, ce->h_unpaired, MPFR_RNDN);
                    mpfr_add_si(tmp, tmp, ce->D_unpaired, MPFR_RNDN);
                    mpfr_mul(tmp, factor, tmp, MPFR_RNDN);
                    mpfr_cos(cos_val, tmp, MPFR_RNDN);
                    mpfr_add(cos_sum, cos_sum, cos_val, MPFR_RNDN);
                }

                mpfr_set(a_val, cos_sum, MPFR_RNDN);
            }
        }

        /* === Compute _d(n, q, p) === */
        wp = p + 50;
        mpfr_set_prec(j_mpfr, wp);
        mpfr_set_prec(a_d, wp);
        mpfr_set_prec(ac, wp);
        mpfr_set_prec(ch_val, wp);
        mpfr_set_prec(sh_val, wp);
        mpfr_set_prec(D_d, wp);
        mpfr_set_prec(E_d, wp);
        mpfr_set_prec(result_d, wp);
        mpfr_set_prec(tmp, wp);
        mpfr_set_prec(tmp2, wp);

        mpfr_set_si(j_mpfr, q, MPFR_RNDN);

        /* a_d = sq23pi / j */
        mpfr_div(a_d, sq23pi, j_mpfr, MPFR_RNDN);
        /* ac = a_d * sqrtb */
        mpfr_mul(ac, a_d, sqrtb, MPFR_RNDN);
        /* cosh/sinh */
        mpfr_cosh(ch_val, ac, MPFR_RNDN);
        mpfr_sinh(sh_val, ac, MPFR_RNDN);
        /* D_d = sqrt(j) / (sqrt8 * b * pi) */
        mpfr_sqrt(D_d, j_mpfr, MPFR_RNDN);
        mpfr_mul(tmp, sqrt8, b, MPFR_RNDN);
        mpfr_mul(tmp, tmp, pi, MPFR_RNDN);
        mpfr_div(D_d, D_d, tmp, MPFR_RNDN);
        /* E_d = a_d * ch - sh/sqrtb */
        mpfr_mul(E_d, a_d, ch_val, MPFR_RNDN);
        mpfr_div(tmp, sh_val, sqrtb, MPFR_RNDN);
        mpfr_sub(E_d, E_d, tmp, MPFR_RNDN);
        /* d_val = D_d * E_d */
        mpfr_mul(d_val, D_d, E_d, MPFR_RNDN);

        /* s += a_val * d_val */
        mpfr_set_prec(tmp, prec + 100);
        mpfr_mul(tmp, a_val, d_val, MPFR_RNDN);
        mpfr_add(s, s, tmp, MPFR_RNDN);

        /* Dynamic precision reduction: p = bitcount(|int(d)|) + 50 */
        mpz_t z_d;
        mpz_init(z_d);
        mpfr_get_z(z_d, d_val, MPFR_RNDZ);
        mpz_abs(z_d, z_d);
        size_t bits = mpz_sizeinbase(z_d, 2);
        if (mpz_sgn(z_d) == 0) bits = 0;
        p = (long)bits + 50;
        mpz_clear(z_d);
    }

    /* Round to nearest integer: int(s + 0.5) */
    mpfr_set_prec(tmp, prec + 100);
    mpfr_set_d(tmp, 0.5, MPFR_RNDN);
    mpfr_add(s, s, tmp, MPFR_RNDN);

    mpz_t result_z;
    mpz_init(result_z);
    mpfr_get_z(result_z, s, MPFR_RNDZ);
    gmp_snprintf(out_str, out_str_size, "%Zd", result_z);

    /* Cleanup */
    mpz_clear(result_z);
    mpfr_clear(s); mpfr_clear(a_val); mpfr_clear(d_val);
    mpfr_clear(tmp); mpfr_clear(tmp2);
    mpfr_clear(pi); mpfr_clear(sq23pi); mpfr_clear(sqrt8);
    mpfr_clear(b); mpfr_clear(sqrtb);
    mpfr_clear(factor); mpfr_clear(cos_val); mpfr_clear(cos_sum);
    mpfr_clear(j_mpfr); mpfr_clear(a_d); mpfr_clear(ac);
    mpfr_clear(ch_val); mpfr_clear(sh_val);
    mpfr_clear(D_d); mpfr_clear(E_d); mpfr_clear(result_d);

    for (long j = 2; j < M; j++) {
        free(coprime[j].h_paired);
        free(coprime[j].D_paired);
    }
    free(coprime);

    return 0;
}
