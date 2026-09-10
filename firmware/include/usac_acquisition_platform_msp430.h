/* MSP430 acquisition adapter shared by the accepted fixed acquisition path and the V1
 * configurable path. It is linked only into images allowed to reach timers. */
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

/* Performs the fixed 200 kS/s acquisition. Callers must already have applied
 * and read back the authorized d10x4_v1 profile. */
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
