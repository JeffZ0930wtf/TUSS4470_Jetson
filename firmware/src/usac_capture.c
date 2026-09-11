/* Owns the only full waveform buffer in the firmware image. Transport code
 * must stream directly from this storage rather than creating a second copy. */
#include "usac_capture.h"

/* DMA overwrites every element before the buffer is exposed. Keeping it out
 * of .bss avoids clearing 4096 bytes before main() can stop the watchdog. */
uint16_t g_usac_capture_waveform[USAC_CAPTURE_SAMPLE_COUNT]
    __attribute__((section(".noinit")));

uint8_t usac_capture_report_is_default_complete(
    const usac_capture_report_t *report)
{
    if (report == 0) {
        return 0u;
    }
    return (uint8_t)(
        (report->captured_samples == USAC_CAPTURE_SAMPLE_COUNT) &&
        (report->trigger_sample_index == USAC_CAPTURE_DEFAULT_PRETRIGGER_COUNT) &&
        (report->dma_remaining == 0u) &&
        (report->burst_completed != 0u) &&
        (report->timed_out == 0u) &&
        (report->sync_timed_out == 0u) &&
        (report->hardware_fault == 0u));
}

uint8_t usac_capture_report_is_complete(
    const usac_capture_report_t *report,
    uint16_t expected_trigger_sample_index)
{
    return (uint8_t)(
        (report != 0) &&
        (expected_trigger_sample_index <= USAC_CAPTURE_SAMPLE_COUNT) &&
        (report->captured_samples == USAC_CAPTURE_SAMPLE_COUNT) &&
        (report->trigger_sample_index == expected_trigger_sample_index) &&
        (report->dma_remaining == 0u) &&
        (report->burst_completed != 0u) &&
        (report->timed_out == 0u) &&
        (report->sync_timed_out == 0u) &&
        (report->hardware_fault == 0u));
}
