/* Fixed M3 acquisition contract: one 4096-byte sample buffer and explicit
 * DMA evidence. Later milestones may generalize timing, not this raw layout. */
#ifndef USAC_M3_CAPTURE_H
#define USAC_M3_CAPTURE_H

#include <stdint.h>

#define USAC_M3_SAMPLE_COUNT 2048u
#define USAC_M3_PRETRIGGER_COUNT 64u
#define USAC_M5_MAX_CAPTURE_EVENTS 17u

/* Compact timeout-only snapshot bits. They identify which acquisition
 * resources were still active when the bounded wait expired. */
#define USAC_M5_CAPTURE_DIAG_GIE_AT_ENTRY 0x0001u
#define USAC_M5_CAPTURE_DIAG_TB0_RUNNING 0x0002u
#define USAC_M5_CAPTURE_DIAG_ADC_ENABLED 0x0004u
#define USAC_M5_CAPTURE_DIAG_ADC_IFG0 0x0008u
#define USAC_M5_CAPTURE_DIAG_DMA0_ENABLED 0x0010u
#define USAC_M5_CAPTURE_DIAG_DMA0_IFG 0x0020u
#define USAC_M5_CAPTURE_DIAG_DMA1_IFG 0x0040u
#define USAC_M5_CAPTURE_DIAG_BURST_COMPLETE 0x0080u

typedef struct {
    uint8_t channel;
    uint8_t edge;
    uint8_t capture_method;
    uint8_t level_after;
    int32_t sample_index;
    uint16_t subsample_tick;
    uint16_t uncertainty_ticks;
    uint32_t frame_offset_ticks;
} usac_m5_capture_event_t;

typedef struct {
    uint16_t captured_samples;
    uint16_t trigger_sample_index;
    uint16_t dma_remaining;
    uint8_t burst_completed;
    uint8_t timed_out;
    uint8_t sync_timed_out;
    uint8_t tuss_dev_stat;
    uint8_t hardware_fault;
    uint8_t out3_start_level;
    uint8_t out4_start_level;
    uint8_t event_count;
    uint16_t diagnostic_flags;
    uint16_t diagnostic_timer_tick;
    uint32_t quality_flags;
    usac_m5_capture_event_t events[USAC_M5_MAX_CAPTURE_EVENTS];
} usac_m3_capture_report_t;

extern uint16_t g_usac_m3_waveform[USAC_M3_SAMPLE_COUNT];

uint8_t usac_m3_capture_report_is_complete(
    const usac_m3_capture_report_t *report);
uint8_t usac_m5_capture_report_is_complete(
    const usac_m3_capture_report_t *report,
    uint16_t expected_trigger_sample_index);

#endif
