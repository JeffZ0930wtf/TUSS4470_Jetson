/* M3-only MSP430 acceptance adapter. This API can generate the finite IO2
 * loopback waveform and therefore must never be linked into the M2 image. */
#ifndef USAC_PLATFORM_M3_MSP430_H
#define USAC_PLATFORM_M3_MSP430_H

#include <stdint.h>

#include "usac_m3_loopback.h"
#include "usac_m3_capture.h"

/* context must point to the initialized tuss4470_bus_t used by the app. */
uint8_t usac_platform_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    usac_m3_loopback_report_t *report);

/* Performs the fixed 200 kS/s acquisition. Callers must already have applied
 * and read back the authorized d10x4_v1 profile. */
uint8_t usac_platform_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report);

#endif
