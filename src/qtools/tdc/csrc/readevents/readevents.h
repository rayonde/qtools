/* readevents.h: Public C API for S-Fifteen TDC2 native communication. */

#ifndef READEVENTS_H
#define READEVENTS_H

#include <stdint.h>
#include <stddef.h>

#ifdef _WIN32
    #define TDC_API __declspec(dllexport)
#else
    #define TDC_API __attribute__((visibility("default")))
#endif

typedef struct tdc_device tdc_device_t;

typedef struct {
    int64_t  *timestamps;    /* Array of timestamps in ps */
    uint8_t  *channels;      /* Array of channels (0-3) */
    size_t    count;         /* Event count */
    double    total_time_ns; /* Total acquisition time in ns */
} tdc_event_buffer_t;

typedef struct {
    uint32_t counts[4];      /* Counts for each channel */
    double   integration_ms; /* Actual duration in ms */
} tdc_singles_t;

/* --- Lifecycle --- */
TDC_API tdc_device_t* tdc_open(const char *device_path);
TDC_API void          tdc_close(tdc_device_t *dev);
TDC_API int           tdc_is_connected(tdc_device_t *dev);

/* --- Data Acquisition --- */
TDC_API int tdc_read_singles(tdc_device_t *dev, double duration_sec, tdc_singles_t *result);
TDC_API int tdc_read_timestamps(tdc_device_t *dev, double duration_sec, tdc_event_buffer_t *buf);
TDC_API void tdc_free_buffer(tdc_event_buffer_t *buf);

/* --- Control --- */
TDC_API int tdc_set_threshold(tdc_device_t *dev, int channel, double voltage);
TDC_API int tdc_write_register(tdc_device_t *dev, uint32_t addr, uint32_t val);
TDC_API int tdc_read_register(tdc_device_t *dev, uint32_t addr, uint32_t *val);

/* --- Errors --- */
TDC_API const char* tdc_get_error(void);

#endif /* READEVENTS_H */
