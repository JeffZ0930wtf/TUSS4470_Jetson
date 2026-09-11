/* Pure acquisition loopback acceptance rules, kept separate from MSP430 registers so
 * boundary and failure behavior can run in the MSP430 simulator. */
#include "usac_loopback.h"

void usac_loopback_evaluate(
    usac_loopback_report_t *report,
    uint16_t expected_interval_ticks)
{
    uint8_t preserved_flags;
    uint8_t index;
    uint16_t minimum = 0xFFFFu;
    uint16_t maximum = 0u;

    if (report == 0) {
        return;
    }
    preserved_flags = (uint8_t)(report->result_flags &
        (USAC_LOOPBACK_COV_SEEN |
         USAC_LOOPBACK_TIMEOUT |
         USAC_LOOPBACK_PREPOST_SAFETY_FAILED));
    report->result_flags = preserved_flags;

    if (report->captured_edges != USAC_LOOPBACK_EDGE_COUNT) {
        report->result_flags |= USAC_LOOPBACK_TIMEOUT;
        report->minimum_interval_ticks = 0u;
        report->maximum_interval_ticks = 0u;
    } else {
        for (index = 1u; index < USAC_LOOPBACK_EDGE_COUNT; ++index) {
            /* Unsigned subtraction intentionally supports one 16-bit wrap. */
            uint16_t interval = (uint16_t)(
                report->capture_ticks[index] - report->capture_ticks[index - 1u]);
            if (interval < minimum) {
                minimum = interval;
            }
            if (interval > maximum) {
                maximum = interval;
            }
            if ((interval + 1u < expected_interval_ticks) ||
                (interval > (uint16_t)(expected_interval_ticks + 1u))) {
                report->result_flags |= USAC_LOOPBACK_INTERVAL_MISMATCH;
            }
        }
        report->minimum_interval_ticks = minimum;
        report->maximum_interval_ticks = maximum;
    }
    if (report->final_io2_level == 0u) {
        report->result_flags |= USAC_LOOPBACK_FINAL_NOT_HIGH;
    }
    if (report->result_flags == 0u) {
        report->result_flags = USAC_LOOPBACK_PASS;
    }
}
