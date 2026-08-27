/* Verified D10x4 profile model shared by configuration, readback, and wire
 * serialization. Masks prevent reserved or transient bits from leaking into
 * ordinary profile application. */
#ifndef TUSS4470_PROFILE_H
#define TUSS4470_PROFILE_H

#include <stdint.h>

#define TUSS4470_PROFILE_REGISTER_COUNT 10u

typedef struct {
    uint8_t address;
    uint8_t value;
} tuss4470_register_pair_t;

typedef struct {
    uint16_t sample_interval_ticks;
    uint16_t burst_period_ticks;
    tuss4470_register_pair_t registers[TUSS4470_PROFILE_REGISTER_COUNT];
} tuss4470_profile_t;

typedef enum {
    TUSS4470_PROFILE_OK = 0,
    TUSS4470_PROFILE_REGISTER_LAYOUT = 1,
    TUSS4470_PROFILE_RESERVED_BIT = 2,
    TUSS4470_PROFILE_INVALID_TIMING = 3,
    TUSS4470_PROFILE_CONTINUOUS_BURST = 4,
    TUSS4470_PROFILE_WRONG_DRIVER = 5,
    TUSS4470_PROFILE_VOUT_RANGE = 6,
    TUSS4470_PROFILE_VDRV_RANGE = 7,
    TUSS4470_PROFILE_STATEFUL_BIT = 8
} tuss4470_profile_result_t;

void tuss4470_profile_init_d10x4(tuss4470_profile_t *profile);
tuss4470_profile_result_t tuss4470_profile_validate(
    const tuss4470_profile_t *profile);

#endif
