/* Holds hardware-independent firmware safety primitives: protocol state, timing
 * range checks, clock-fault interpretation, and TUSS4470 SPI word parity. */
#include "usac_firmware_core.h"

static uint16_t tuss4470_spi_word(uint8_t is_read, uint8_t address, uint8_t value)
{
    uint16_t word;
    uint16_t parity_bits;

    word = (uint16_t)(((uint16_t)(is_read & 1u) << 15) |
                      ((uint16_t)(address & 0x3Fu) << 9) |
                      value);
    parity_bits = word;
    parity_bits ^= (uint16_t)(parity_bits >> 8);
    parity_bits ^= (uint16_t)(parity_bits >> 4);
    parity_bits ^= (uint16_t)(parity_bits >> 2);
    parity_bits ^= (uint16_t)(parity_bits >> 1);
    if ((parity_bits & 1u) == 0u) {
        word |= 0x0100u;
    }
    return word;
}

void usac_firmware_core_reset(usac_firmware_core_t *core)
{
    core->state = USAC_FIRMWARE_RESET_SAFE;
    core->io2_high = 1u;
    core->burst_timer_running = 0u;
    core->burst_inhibited = 1u;
}

uint8_t usac_firmware_core_burst_permitted(const usac_firmware_core_t *core)
{
    (void)core;
    return 0u;
}

uint8_t usac_firmware_clock_faults_safe(uint8_t ucsctl7_low)
{
    /* Base firmware/acquisition use REFO, so DCOFFG=bit0 and XT2OFFG=bit3 are fatal while
     * XT1 may remain flagged. V1 separately gates its required XT1 source. */
    return (uint8_t)((ucsctl7_low & 0x09u) == 0u);
}

usac_firmware_result_t usac_firmware_validate_timing(
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks)
{
    if ((sample_interval_ticks < 120u) || (sample_interval_ticks > 960u) ||
        (burst_period_ticks < 24u) || (burst_period_ticks > 800u)) {
        return USAC_FIRMWARE_INVALID_TIMING;
    }
    return USAC_FIRMWARE_OK;
}

usac_firmware_result_t usac_firmware_build_timing_stage(
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_firmware_timing_stage_t *stage)
{
    if ((stage == 0) ||
        (usac_firmware_validate_timing(
             sample_interval_ticks, burst_period_ticks) != USAC_FIRMWARE_OK)) {
        return USAC_FIRMWARE_INVALID_TIMING;
    }
    stage->sample_interval_ticks = sample_interval_ticks;
    stage->burst_period_ticks = burst_period_ticks;
    stage->tb0_ccr0 = (uint16_t)(sample_interval_ticks - 1u);
    stage->ta2_ccr0 = (uint16_t)(burst_period_ticks - 1u);
    stage->timer_control_bits = 0u;
    return USAC_FIRMWARE_OK;
}

uint16_t tuss4470_spi_write_word(uint8_t address, uint8_t value)
{
    return tuss4470_spi_word(0u, address, value);
}

uint16_t tuss4470_spi_read_word(uint8_t address)
{
    return tuss4470_spi_word(1u, address, 0u);
}
