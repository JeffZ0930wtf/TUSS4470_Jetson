/* Fixed MCU-side configuration contract. Encoding and decoding validate the
 * canonical hash/CRC; they do not apply registers or start hardware. */
#ifndef USAC_CONFIG_V2_H
#define USAC_CONFIG_V2_H

#include <stdint.h>

#include "tuss4470_profile.h"

#define USAC_CONFIG_V2_WIRE_LENGTH 72u
#define USAC_CONFIG_V2_CANONICAL_LENGTH 35u

typedef struct {
    tuss4470_profile_t profile;
    uint16_t sample_count;
    uint16_t pretrigger_count;
    uint8_t adc_bits;
    uint8_t aux_flags;
    uint16_t vref_mv;
    uint8_t profile_sha256[32];
    uint32_t device_config_crc32;
} usac_config_v2_t;

typedef enum {
    USAC_CONFIG_V2_OK = 0,
    USAC_CONFIG_V2_INVALID_LENGTH = 1,
    USAC_CONFIG_V2_INVALID_VALUE = 2,
    USAC_CONFIG_V2_HASH_MISMATCH = 3,
    USAC_CONFIG_V2_CRC_MISMATCH = 4,
    USAC_CONFIG_V2_OUTPUT_TOO_SMALL = 5
} usac_config_v2_result_t;

void usac_config_v2_init_d10x4(usac_config_v2_t *config);
/* Recomputes both identifiers after an intentional semantic field change. */
usac_config_v2_result_t usac_config_v2_rehash(usac_config_v2_t *config);
usac_config_v2_result_t usac_config_v2_encode(
    const usac_config_v2_t *config,
    uint8_t *output,
    uint16_t capacity,
    uint16_t *output_length);
usac_config_v2_result_t usac_config_v2_decode(
    const uint8_t *wire,
    uint16_t length,
    usac_config_v2_t *config);

#endif
