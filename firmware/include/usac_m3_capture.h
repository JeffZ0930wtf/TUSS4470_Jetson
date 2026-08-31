/* Fixed M3 acquisition contract: one 4096-byte sample buffer and explicit
 * DMA evidence. Later milestones may generalize timing, not this raw layout. */
#ifndef USAC_M3_CAPTURE_H
#define USAC_M3_CAPTURE_H

#include <stdint.h>

#define USAC_M3_SAMPLE_COUNT 2048u
#define USAC_M3_PRETRIGGER_COUNT 64u

typedef struct {
    uint16_t captured_samples;
    uint16_t trigger_sample_index;
    uint16_t dma_remaining;
    uint8_t burst_completed;
    uint8_t timed_out;
    uint8_t tuss_dev_stat;
    uint8_t hardware_fault;
} usac_m3_capture_report_t;

extern uint16_t g_usac_m3_waveform[USAC_M3_SAMPLE_COUNT];

uint8_t usac_m3_capture_report_is_complete(
    const usac_m3_capture_report_t *report);

#endif
