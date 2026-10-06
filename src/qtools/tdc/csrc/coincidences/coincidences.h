#ifndef TDC_COINCIDENCES_H
#define TDC_COINCIDENCES_H

#include <stdint.h>

#ifdef _WIN32
#  define COINC_API __declspec(dllexport)
#else
#  define COINC_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Compute the coincidence g2 histogram from two sorted arrays of timestamps.
 *
 * Uses a sliding window algorithm with O(N1 + N2) time complexity.
 * All timestamps are in bin units (int64).
 *
 * @param t1          Sorted timestamps of the start channel (int64, bin units).
 * @param n1          Size of t1.
 * @param t2_adj      Sorted, offset-adjusted timestamps of the stop channel.
 * @param n2          Size of t2_adj.
 * @param bins        Number of bins in the histogram.
 * @param out_hist    Output histogram array (size must be at least bins).
 * @return            0 on success, or non-zero error code.
 */
COINC_API int tdc_compute_g2(
    const int64_t* t1, int n1,
    const int64_t* t2_adj, int n2,
    int bins,
    uint64_t* out_hist
);

/**
 * 3-fold (triplet) coincidence.
 *
 * t1 = reference channel, t2/t3 = signal channels.
 * For each reference event, enumerates all (t2, t3) pairs within the
 * window [0, bins). Each triplet contributes to ALL four histograms.
 *
 * When *deduplicate* is non-zero, each unique delay per reference event
 * is counted at most once across the histograms.
 *
 * Events are written to flat caller-allocated buffers (may be NULL to skip):
 *   out_events[3*e+0] = t1, out_events[3*e+1] = t2, out_events[3*e+2] = t3
 *   out_ref_idx[e]     = index of t1 in the original array
 *   *out_count          = number of events written
 * Returns -2 if the caller buffer is too small (grow & retry).
 *
 * @param t1       Reference channel timestamps (sorted int64, bin units).
 * @param n1       Length of t1.
 * @param t2       Signal channel 1 timestamps.
 * @param n2       Length of t2.
 * @param t3       Signal channel 2 timestamps.
 * @param n3       Length of t3.
 * @param bins     Number of histogram bins.
 * @param deduplicate  Non-zero enables per-ref dedup of histogram bins.
 * @param hist_21  Output: histogram of (t2 - t1).
 * @param hist_31  Output: histogram of (t3 - t1).
 * @param hist_32  Output: histogram of (t3 - t2).
 * @param hist_23  Output: histogram of (t2 - t3).
 * @param out_events    Flat output buffer for event tuples (or NULL).
 * @param out_ref_idx   Output buffer for ref indices (or NULL).
 * @param max_events    Capacity of out_events / out_ref_idx.
 * @param out_count     Actual number of events written.
 * @return         0 on success, -1 on error, -2 if events buffer full.
 */
COINC_API int tdc_compute_triplet(
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
);

/**
 * N-fold gate coincidence (generalized).
 *
 * Reference channel + N-1 signal channels.
 * For each reference event, scan all signal channels within the window
 * [0, bins). Each (ref, sig[k]) pair is counted in out_hists[k].
 *
 * When *deduplicate* is non-zero, each unique (sig[k]-ref) delay per
 * reference event is counted at most once.
 *
 * ``n_fold_count`` reports the number of reference events for which **all**
 * N-1 signal channels had at least one hit in the window. This is a "gated"
 * count — one per qualifying reference event, not the product of per-channel
 * hit multiplicities.
 *
 * Events are written to flat caller-allocated buffers (may be NULL to skip):
 *   out_events[stride*e] = ref, out_events[stride*e+1..+n_signals] = sig hits
 *   out_ref_idx[e]       = index of ref in the t_ref array
 *   *out_count           = number of events written
 * where stride = n_signals + 1. Each event is one combination of
 * (sig_0, ..., sig_{N-1}) hits within the ref window, enumerated
 * cartesian-product style. Returns -2 if the buffer overflows.
 *
 * @param t_ref             Reference channel timestamps (sorted int64).
 * @param n_ref             Length of t_ref.
 * @param signals           Array of N signal channel timestamp arrays.
 * @param signal_lengths    Length of each signal array.
 * @param n_signals         Number of signal channels (N-1).
 * @param bins              Number of histogram bins.
 * @param deduplicate       Non-zero enables per-ref per-channel dedup.
 * @param out_hists         Array of N output histogram pointers (caller-allocated,
 *                          each size ``bins``). out_hists[k] = (signal[k] - ref).
 * @param n_fold_count      Output: number of reference events where all signal
 *                          channels had a coincidence hit.
 * @param out_events        Flat output buffer for N-fold tuples (or NULL).
 * @param out_ref_idx       Output buffer for ref indices (or NULL).
 * @param max_events        Capacity.
 * @param out_count         Actual events written.
 * @return                  0 on success, -1 on error, -2 if events overflow.
 */
COINC_API int tdc_compute_gate(
    const int64_t* t_ref, int n_ref,
    const int64_t** signals, const int* signal_lengths, int n_signals,
    int bins, int deduplicate,
    uint64_t** out_hists,
    uint64_t* n_fold_count,
    int64_t* out_events,
    int64_t* out_ref_idx,
    int max_events, int* out_count
);

/**
 * Gate-photon correspondence (one-to-many mapping).
 *
 * For each gate (trigger) event, finds ALL photon hits from the signal
 * channels within the window [0, bins). No "all-hit" filter is applied;
 * every photon within the window is recorded.
 *
 * @param t_gate            Gate / trigger timestamps (sorted int64, bin units).
 * @param n_gate            Length of t_gate.
 * @param photon_signals    Array of N photon channel timestamp arrays.
 * @param signal_lengths    Length of each photon signal array.
 * @param n_signals         Number of photon channels.
 * @param bins              Window size in bins.
 * @param out_photons       Flat output buffer for photon timestamps.
 * @param out_channels      Channel index (0..n_signals-1) for each photon.
 * @param out_offsets       [n_gate+1] start offsets into out_photons[].
 * @param max_hits          Capacity of out_photons / out_channels.
 * @param out_count         Actual total photon hits written.
 * @return                  0 on success, -1 on error, -2 if overflow.
 */
COINC_API int tdc_compute_gate_photons(
    const int64_t* t_gate, int n_gate,
    const int64_t** photon_signals, const int* signal_lengths, int n_signals,
    int bins,
    int64_t* out_photons,
    int32_t* out_channels,
    int32_t* out_offsets,
    int max_hits,
    int* out_count
);

#ifdef __cplusplus
}
#endif

#endif /* TDC_COINCIDENCES_H */
