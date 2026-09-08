/* Implements the MCU copy of AcquisitionConfigV2. The canonical 35-byte
 * representation feeds both SHA-256 identity and CRC integrity checks so C
 * and Python bind commands to exactly the same hardware/timing fields. */
#include "usac_config_v2.h"

#include "usac_mcu_protocol.h"
#include "usac_sha256.h"

#define PROFILE_SCHEMA_VERSION 2u

static uint16_t read_u16_le(const uint8_t *data)
{
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

static uint32_t read_u32_le(const uint8_t *data)
{
    return (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
           ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
}

static void write_u16_le(uint8_t *data, uint16_t value)
{
    data[0] = (uint8_t)value;
    data[1] = (uint8_t)(value >> 8);
}

static void write_u32_le(uint8_t *data, uint32_t value)
{
    data[0] = (uint8_t)value;
    data[1] = (uint8_t)(value >> 8);
    data[2] = (uint8_t)(value >> 16);
    data[3] = (uint8_t)(value >> 24);
}

static usac_config_v2_result_t validate(const usac_config_v2_t *config)
{
    if ((config == 0) || (config->sample_count != 2048u) ||
        (config->pretrigger_count >= config->sample_count) ||
        (config->adc_bits != 12u) || ((config->aux_flags & 0xFCu) != 0u) ||
        (config->vref_mv != 3300u) ||
        (tuss4470_profile_validate(&config->profile) != TUSS4470_PROFILE_OK)) {
        return USAC_CONFIG_V2_INVALID_VALUE;
    }
    return USAC_CONFIG_V2_OK;
}

static usac_config_v2_result_t canonical_bytes(
    const usac_config_v2_t *config,
    uint8_t canonical[USAC_CONFIG_V2_CANONICAL_LENGTH])
{
    uint8_t index;

    if (validate(config) != USAC_CONFIG_V2_OK) {
        return USAC_CONFIG_V2_INVALID_VALUE;
    }
    write_u16_le(&canonical[0], PROFILE_SCHEMA_VERSION);
    write_u16_le(&canonical[2], config->profile.sample_interval_ticks);
    write_u16_le(&canonical[4], config->sample_count);
    write_u16_le(&canonical[6], config->pretrigger_count);
    canonical[8] = config->adc_bits;
    write_u16_le(&canonical[9], config->vref_mv);
    canonical[11] = config->aux_flags;
    write_u16_le(&canonical[12], config->profile.burst_period_ticks);
    canonical[14] = TUSS4470_PROFILE_REGISTER_COUNT;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        canonical[15u + 2u * index] = config->profile.registers[index].address;
        canonical[16u + 2u * index] = config->profile.registers[index].value;
    }
    return USAC_CONFIG_V2_OK;
}

void usac_config_v2_init_d10x4(usac_config_v2_t *config)
{
    tuss4470_profile_init_d10x4(&config->profile);
    config->sample_count = 2048u;
    config->pretrigger_count = 64u;
    config->adc_bits = 12u;
    config->aux_flags = 0u;
    config->vref_mv = 3300u;
    (void)usac_config_v2_rehash(config);
}

usac_config_v2_result_t usac_config_v2_rehash(usac_config_v2_t *config)
{
    uint8_t canonical[USAC_CONFIG_V2_CANONICAL_LENGTH];
    usac_config_v2_result_t result = canonical_bytes(config, canonical);

    if (result != USAC_CONFIG_V2_OK) {
        return result;
    }
    usac_sha256(canonical, USAC_CONFIG_V2_CANONICAL_LENGTH, config->profile_sha256);
    config->device_config_crc32 = usac_mcu_crc32(
        canonical, USAC_CONFIG_V2_CANONICAL_LENGTH);
    return USAC_CONFIG_V2_OK;
}

usac_config_v2_result_t usac_config_v2_encode(
    const usac_config_v2_t *config,
    uint8_t *output,
    uint16_t capacity,
    uint16_t *output_length)
{
    uint8_t canonical[USAC_CONFIG_V2_CANONICAL_LENGTH];
    uint8_t digest[32];
    uint32_t crc;
    uint8_t index;

    if ((output == 0) || (output_length == 0) ||
        (capacity < USAC_CONFIG_V2_WIRE_LENGTH)) {
        return USAC_CONFIG_V2_OUTPUT_TOO_SMALL;
    }
    if (canonical_bytes(config, canonical) != USAC_CONFIG_V2_OK) {
        return USAC_CONFIG_V2_INVALID_VALUE;
    }
    usac_sha256(canonical, USAC_CONFIG_V2_CANONICAL_LENGTH, digest);
    crc = usac_mcu_crc32(canonical, USAC_CONFIG_V2_CANONICAL_LENGTH);
    for (index = 0u; index < 32u; ++index) {
        if (digest[index] != config->profile_sha256[index]) {
            return USAC_CONFIG_V2_HASH_MISMATCH;
        }
    }
    if (crc != config->device_config_crc32) {
        return USAC_CONFIG_V2_CRC_MISMATCH;
    }

    write_u16_le(&output[0], PROFILE_SCHEMA_VERSION);
    write_u16_le(&output[2], config->profile.sample_interval_ticks);
    write_u16_le(&output[4], config->sample_count);
    write_u16_le(&output[6], config->pretrigger_count);
    output[8] = config->adc_bits;
    output[9] = config->aux_flags;
    write_u16_le(&output[10], config->vref_mv);
    write_u16_le(&output[12], config->profile.burst_period_ticks);
    output[14] = TUSS4470_PROFILE_REGISTER_COUNT;
    output[15] = 0u;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        output[16u + 2u * index] = config->profile.registers[index].address;
        output[17u + 2u * index] = config->profile.registers[index].value;
    }
    for (index = 0u; index < 32u; ++index) {
        output[36u + index] = config->profile_sha256[index];
    }
    write_u32_le(&output[68], config->device_config_crc32);
    *output_length = USAC_CONFIG_V2_WIRE_LENGTH;
    return USAC_CONFIG_V2_OK;
}

usac_config_v2_result_t usac_config_v2_decode(
    const uint8_t *wire,
    uint16_t length,
    usac_config_v2_t *config)
{
    uint8_t canonical[USAC_CONFIG_V2_CANONICAL_LENGTH];
    uint8_t digest[32];
    uint32_t crc;
    uint8_t index;

    if ((wire == 0) || (config == 0) || (length != USAC_CONFIG_V2_WIRE_LENGTH)) {
        return USAC_CONFIG_V2_INVALID_LENGTH;
    }
    if ((read_u16_le(&wire[0]) != PROFILE_SCHEMA_VERSION) ||
        (wire[14] != TUSS4470_PROFILE_REGISTER_COUNT) || (wire[15] != 0u)) {
        return USAC_CONFIG_V2_INVALID_VALUE;
    }
    config->profile.sample_interval_ticks = read_u16_le(&wire[2]);
    config->sample_count = read_u16_le(&wire[4]);
    config->pretrigger_count = read_u16_le(&wire[6]);
    config->adc_bits = wire[8];
    config->aux_flags = wire[9];
    config->vref_mv = read_u16_le(&wire[10]);
    config->profile.burst_period_ticks = read_u16_le(&wire[12]);
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        config->profile.registers[index].address = wire[16u + 2u * index];
        config->profile.registers[index].value = wire[17u + 2u * index];
    }
    if (canonical_bytes(config, canonical) != USAC_CONFIG_V2_OK) {
        return USAC_CONFIG_V2_INVALID_VALUE;
    }
    usac_sha256(canonical, USAC_CONFIG_V2_CANONICAL_LENGTH, digest);
    for (index = 0u; index < 32u; ++index) {
        config->profile_sha256[index] = wire[36u + index];
        if (digest[index] != wire[36u + index]) {
            return USAC_CONFIG_V2_HASH_MISMATCH;
        }
    }
    crc = usac_mcu_crc32(canonical, USAC_CONFIG_V2_CANONICAL_LENGTH);
    config->device_config_crc32 = read_u32_le(&wire[68]);
    if (crc != config->device_config_crc32) {
        return USAC_CONFIG_V2_CRC_MISMATCH;
    }
    return USAC_CONFIG_V2_OK;
}
