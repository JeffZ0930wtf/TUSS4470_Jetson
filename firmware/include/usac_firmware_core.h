/* Hardware-independent firmware state, timing, clock, and SPI safety primitives.
 * This API can validate readiness but contains no transmission routine. */
#ifndef USAC_FIRMWARE_CORE_H
#define USAC_FIRMWARE_CORE_H

#include <stdint.h>

typedef enum {
    USAC_FIRMWARE_RESET_SAFE = 0,
    USAC_FIRMWARE_USB_DETACH_HOLD = 1,
    USAC_FIRMWARE_SELF_TEST = 2,
    USAC_FIRMWARE_ENUMERATING = 3,
    USAC_FIRMWARE_SESSION_WAIT = 4,
    USAC_FIRMWARE_CONFIGURING = 5,
    USAC_FIRMWARE_IDLE_SAFE = 6,
    USAC_FIRMWARE_FAULT = 7
} usac_firmware_state_t;

typedef enum {
    USAC_FIRMWARE_OK = 0,
    USAC_FIRMWARE_INVALID_TIMING = 1
} usac_firmware_result_t;

typedef struct {
    usac_firmware_state_t state;
    uint8_t io2_high;
    uint8_t burst_timer_running;
    uint8_t burst_inhibited;
} usac_firmware_core_t;

typedef struct {
    uint16_t sample_interval_ticks;
    uint16_t burst_period_ticks;
    uint16_t tb0_ccr0;
    uint16_t ta2_ccr0;
    uint16_t timer_control_bits;
} usac_firmware_timing_stage_t;

void usac_firmware_core_reset(usac_firmware_core_t *core);
uint8_t usac_firmware_core_burst_permitted(const usac_firmware_core_t *core);
uint8_t usac_firmware_clock_faults_safe(uint8_t ucsctl7_low);
usac_firmware_result_t usac_firmware_validate_timing(
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks);
usac_firmware_result_t usac_firmware_build_timing_stage(
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_firmware_timing_stage_t *stage);

uint16_t tuss4470_spi_write_word(uint8_t address, uint8_t value);
uint16_t tuss4470_spi_read_word(uint8_t address);

#endif
