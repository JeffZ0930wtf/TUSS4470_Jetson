/* Hardware-independent evaluation for the M3 IO2-to-TA0CCR4 acceptance test.
 * The platform layer records raw timer evidence; this module applies the
 * protocol's exact edge-count, interval, overflow, and safe-final-level rules. */
#ifndef USAC_M3_LOOPBACK_H
#define USAC_M3_LOOPBACK_H

#include <stdint.h>

#define USAC_M3_LOOPBACK_EDGE_COUNT 8u

#define USAC_M3_LOOPBACK_PASS 0x01u
#define USAC_M3_LOOPBACK_COV_SEEN 0x02u
#define USAC_M3_LOOPBACK_TIMEOUT 0x04u
#define USAC_M3_LOOPBACK_INTERVAL_MISMATCH 0x08u
#define USAC_M3_LOOPBACK_FINAL_NOT_HIGH 0x10u
#define USAC_M3_LOOPBACK_PREPOST_SAFETY_FAILED 0x20u

typedef struct {
    uint16_t capture_ticks[USAC_M3_LOOPBACK_EDGE_COUNT];
    uint16_t minimum_interval_ticks;
    uint16_t maximum_interval_ticks;
    uint8_t captured_edges;
    uint8_t result_flags;
    uint8_t pre_spi_status;
    uint8_t pre_dev_stat;
    uint8_t pre_tof_config;
    uint8_t pre_vdrv_ctrl;
    uint8_t post_spi_status;
    uint8_t post_dev_stat;
    uint8_t post_tof_config;
    uint8_t post_vdrv_ctrl;
    uint8_t final_io2_level;
} usac_m3_loopback_report_t;

/* Derives PASS and failure flags from raw evidence. Existing platform flags
 * for overflow, timeout, or TUSS safety failure are preserved. */
void usac_m3_loopback_evaluate(
    usac_m3_loopback_report_t *report,
    uint16_t expected_interval_ticks);

#endif
