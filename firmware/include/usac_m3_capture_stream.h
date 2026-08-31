/* Segmented CAPTURE_DATA encoder. Metadata is small and owned here; the 4096
 * sample bytes are exposed directly from the unique DMA waveform buffer. */
#ifndef USAC_M3_CAPTURE_STREAM_H
#define USAC_M3_CAPTURE_STREAM_H

#include <stdint.h>

#include "tuss4470_profile.h"
#include "usac_m3_capture.h"

#define USAC_M3_CAPTURE_METADATA_LENGTH 208u
#define USAC_M3_QUALITY_TIMING_UNCALIBRATED 0x00000020ul

typedef struct {
    uint8_t request_id[16];
    uint8_t boot_id[16];
    uint8_t device_id[16];
    uint8_t profile_sha256[32];
    uint32_t device_config_crc32;
    uint32_t frame_sequence;
    uint32_t capture_sequence;
    uint16_t sample_interval_ticks;
    uint16_t burst_period_ticks;
    uint8_t tuss_dev_stat;
    tuss4470_register_pair_t register_pairs[TUSS4470_PROFILE_REGISTER_COUNT];
} usac_m3_capture_descriptor_t;

typedef struct {
    uint8_t frame_header[16];
    uint8_t metadata[USAC_M3_CAPTURE_METADATA_LENGTH];
    uint8_t frame_crc[4];
    const uint16_t *samples;
    uint8_t phase;
    uint8_t active;
} usac_m3_capture_stream_t;

void usac_m3_capture_stream_init(
    usac_m3_capture_stream_t *stream,
    const usac_m3_capture_descriptor_t *descriptor,
    const uint16_t samples[USAC_M3_SAMPLE_COUNT]);
uint8_t usac_m3_capture_stream_peek(
    const usac_m3_capture_stream_t *stream,
    const uint8_t **data,
    uint16_t *length);
uint8_t usac_m3_capture_stream_commit(usac_m3_capture_stream_t *stream);
uint32_t usac_m3_crc32_begin(void);
uint32_t usac_m3_crc32_update(uint32_t crc, const uint8_t *data, uint16_t length);
uint32_t usac_m3_crc32_finish(uint32_t crc);

#endif
