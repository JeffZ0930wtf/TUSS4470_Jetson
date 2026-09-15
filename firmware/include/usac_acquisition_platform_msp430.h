/* MSP430 adapter for ADC/DMA acquisition, finite Burst timing, and IO2
 * loopback evaluation. These functions directly control hardware resources. */
#ifndef USAC_ACQUISITION_PLATFORM_MSP430_H
#define USAC_ACQUISITION_PLATFORM_MSP430_H

#include <stdint.h>

#include "usac_loopback.h"
#include "usac_capture.h"
#include "usac_config_v2.h"

/* context must point to the initialized tuss4470_bus_t used by the app. */
uint8_t usac_platform_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    usac_loopback_report_t *report);

/* Runs the shared ADC/DMA capture engine. usac_platform_capture() prepares
 * configurable timing, pretrigger, and Burst state before calling this.
 * Outside an active configurable capture, only the 200 kS/s D10x4 baseline
 * timing is accepted. Callers must already have applied and read back the
 * configuration; this function does not apply a register profile. */
uint8_t usac_platform_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_capture_report_t *report);

#ifdef USAC_ENABLE_ACQUISITION
/* Executes one already-validated finite configuration. External slave sync is
 * bounded by sync_timeout_ms; timeout returns without starting a Burst. */
uint8_t usac_platform_capture(
    void *context,
    const usac_config_v2_t *config,
    uint8_t trigger_source,
    uint32_t sync_timeout_ms,
    usac_capture_report_t *report);

/* Called from the shared TA1 CCR1 ISR.  Slave sync uses this interrupt-owned
 * timebase because TI does not guarantee direct reads of an asynchronously
 * clocked running TA1R register. */
void usac_platform_on_aclk_quantum(void);
#endif


#endif
