/* Defines the verified D10x4 firmware register profile and validates its immutable
 * address/mask/value relationships. It is a bring-up baseline, not a public
 * raw-register interface or the only future transducer configuration. */
#include "tuss4470_profile.h"

static const uint8_t register_addresses[TUSS4470_PROFILE_REGISTER_COUNT] = {
    0x10u, 0x11u, 0x12u, 0x13u, 0x14u,
    0x16u, 0x17u, 0x18u, 0x1Au, 0x1Bu
};

static const uint8_t register_masks[TUSS4470_PROFILE_REGISTER_COUNT] = {
    0xFFu, 0x3Fu, 0xFFu, 0xC7u, 0x1Fu,
    0x7Fu, 0x1Fu, 0xFFu, 0xFFu, 0xC3u
};

static const uint8_t d10x4_values[TUSS4470_PROFILE_REGISTER_COUNT] = {
    0x2Eu, 0x00u, 0x00u, 0x00u, 0x03u,
    0x40u, 0x07u, 0x14u, 0x01u, 0x02u
};

void tuss4470_profile_init_d10x4(tuss4470_profile_t *profile)
{
    uint8_t index;

    profile->sample_interval_ticks = 120u;
    profile->burst_period_ticks = 50u;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        profile->registers[index].address = register_addresses[index];
        profile->registers[index].value = d10x4_values[index];
    }
}

tuss4470_profile_result_t tuss4470_profile_validate(
    const tuss4470_profile_t *profile)
{
    uint8_t index;
    uint8_t value;

    if ((profile->sample_interval_ticks < 120u) ||
        (profile->sample_interval_ticks > 960u) ||
        (profile->burst_period_ticks < 24u) ||
        (profile->burst_period_ticks > 800u)) {
        return TUSS4470_PROFILE_INVALID_TIMING;
    }

    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        if (profile->registers[index].address != register_addresses[index]) {
            return TUSS4470_PROFILE_REGISTER_LAYOUT;
        }
        if ((profile->registers[index].value &
             (uint8_t)~register_masks[index]) != 0u) {
            return TUSS4470_PROFILE_RESERVED_BIT;
        }
    }

    value = profile->registers[8].value;
    if ((value & 0x3Fu) == 0u) {
        return TUSS4470_PROFILE_CONTINUOUS_BURST;
    }
    if ((value & 0x40u) != 0u) {
        return TUSS4470_PROFILE_WRONG_DRIVER;
    }

    if ((profile->registers[3].value & 0x04u) != 0u) {
        return TUSS4470_PROFILE_VOUT_RANGE;
    }

    value = profile->registers[5].value;
    if ((value & (0x10u | 0x0Fu)) != 0u) {
        return TUSS4470_PROFILE_VDRV_RANGE;
    }

    value = profile->registers[9].value;
    if ((value & (0x01u | 0x40u | 0x80u)) != 0u) {
        return TUSS4470_PROFILE_STATEFUL_BIT;
    }

    return TUSS4470_PROFILE_OK;
}
