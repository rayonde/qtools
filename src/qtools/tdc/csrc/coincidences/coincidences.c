#include "coincidences.h"
#include <stdint.h>

int tdc_compute_g2(
    const int64_t* t1, int n1,
    const int64_t* t2_adj, int n2,
    int bins,
    uint64_t* out_hist
) {
    if (!t1 || !t2_adj || !out_hist || n1 < 0 || n2 < 0 || bins <= 0) {
        return -1;
    }

    int idx2_start = 0;

    // Reset output histogram
    for (int i = 0; i < bins; i++) {
        out_hist[i] = 0;
    }

    for (int i = 0; i < n1; i++) {
        int64_t val1 = t1[i];

        // Slide the window start index to the first element where t2_adj[idx2_start] >= val1
        while (idx2_start < n2 && t2_adj[idx2_start] < val1) {
            idx2_start++;
        }

        // Scan elements inside the coincidence window
        for (int j = idx2_start; j < n2; j++) {
            int64_t diff = t2_adj[j] - val1;
            if (diff >= bins) {
                break; // Out of histogram range
            }
            if (diff >= 0) {
                out_hist[diff]++;
            }
        }
    }

    return 0;
}
