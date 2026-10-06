#include "coincidences.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * 3-fold (triplet) coincidence
 *
 * t1 = reference channel, t2 = signal channel 1, t3 = signal channel 2.
 *
 * For each reference event, finds all (t2, t3) pairs within the coincidence
 * window [0, bins). Each such triplet contributes to ALL four histograms.
 *
 * When *deduplicate* is non-zero, each unique delay value per reference event
 * is counted at most once across the four histograms (i.e. per-t1 dedup).
 *
 * Events (the actual triplet timestamp tuples) are written to caller-allocated
 * flat buffers:
 *   out_events[3*e+0] = t1, out_events[3*e+1] = t2, out_events[3*e+2] = t3
 *   out_ref_idx[e]     = index of t1 in the original t1 array
 *   *out_count          = number of triplets written
 * If the buffers fill up (-2 is returned) the caller may grow them and retry.
 *
 * Histogram outputs:
 *   hist_21 — (t2 - t1)
 *   hist_31 — (t3 - t1)
 *   hist_32 — (t3 - t2)
 *   hist_23 — (t2 - t3)
 * ------------------------------------------------------------------------- */
int tdc_compute_triplet(
    const int64_t* t1, int n1,
    const int64_t* t2, int n2,
    const int64_t* t3, int n3,
    int bins, int deduplicate,
    uint64_t* hist_21,
    uint64_t* hist_31,
    uint64_t* hist_32,
    uint64_t* hist_23,
    int64_t* out_events,
    int64_t* out_ref_idx,
    int max_events, int* out_count
) {
    if (!t1 || !t2 || !t3) return -1;
    if (!hist_21 || !hist_31 || !hist_32 || !hist_23) return -1;
    if (n1 < 0 || n2 < 0 || n3 < 0 || bins <= 0) return -1;

    int collect_events = (out_events != NULL && out_ref_idx != NULL
                          && out_count != NULL && max_events > 0);
    if (collect_events) *out_count = 0;

    memset(hist_21, 0, bins * sizeof(uint64_t));
    memset(hist_31, 0, bins * sizeof(uint64_t));
    memset(hist_32, 0, bins * sizeof(uint64_t));
    memset(hist_23, 0, bins * sizeof(uint64_t));

    int idx2_start = 0;
    int idx3_start = 0;

    /* Per-ref dedup masks (allocated once if needed) */
    char* mask21 = NULL;
    char* mask31 = NULL;
    char* mask32 = NULL;
    char* mask23 = NULL;
    if (deduplicate) {
        mask21 = (char*)calloc(bins, 1);
        mask31 = (char*)calloc(bins, 1);
        mask32 = (char*)calloc(bins, 1);
        mask23 = (char*)calloc(bins, 1);
        if (!mask21 || !mask31 || !mask32 || !mask23) {
            free(mask21); free(mask31); free(mask32); free(mask23);
            return -1;
        }
    }

    for (int i = 0; i < n1; i++) {
        int64_t val1 = t1[i];

        /* Advance cached start indices past val1 */
        while (idx2_start < n2 && t2[idx2_start] < val1) idx2_start++;
        while (idx3_start < n3 && t3[idx3_start] < val1) idx3_start++;

        if (deduplicate) {
            memset(mask21, 0, bins);
            memset(mask31, 0, bins);
            memset(mask32, 0, bins);
            memset(mask23, 0, bins);
        }

        for (int j = idx2_start; j < n2; j++) {
            int64_t d21 = t2[j] - val1;
            if (d21 >= bins) break;

            for (int k = idx3_start; k < n3; k++) {
                int64_t d31 = t3[k] - val1;
                if (d31 >= bins) break;

                /* --- triplet event (val1, t2[j], t3[k]) found --- */
                if (!deduplicate) {
                    hist_21[d21]++;
                    hist_31[d31]++;
                } else {
                    if (!mask21[d21]) { hist_21[d21]++; mask21[d21] = 1; }
                    if (!mask31[d31]) { hist_31[d31]++; mask31[d31] = 1; }
                }

                int64_t d32 = t3[k] - t2[j];
                if (d32 >= 0 && d32 < bins) {
                    if (!deduplicate) hist_32[d32]++;
                    else if (!mask32[d32]) { hist_32[d32]++; mask32[d32] = 1; }
                }

                int64_t d23 = t2[j] - t3[k];
                if (d23 >= 0 && d23 < bins) {
                    if (!deduplicate) hist_23[d23]++;
                    else if (!mask23[d23]) { hist_23[d23]++; mask23[d23] = 1; }
                }

                /* Write event tuple if requested */
                if (collect_events) {
                    if (*out_count >= max_events) {
                        free(mask21); free(mask31); free(mask32); free(mask23);
                        return -2; /* buffer full — caller may grow & retry */
                    }
                    int pos = *out_count;
                    out_events[pos * 3 + 0] = val1;
                    out_events[pos * 3 + 1] = t2[j];
                    out_events[pos * 3 + 2] = t3[k];
                    out_ref_idx[pos] = i;
                    (*out_count)++;
                }
            }
        }
    }

    free(mask21); free(mask31); free(mask32); free(mask23);
    return 0;
}


/* ---------------------------------------------------------------------------
 * N-fold gate coincidence (generalized)
 *
 * Reference channel + N-1 signal channels.
 *
 * For each reference event, scans ALL signal channels within the coincidence
 * window [0, bins). Pairwise histograms out_hists[k] record every (sig[k]-ref)
 * hit (marginal, independent of other channels).
 *
 * When *deduplicate* is non-zero, each unique (sig[k]-ref) delay is counted
 * at most once per reference event (per-t1 per-channel dedup).
 *
 * ``n_fold_count`` reports the number of reference events where ALL signal
 * channels had at least one hit — one gated count per qualifying ref.
 *
 * Events (N-fold tuples) are written to flat caller-allocated buffers:
 *   out_events[stride*e]   = ref, out_events[stride*e+1..+n_signals] = sig hits
 *   out_ref_idx[e]         = index of ref in the t_ref array
 *   *out_count             = number of tuples written
 * where stride = n_signals + 1. Only combinations where all channels hit are
 * enumerated. Overflow returns -2 (caller may grow & retry).
 * ------------------------------------------------------------------------- */
int tdc_compute_gate(
    const int64_t* t_ref, int n_ref,
    const int64_t** signals, const int* signal_lengths, int n_signals,
    int bins, int deduplicate,
    uint64_t** out_hists,
    uint64_t* n_fold_count,
    int64_t* out_events,
    int64_t* out_ref_idx,
    int max_events, int* out_count
) {
    if (!t_ref || !signals || !signal_lengths || !out_hists || !n_fold_count)
        return -1;
    if (n_ref < 0 || n_signals <= 0 || bins <= 0)
        return -1;

    for (int k = 0; k < n_signals; k++) {
        if (!signals[k] || signal_lengths[k] < 0) return -1;
        if (!out_hists[k]) return -1;
        memset(out_hists[k], 0, bins * sizeof(uint64_t));
    }
    *n_fold_count = 0;

    int collect_events = (out_events != NULL && out_ref_idx != NULL
                          && out_count != NULL && max_events > 0);
    if (collect_events) *out_count = 0;

    int stride = n_signals + 1;

    /* Cached start indices per signal */
    int* idx_start = (int*)calloc(n_signals, sizeof(int));
    if (!idx_start) return -1;

    /* Per-ref per-channel dedup masks (allocated once if needed) */
    char** dedup_masks = NULL;
    if (deduplicate) {
        dedup_masks = (char**)calloc(n_signals, sizeof(char*));
        if (!dedup_masks) { free(idx_start); return -1; }
        for (int k = 0; k < n_signals; k++) {
            dedup_masks[k] = (char*)calloc(bins, 1);
            if (!dedup_masks[k]) {
                for (int j = 0; j < k; j++) free(dedup_masks[j]);
                free(dedup_masks); free(idx_start);
                return -1;
            }
        }
    }

    /* Temporary arrays for event enumeration per ref */
    int** matches = NULL;       /* matches[k][m] = index j into signals[k] */
    int* match_counts = NULL;   /* number of matches per channel for current ref */
    int* match_caps = NULL;     /* capacity per channel */
    if (collect_events) {
        matches = (int**)calloc(n_signals, sizeof(int*));
        match_counts = (int*)calloc(n_signals, sizeof(int));
        match_caps = (int*)calloc(n_signals, sizeof(int));
        if (!matches || !match_counts || !match_caps) {
            free(matches); free(match_counts); free(match_caps);
            if (dedup_masks) {
                for (int k=0;k<n_signals;k++) free(dedup_masks[k]);
                free(dedup_masks);
            }
            free(idx_start); return -1;
        }
        for (int k = 0; k < n_signals; k++) {
            match_caps[k] = 64;
            matches[k] = (int*)malloc(match_caps[k] * sizeof(int));
            if (!matches[k]) {
                for (int j=0;j<k;j++) free(matches[j]);
                free(matches); free(match_counts); free(match_caps);
                if (dedup_masks){for(int j=0;j<n_signals;j++)free(dedup_masks[j]);free(dedup_masks);}
                free(idx_start); return -1;
            }
        }
    }

    for (int i = 0; i < n_ref; i++) {
        int64_t ref = t_ref[i];
        int all_hit = 1;

        if (deduplicate) {
            for (int k = 0; k < n_signals; k++)
                memset(dedup_masks[k], 0, bins);
        }
        if (collect_events) {
            for (int k = 0; k < n_signals; k++)
                match_counts[k] = 0;
        }

        for (int k = 0; k < n_signals; k++) {
            const int64_t* sig = signals[k];
            int n_sig = signal_lengths[k];
            int found = 0;

            /* Advance cached index past ref */
            while (idx_start[k] < n_sig && sig[idx_start[k]] < ref)
                idx_start[k]++;

            /* Scan within the window [ref, ref + bins) */
            for (int j = idx_start[k]; j < n_sig; j++) {
                int64_t diff = sig[j] - ref;
                if (diff >= bins) break;

                if (!deduplicate) {
                    out_hists[k][diff]++;
                } else if (!dedup_masks[k][diff]) {
                    out_hists[k][diff]++;
                    dedup_masks[k][diff] = 1;
                }

                if (collect_events) {
                    /* Grow matches buffer if needed */
                    if (match_counts[k] >= match_caps[k]) {
                        match_caps[k] *= 2;
                        int* new_buf = (int*)realloc(matches[k], match_caps[k] * sizeof(int));
                        if (!new_buf) goto cleanup;
                        matches[k] = new_buf;
                    }
                    matches[k][match_counts[k]++] = j;
                }

                found = 1;
            }

            if (!found) all_hit = 0;
        }

        if (all_hit) {
            (*n_fold_count)++;

            if (collect_events) {
                /* Enumerate cartesian product of matched indices */
                int* cursors = (int*)calloc(n_signals, sizeof(int));
                if (!cursors) goto cleanup;

                for (;;) {
                    /* Write current combination */
                    if (*out_count >= max_events) {
                        free(cursors);
                        goto overflow;
                    }
                    int pos = *out_count;
                    out_events[pos * stride] = ref;
                    for (int k = 0; k < n_signals; k++) {
                        out_events[pos * stride + 1 + k] = signals[k][matches[k][cursors[k]]];
                    }
                    out_ref_idx[pos] = i;
                    (*out_count)++;

                    /* Advance cursors (odometer) */
                    int carry = 1;
                    for (int k = n_signals - 1; k >= 0 && carry; k--) {
                        cursors[k]++;
                        if (cursors[k] >= match_counts[k]) {
                            cursors[k] = 0;
                        } else {
                            carry = 0;
                        }
                    }
                    if (carry) break; /* wrapped around — all combinations done */
                }
                free(cursors);
            }
        }
    }

    free(idx_start);
    if (dedup_masks) {
        for (int k = 0; k < n_signals; k++) free(dedup_masks[k]);
        free(dedup_masks);
    }
    if (collect_events) {
        for (int k = 0; k < n_signals; k++) free(matches[k]);
        free(matches); free(match_counts); free(match_caps);
    }
    return 0;

overflow:
    for (int k = 0; k < n_signals; k++) free(matches[k]);
    free(matches); free(match_counts); free(match_caps);
    if (dedup_masks) {
        for (int k = 0; k < n_signals; k++) free(dedup_masks[k]);
        free(dedup_masks);
    }
    free(idx_start);
    return -2;

cleanup:
    for (int k = 0; k < n_signals; k++) free(matches[k]);
    free(matches); free(match_counts); free(match_caps);
    if (dedup_masks) {
        for (int k = 0; k < n_signals; k++) free(dedup_masks[k]);
        free(dedup_masks);
    }
    free(idx_start);
    return -1;
}


/* ---------------------------------------------------------------------------
 * Gate-photon correspondence
 *
 * For each gate (trigger) event, find all photon hits from one or more
 * photon-detection channels within the coincidence window [0, bins).
 *
 * Unlike tdc_compute_gate there is no "all channels must hit" requirement —
 * every photon within the window is recorded, period.
 *
 * Output:
 *   out_photons[]  — flat array of photon timestamps (in bin units)
 *   out_channels[] — channel index (0 … n_signals-1) for each photon
 *   out_offsets[]  — [n_gate+1] start offsets: gate i covers
 *                    out_photons[out_offsets[i] … out_offsets[i+1]-1]
 *   *out_count     — total number of photons written (== out_offsets[n_gate])
 *
 * Buffer overflow returns -2 so the caller can grow & retry.
 * ------------------------------------------------------------------------- */
int tdc_compute_gate_photons(
    const int64_t* t_gate, int n_gate,
    const int64_t** photon_signals, const int* signal_lengths, int n_signals,
    int bins,
    int64_t* out_photons,
    int32_t* out_channels,
    int32_t* out_offsets,
    int max_hits,
    int* out_count
) {
    if (!t_gate || !photon_signals || !signal_lengths) return -1;
    if (!out_photons || !out_channels || !out_offsets || !out_count) return -1;
    if (n_gate < 0 || n_signals <= 0 || bins <= 0) return -1;

    for (int k = 0; k < n_signals; k++) {
        if (!photon_signals[k] || signal_lengths[k] < 0) return -1;
    }

    *out_count = 0;
    out_offsets[0] = 0;

    /* Cached start indices per photon channel */
    int* idx_start = (int*)calloc(n_signals, sizeof(int));
    if (!idx_start) return -1;

    for (int i = 0; i < n_gate; i++) {
        int64_t gate = t_gate[i];

        for (int k = 0; k < n_signals; k++) {
            const int64_t* sig = photon_signals[k];
            int n_sig = signal_lengths[k];

            while (idx_start[k] < n_sig && sig[idx_start[k]] < gate)
                idx_start[k]++;

            for (int j = idx_start[k]; j < n_sig; j++) {
                int64_t diff = sig[j] - gate;
                if (diff >= bins) break;

                if (*out_count >= max_hits) {
                    free(idx_start);
                    return -2;
                }
                out_photons[*out_count] = sig[j];
                out_channels[*out_count] = (int32_t)k;
                (*out_count)++;
            }
        }

        out_offsets[i + 1] = *out_count;
    }

    free(idx_start);
    return 0;
}
