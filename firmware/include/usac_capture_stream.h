/* Segmented CAPTURE_DATA encoder. Metadata is small and owned here; the 4096
 * sample bytes are exposed directly from the unique DMA waveform buffer. */
#ifndef USAC_CAPTURE_STREAM_H
#define USAC_CAPTURE_STREAM_H

#include <stdint.h>

#include "tuss4470_profile.h"
#include "usac_capture.h"

#define USAC_CAPTURE_METADATA_LENGTH 208u
#define USAC_CAPTURE_METADATA_MAX_LENGTH 480u
#define USAC_QUALITY_TIMING_UNCALIBRATED 0x00000020ul

typedef struct {
    uint8_t request_id[16];
    uint8_t schedule_id[16];
    uint8_t boot_id[16];
    uint8_t device_id[16];
    uint8_t profile_sha256[32];
    uint32_t device_config_crc32;
    uint32_t frame_sequence;
    uint32_t capture_sequence;
    uint8_t async_capture;
    uint16_t sample_interval_ticks;
    uint16_t burst_period_ticks;
    uint16_t pretrigger_count;
    uint8_t tuss_dev_stat;
    uint8_t out3_start_level;
    uint8_t out4_start_level;
    uint8_t event_count;
    uint32_t quality_flags;
    usac_capture_event_t events[USAC_MAX_CAPTURE_EVENTS];
    tuss4470_register_pair_t register_pairs[TUSS4470_PROFILE_REGISTER_COUNT];
} usac_capture_descriptor_t;

typedef struct {
    uint8_t frame_header[16];
    uint8_t metadata[USAC_CAPTURE_METADATA_MAX_LENGTH];
    uint16_t metadata_length;
    uint8_t frame_crc[4];
    const uint16_t *samples;
    uint8_t phase;
    uint8_t active;
} usac_capture_stream_t;

void usac_capture_stream_init(
    usac_capture_stream_t *stream,
    const usac_capture_descriptor_t *descriptor,
    const uint16_t samples[USAC_CAPTURE_SAMPLE_COUNT]);
uint8_t usac_capture_stream_peek(
    const usac_capture_stream_t *stream,
    const uint8_t **data,
    uint16_t *length);
uint8_t usac_capture_stream_commit(usac_capture_stream_t *stream);
uint32_t usac_crc32_begin(void);
uint32_t usac_crc32_update(uint32_t crc, const uint8_t *data, uint16_t length);
uint32_t usac_crc32_finish(uint32_t crc);

#endif
