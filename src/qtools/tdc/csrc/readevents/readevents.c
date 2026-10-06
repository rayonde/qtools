/* readevents.c: Skeleton implementations for TDC2 native library. */

#include "readevents.h"
#include <stdlib.h>
#include <string.h>

static char g_last_error[256] = "No error";

TDC_API tdc_device_t* tdc_open(const char *device_path) {
    (void)device_path;
    /* Stub: to be implemented in Phase 2 with libusb */
    strncpy(g_last_error, "Backend not yet implemented in Phase 1", sizeof(g_last_error));
    return NULL;
}

TDC_API void tdc_close(tdc_device_t *dev) {
    (void)dev;
}

TDC_API int tdc_is_connected(tdc_device_t *dev) {
    return dev != NULL;
}

TDC_API int tdc_read_singles(tdc_device_t *dev, double duration_sec, tdc_singles_t *result) {
    (void)dev; (void)duration_sec; (void)result;
    return -1;
}

TDC_API int tdc_read_timestamps(tdc_device_t *dev, double duration_sec, tdc_event_buffer_t *buf) {
    (void)dev; (void)duration_sec; (void)buf;
    return -1;
}

TDC_API void tdc_free_buffer(tdc_event_buffer_t *buf) {
    if (buf) {
        free(buf->timestamps);
        free(buf->channels);
        buf->timestamps = NULL;
        buf->channels = NULL;
        buf->count = 0;
    }
}

TDC_API int tdc_set_threshold(tdc_device_t *dev, int channel, double voltage) {
    (void)dev; (void)channel; (void)voltage;
    return -1;
}

TDC_API int tdc_write_register(tdc_device_t *dev, uint32_t addr, uint32_t val) {
    (void)dev; (void)addr; (void)val;
    return -1;
}

TDC_API int tdc_read_register(tdc_device_t *dev, uint32_t addr, uint32_t *val) {
    (void)dev; (void)addr; (void)val;
    return -1;
}

TDC_API const char* tdc_get_error(void) {
    return g_last_error;
}
