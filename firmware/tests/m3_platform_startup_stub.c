/* M3 startup-only diagnostic platform. It preserves the production M3 main
 * loop and full waveform RAM allocation while making every acquisition entry
 * point fail closed. This file is never linked into a release image. */
#include <stdint.h>

#include "usac_m3_capture.h"
#include "usac_platform_m3_msp430.h"

uint16_t g_usac_m3_waveform[USAC_M3_SAMPLE_COUNT];

uint8_t usac_platform_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    usac_m3_loopback_report_t *report)
{
    (void)context;
    (void)burst_period_ticks;
    (void)report;
    return 0u;
}

uint8_t usac_platform_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report)
{
    (void)context;
    (void)sample_interval_ticks;
    (void)burst_period_ticks;
    (void)report;
    return 0u;
}
