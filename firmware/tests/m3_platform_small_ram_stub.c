/* Startup diagnostic with a one-word placeholder waveform. The production
 * main never dereferences it before an accepted capture, while both callbacks
 * below always fail, so this safely isolates static-RAM pressure. The loose
 * pointer parameter types are intentional: this diagnostic TU is link-only
 * and is never part of a release image. */
#include <stdint.h>

uint16_t g_usac_m3_waveform[1];

uint8_t usac_m3_capture_report_is_complete(const void *report)
{
    (void)report;
    return 0u;
}

uint8_t usac_platform_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    void *report)
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
    void *report)
{
    (void)context;
    (void)sample_interval_ticks;
    (void)burst_period_ticks;
    (void)report;
    return 0u;
}
