/* Owns the only full waveform buffer in the firmware image. Transport code
 * must stream directly from this storage rather than creating a second copy. */
#include "usac_m3_capture.h"

/* DMA overwrites every element before the buffer is exposed. Keeping it out
 * of .bss avoids clearing 4096 bytes before main() can stop the watchdog. */
uint16_t g_usac_m3_waveform[USAC_M3_SAMPLE_COUNT]
    __attribute__((section(".noinit")));

uint8_t usac_m3_capture_report_is_complete(
    const usac_m3_capture_report_t *report)
{
    if (report == 0) {
        return 0u;
    }
    return (uint8_t)(
        (report->captured_samples == USAC_M3_SAMPLE_COUNT) &&
        (report->trigger_sample_index == USAC_M3_PRETRIGGER_COUNT) &&
        (report->dma_remaining == 0u) &&
        (report->burst_completed != 0u) &&
        (report->timed_out == 0u) &&
        (report->hardware_fault == 0u));
}
