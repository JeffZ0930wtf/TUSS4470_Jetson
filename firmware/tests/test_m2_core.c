#include <stdint.h>
#include <msp430.h>

#include "usac_m2_core.h"
#include "usac_m3_loopback.h"
#include "usac_m3_capture.h"
#include "usac_m3_capture_stream.h"
#include "usac_m3_capture_tx.h"
#include "tuss4470_profile.h"
#include "tuss4470_configurator.h"
#include "usac_platform_msp430.h"
#include "usac_mcu_protocol.h"
#include "usac_identity.h"
#include "usac_sha256.h"
#include "usac_config_v2.h"
#include "usac_m2_app.h"
#include "usac_dtr_gate.h"
#include "usac_tx_gate.h"

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

static int test_reset_is_safe(void)
{
    usac_m2_core_t core;

    usac_m2_core_reset(&core);

    CHECK(core.state == USAC_M2_RESET_SAFE);
    CHECK(core.io2_high == 1u);
    CHECK(core.burst_timer_running == 0u);
    CHECK(core.burst_inhibited == 1u);
    CHECK(usac_m2_core_burst_permitted(&core) == 0u);
    return 0;
}

static int test_m2_never_releases_burst(void)
{
    usac_m2_core_t core;
    uint8_t state;

    usac_m2_core_reset(&core);
    for (state = USAC_M2_RESET_SAFE; state <= USAC_M2_FAULT; ++state) {
        core.state = (usac_m2_state_t)state;
        core.io2_high = 1u;
        core.burst_timer_running = 0u;
        core.burst_inhibited = 1u;
        CHECK(usac_m2_core_burst_permitted(&core) == 0u);
    }
    return 0;
}

static int test_timer_ranges_are_bounded(void)
{
    usac_m2_timing_stage_t stage;

    CHECK(usac_m2_validate_timing(120u, 24u) == USAC_M2_OK);
    CHECK(usac_m2_validate_timing(960u, 800u) == USAC_M2_OK);
    CHECK(usac_m2_validate_timing(119u, 24u) == USAC_M2_INVALID_TIMING);
    CHECK(usac_m2_validate_timing(961u, 24u) == USAC_M2_INVALID_TIMING);
    CHECK(usac_m2_validate_timing(120u, 23u) == USAC_M2_INVALID_TIMING);
    CHECK(usac_m2_validate_timing(120u, 801u) == USAC_M2_INVALID_TIMING);
    CHECK(usac_m2_build_timing_stage(120u, 50u, &stage) == USAC_M2_OK);
    CHECK(stage.sample_interval_ticks == 120u);
    CHECK(stage.burst_period_ticks == 50u);
    CHECK(stage.tb0_ccr0 == 119u);
    CHECK(stage.ta2_ccr0 == 49u);
    CHECK(stage.timer_control_bits == 0u);
    return 0;
}

static int test_clock_gate_ignores_only_unused_xt1_fault(void)
{
    CHECK(usac_m2_clock_faults_safe(0x00u) == 1u);
    CHECK(usac_m2_clock_faults_safe(0x02u) == 1u);
    CHECK(usac_m2_clock_faults_safe(0x01u) == 0u);
    CHECK(usac_m2_clock_faults_safe(0x08u) == 0u);
    CHECK(usac_m2_clock_faults_safe(0x0Bu) == 0u);
    return 0;
}

static int test_official_spi_vectors(void)
{
    CHECK(tuss4470_spi_write_word(0x10u, 0x2Eu) == 0x202Eu);
    CHECK(tuss4470_spi_read_word(0x10u) == 0xA100u);
    CHECK(tuss4470_spi_write_word(0x16u, 0x40u) == 0x2D40u);
    CHECK(tuss4470_spi_read_word(0x16u) == 0xAD00u);
    CHECK(tuss4470_spi_write_word(0x1Au, 0x01u) == 0x3501u);
    CHECK(tuss4470_spi_read_word(0x1Au) == 0xB500u);
    return 0;
}

static int test_d10x4_default_profile_is_complete(void)
{
    static const uint8_t expected_addresses[TUSS4470_PROFILE_REGISTER_COUNT] = {
        0x10u, 0x11u, 0x12u, 0x13u, 0x14u,
        0x16u, 0x17u, 0x18u, 0x1Au, 0x1Bu
    };
    static const uint8_t expected_values[TUSS4470_PROFILE_REGISTER_COUNT] = {
        0x2Eu, 0x00u, 0x00u, 0x00u, 0x03u,
        0x40u, 0x07u, 0x14u, 0x01u, 0x02u
    };
    tuss4470_profile_t profile;
    uint8_t index;

    tuss4470_profile_init_d10x4(&profile);
    CHECK(profile.sample_interval_ticks == 120u);
    CHECK(profile.burst_period_ticks == 50u);
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        CHECK(profile.registers[index].address == expected_addresses[index]);
        CHECK(profile.registers[index].value == expected_values[index]);
    }
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_OK);
    return 0;
}

static int test_profile_rejects_hardware_unsafe_values(void)
{
    tuss4470_profile_t profile;

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[8].value = 0x00u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_CONTINUOUS_BURST);

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[8].value = 0x41u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_WRONG_DRIVER);

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[3].value = 0x04u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_VOUT_RANGE);

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[5].value = 0x50u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_VDRV_RANGE);

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[9].value = 0x03u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_STATEFUL_BIT);

    tuss4470_profile_init_d10x4(&profile);
    profile.registers[5].value = 0x60u;
    profile.registers[9].value = 0x00u;
    CHECK(tuss4470_profile_validate(&profile) == TUSS4470_PROFILE_OK);
    return 0;
}

typedef struct {
    uint8_t registers[0x20];
    uint8_t writes_address[32];
    uint8_t writes_value[32];
    uint8_t write_count;
    uint8_t corrupt_readback_address;
    uint8_t delay_count;
} fake_tuss4470_t;

static uint8_t fake_read(void *context, uint8_t address, uint8_t *value)
{
    fake_tuss4470_t *device = (fake_tuss4470_t *)context;

    *value = device->registers[address];
    if (address == device->corrupt_readback_address) {
        *value ^= 0x01u;
    }
    return 1u;
}

static uint8_t fake_write(void *context, uint8_t address, uint8_t value)
{
    fake_tuss4470_t *device = (fake_tuss4470_t *)context;

    device->registers[address] = value;
    device->writes_address[device->write_count] = address;
    device->writes_value[device->write_count] = value;
    ++device->write_count;
    return 1u;
}

static void fake_delay_1ms(void *context)
{
    fake_tuss4470_t *device = (fake_tuss4470_t *)context;
    ++device->delay_count;
}

static void fake_tuss4470_init(fake_tuss4470_t *device)
{
    uint8_t index;

    for (index = 0u; index < (uint8_t)sizeof(*device); ++index) {
        ((uint8_t *)device)[index] = 0u;
    }
    device->registers[0x1Du] = 0xB9u;
    device->registers[0x1Eu] = 0x02u;
    device->registers[0x1Cu] = 0x08u;
    device->corrupt_readback_address = 0xFFu;
}

static int test_configurator_applies_safe_order_and_reaches_ready(void)
{
    fake_tuss4470_t device;
    tuss4470_bus_t bus;
    tuss4470_profile_t profile;
    tuss4470_config_report_t report;

    fake_tuss4470_init(&device);
    bus.context = &device;
    bus.read = fake_read;
    bus.write = fake_write;
    bus.delay_1ms = fake_delay_1ms;
    tuss4470_profile_init_d10x4(&profile);

    CHECK(tuss4470_configure_m2(&bus, &profile, 4u, &report) ==
          TUSS4470_CONFIG_OK);
    CHECK(report.device_id == 0xB9u);
    CHECK(report.revision_id == 0x02u);
    CHECK(report.dev_stat == 0x08u);
    CHECK(device.delay_count == 1u);
    CHECK(device.writes_address[0] == 0x1Au);
    CHECK(device.writes_value[0] == 0x01u);
    CHECK(device.writes_address[1] == 0x16u);
    CHECK(device.writes_value[1] == 0x20u);
    CHECK(device.writes_address[2] == 0x1Bu);
    CHECK(device.writes_value[2] == 0x00u);
    CHECK(device.writes_address[3] == 0x14u);
    CHECK(device.writes_value[3] == 0x03u);
    CHECK(device.writes_address[device.write_count - 2u] == 0x16u);
    CHECK(device.writes_value[device.write_count - 2u] == 0x40u);
    CHECK(device.writes_address[device.write_count - 1u] == 0x1Bu);
    CHECK(device.writes_value[device.write_count - 1u] == 0x02u);
    CHECK(device.registers[0x1Au] == 0x01u);
    CHECK((device.registers[0x1Bu] & 0x01u) == 0u);
    CHECK(tuss4470_force_safe(&bus) == TUSS4470_CONFIG_OK);
    CHECK(device.registers[0x1Bu] == 0x40u);
    CHECK(device.registers[0x16u] == 0x20u);

    fake_tuss4470_init(&device);
    device.registers[0x1Cu] = 0x00u;
    tuss4470_profile_init_d10x4(&profile);
    profile.registers[5].value = 0x60u;
    profile.registers[9].value = 0x00u;
    CHECK(tuss4470_configure_m2(&bus, &profile, 1u, &report) ==
          TUSS4470_CONFIG_OK);
    CHECK(device.registers[0x16u] == 0x60u);
    CHECK(device.registers[0x1Bu] == 0x00u);

    fake_tuss4470_init(&device);
    CHECK(tuss4470_enter_low_power(
              &bus, TUSS4470_LOW_POWER_STANDBY) == TUSS4470_CONFIG_OK);
    CHECK(device.registers[0x16u] == 0x20u);
    CHECK(device.registers[0x1Bu] == 0x40u);
    CHECK(tuss4470_enter_low_power(
              &bus, TUSS4470_LOW_POWER_SLEEP) == TUSS4470_CONFIG_OK);
    CHECK(device.registers[0x16u] == 0x20u);
    CHECK(device.registers[0x1Bu] == 0x80u);
    return 0;
}

static int test_configurator_fails_closed_on_identity_readback_and_status(void)
{
    fake_tuss4470_t device;
    tuss4470_bus_t bus;
    tuss4470_profile_t profile;
    tuss4470_config_report_t report;

    fake_tuss4470_init(&device);
    bus.context = &device;
    bus.read = fake_read;
    bus.write = fake_write;
    bus.delay_1ms = fake_delay_1ms;
    tuss4470_profile_init_d10x4(&profile);

    device.registers[0x1Du] = 0x00u;
    CHECK(tuss4470_configure_m2(&bus, &profile, 4u, &report) ==
          TUSS4470_CONFIG_IDENTITY);
    CHECK(device.write_count == 0u);

    fake_tuss4470_init(&device);
    device.corrupt_readback_address = 0x14u;
    CHECK(tuss4470_configure_m2(&bus, &profile, 4u, &report) ==
          TUSS4470_CONFIG_READBACK);
    CHECK((device.registers[0x1Bu] & 0x01u) == 0u);

    fake_tuss4470_init(&device);
    device.registers[0x1Cu] = 0x02u;
    CHECK(tuss4470_configure_m2(&bus, &profile, 4u, &report) ==
          TUSS4470_CONFIG_DRIVER_FAULT);
    CHECK((device.registers[0x1Bu] & 0x01u) == 0u);
    CHECK(device.registers[0x1Bu] == 0x40u);
    CHECK(device.registers[0x16u] == 0x20u);

    fake_tuss4470_init(&device);
    device.registers[0x1Cu] = 0x00u;
    CHECK(tuss4470_configure_m2(&bus, &profile, 2u, &report) ==
          TUSS4470_CONFIG_VDRV_TIMEOUT);
    CHECK((device.registers[0x1Bu] & 0x01u) == 0u);
    CHECK(device.registers[0x1Bu] == 0x40u);
    CHECK(device.registers[0x16u] == 0x20u);
    return 0;
}

static int test_mcu_parser_accepts_m1_hello_vector(void)
{
    static const uint8_t hello_frame[] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x01u,0x00u,0x00u,
        0x01u,0x00u,0x00u,0x00u,0x14u,0x00u,0x00u,0x00u,
        0x00u,0x01u,0x02u,0x03u,0x04u,0x05u,0x06u,0x07u,
        0x08u,0x09u,0x0Au,0x0Bu,0x0Cu,0x0Du,0x0Eu,0x0Fu,
        0x01u,0x01u,0x00u,0x00u,0x07u,0x62u,0x2Eu,0xCDu
    };
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    uint16_t index;

    usac_mcu_parser_init(&parser);
    for (index = 0u; index < (uint16_t)(sizeof(hello_frame) - 1u); ++index) {
        CHECK(usac_mcu_parser_feed(&parser, hello_frame[index], &frame) ==
              USAC_MCU_PARSE_INCOMPLETE);
    }
    CHECK(usac_mcu_parser_feed(
              &parser, hello_frame[sizeof(hello_frame) - 1u], &frame) ==
          USAC_MCU_PARSE_FRAME);
    CHECK(frame.message_type == 0x01u);
    CHECK(frame.sequence == 1u);
    CHECK(frame.payload_length == 20u);
    CHECK(frame.payload[0] == 0x00u);
    CHECK(frame.payload[15] == 0x0Fu);
    CHECK(frame.payload[16] == 0x01u);
    CHECK(frame.payload[17] == 0x01u);
    return 0;
}

static int test_mcu_encoder_reproduces_m1_hello_vector(void)
{
    static const uint8_t hello_payload[20] = {
        0x00u,0x01u,0x02u,0x03u,0x04u,0x05u,0x06u,0x07u,
        0x08u,0x09u,0x0Au,0x0Bu,0x0Cu,0x0Du,0x0Eu,0x0Fu,
        0x01u,0x01u,0x00u,0x00u
    };
    static const uint8_t expected_frame[40] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x01u,0x00u,0x00u,
        0x01u,0x00u,0x00u,0x00u,0x14u,0x00u,0x00u,0x00u,
        0x00u,0x01u,0x02u,0x03u,0x04u,0x05u,0x06u,0x07u,
        0x08u,0x09u,0x0Au,0x0Bu,0x0Cu,0x0Du,0x0Eu,0x0Fu,
        0x01u,0x01u,0x00u,0x00u,0x07u,0x62u,0x2Eu,0xCDu
    };
    uint8_t encoded[40];
    uint16_t encoded_length;
    uint8_t index;

    CHECK(usac_mcu_encode_frame(
              0x01u, 0u, 1u, hello_payload, 20u,
              encoded, (uint16_t)sizeof(encoded), &encoded_length) == 1u);
    CHECK(encoded_length == sizeof(expected_frame));
    for (index = 0u; index < sizeof(expected_frame); ++index) {
        CHECK(encoded[index] == expected_frame[index]);
    }
    CHECK(usac_mcu_encode_frame(
              0x01u, 0u, 1u, hello_payload, 20u,
              encoded, 39u, &encoded_length) == 0u);
    return 0;
}

static int test_mcu_parser_bounds_input_and_resynchronizes(void)
{
    static const uint8_t oversized_header[] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x04u,0x00u,0x00u,
        0x02u,0x00u,0x00u,0x00u,0xC1u,0x00u,0x00u,0x00u
    };
    static const uint8_t get_config_frame[] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x03u,0x00u,0x00u,
        0x03u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,
        0xE2u,0xEBu,0x1Du,0xF7u
    };
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    uint16_t index;

    usac_mcu_parser_init(&parser);
    for (index = 0u; index < (uint16_t)(sizeof(oversized_header) - 1u); ++index) {
        CHECK(usac_mcu_parser_feed(&parser, oversized_header[index], &frame) ==
              USAC_MCU_PARSE_INCOMPLETE);
    }
    CHECK(usac_mcu_parser_feed(
              &parser,
              oversized_header[sizeof(oversized_header) - 1u],
              &frame) == USAC_MCU_PARSE_INVALID_LENGTH);
    CHECK(parser.count == 0u);
    CHECK(sizeof(parser.buffer) == 256u);

    for (index = 0u; index < (uint16_t)sizeof(get_config_frame); ++index) {
        usac_mcu_parse_result_t result = usac_mcu_parser_feed(
            &parser, get_config_frame[index], &frame);
        if (index + 1u == (uint16_t)sizeof(get_config_frame)) {
            CHECK(result == USAC_MCU_PARSE_FRAME);
        } else {
            CHECK(result == USAC_MCU_PARSE_INCOMPLETE);
        }
    }
    CHECK(frame.message_type == 0x03u);
    CHECK(frame.payload_length == 0u);
    return 0;
}

static int test_mcu_parser_rejects_crc_then_accepts_next_frame(void)
{
    uint8_t frame_bytes[] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x03u,0x00u,0x00u,
        0x03u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,
        0xE2u,0xEBu,0x1Du,0xF7u
    };
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    uint16_t index;

    usac_mcu_parser_init(&parser);
    frame_bytes[16] ^= 0x01u;
    for (index = 0u; index < (uint16_t)(sizeof(frame_bytes) - 1u); ++index) {
        CHECK(usac_mcu_parser_feed(&parser, frame_bytes[index], &frame) ==
              USAC_MCU_PARSE_INCOMPLETE);
    }
    CHECK(usac_mcu_parser_feed(
              &parser, frame_bytes[sizeof(frame_bytes) - 1u], &frame) ==
          USAC_MCU_PARSE_BAD_CRC);

    frame_bytes[16] ^= 0x01u;
    for (index = 0u; index < (uint16_t)sizeof(frame_bytes); ++index) {
        usac_mcu_parse_result_t result = usac_mcu_parser_feed(
            &parser, frame_bytes[index], &frame);
        if (index + 1u == (uint16_t)sizeof(frame_bytes)) {
            CHECK(result == USAC_MCU_PARSE_FRAME);
        } else {
            CHECK(result == USAC_MCU_PARSE_INCOMPLETE);
        }
    }
    return 0;
}

static int test_mcu_parser_timeout_discards_partial_candidate(void)
{
    static const uint8_t frame_bytes[] = {
        0x55u,0x53u,0x41u,0x43u,0x01u,0x03u,0x00u,0x00u,
        0x03u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,0x00u,
        0xE2u,0xEBu,0x1Du,0xF7u
    };
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    usac_mcu_parse_result_t result;
    uint16_t index;

    usac_mcu_parser_init(&parser);
    for (index = 0u; index < 5u; ++index) {
        result = usac_mcu_parser_feed(&parser, frame_bytes[index], &frame);
        CHECK(result == USAC_MCU_PARSE_INCOMPLETE);
    }
    CHECK(parser.count == 5u);
    CHECK(usac_mcu_parser_expire(&parser) == USAC_MCU_PARSE_TIMEOUT);
    CHECK(parser.count == 0u);
    for (index = 0u; index < sizeof(frame_bytes); ++index) {
        result = usac_mcu_parser_feed(&parser, frame_bytes[index], &frame);
    }
    CHECK(result == USAC_MCU_PARSE_FRAME);
    return 0;
}

static int test_m2_parser_rejects_short_set_config(void)
{
    uint8_t payload[100] = {0u};
    uint8_t encoded[120];
    uint16_t encoded_length;
    uint16_t index;
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    usac_mcu_parse_result_t result = USAC_MCU_PARSE_INCOMPLETE;

    CHECK(usac_mcu_encode_frame(
              0x04u, 0u, 7u, payload, sizeof(payload),
              encoded, sizeof(encoded), &encoded_length) == 1u);
    CHECK(encoded_length == sizeof(encoded));
    usac_mcu_parser_init(&parser);
    for (index = 0u; index < encoded_length; ++index) {
        result = usac_mcu_parser_feed(&parser, encoded[index], &frame);
        if (result != USAC_MCU_PARSE_INCOMPLETE) {
            break;
        }
    }
    CHECK(result == USAC_MCU_PARSE_INVALID_LENGTH);
    CHECK(index == 15u);
    CHECK(parser.count == 0u);
    return 0;
}

static int test_mcu_parser_passes_unknown_bounded_command_to_app(void)
{
    uint8_t encoded[32];
    uint16_t encoded_length;
    uint16_t index;
    usac_mcu_parser_t parser;
    usac_mcu_frame_view_t frame;
    usac_mcu_parse_result_t result = USAC_MCU_PARSE_INCOMPLETE;

    CHECK(usac_mcu_encode_frame(
              0x2Au, 0u, 0x01020304ul, 0, 0u,
              encoded, sizeof(encoded), &encoded_length) == 1u);
    usac_mcu_parser_init(&parser);
    for (index = 0u; index < encoded_length; ++index) {
        result = usac_mcu_parser_feed(&parser, encoded[index], &frame);
    }
    CHECK(result == USAC_MCU_PARSE_FRAME);
    CHECK(frame.message_type == 0x2Au);
    CHECK(frame.sequence == 0x01020304ul);
    CHECK(frame.payload_length == 0u);
    return 0;
}

static usac_mcu_parse_result_t parse_complete_test_frame(
    const uint8_t *encoded,
    uint16_t encoded_length,
    usac_mcu_frame_view_t *frame)
{
    usac_mcu_parser_t parser;
    usac_mcu_parse_result_t result = USAC_MCU_PARSE_INCOMPLETE;
    uint16_t index;

    usac_mcu_parser_init(&parser);
    for (index = 0u; index < encoded_length; ++index) {
        result = usac_mcu_parser_feed(&parser, encoded[index], frame);
        if (result != USAC_MCU_PARSE_INCOMPLETE) {
            break;
        }
    }
    return result;
}

static int test_m3_parser_validates_io2_loopback_command(void)
{
    uint8_t payload[56] = {0u};
    uint8_t encoded[76];
    uint16_t encoded_length;
    usac_mcu_frame_view_t frame;

    payload[52] = 8u;
    CHECK(usac_mcu_encode_frame(
              0x0Eu, 0u, 0x11223344ul, payload, sizeof(payload),
              encoded, sizeof(encoded), &encoded_length) == 1u);
    CHECK(parse_complete_test_frame(encoded, encoded_length, &frame) ==
          USAC_MCU_PARSE_FRAME);
    CHECK(frame.message_type == 0x0Eu);
    CHECK(frame.sequence == 0x11223344ul);
    CHECK(frame.payload_length == 56u);

    payload[52] = 7u;
    CHECK(usac_mcu_encode_frame(
              0x0Eu, 0u, 1u, payload, sizeof(payload),
              encoded, sizeof(encoded), &encoded_length) == 1u);
    CHECK(parse_complete_test_frame(encoded, encoded_length, &frame) ==
          USAC_MCU_PARSE_INVALID_PAYLOAD);

    payload[52] = 8u;
    payload[55] = 1u;
    CHECK(usac_mcu_encode_frame(
              0x0Eu, 0u, 2u, payload, sizeof(payload),
              encoded, sizeof(encoded), &encoded_length) == 1u);
    CHECK(parse_complete_test_frame(encoded, encoded_length, &frame) ==
          USAC_MCU_PARSE_INVALID_PAYLOAD);

    payload[55] = 0u;
    CHECK(usac_mcu_encode_frame(
              0x0Eu, 0u, 3u, payload, 55u,
              encoded, sizeof(encoded), &encoded_length) == 1u);
    CHECK(parse_complete_test_frame(encoded, encoded_length, &frame) ==
          USAC_MCU_PARSE_INVALID_LENGTH);
    return 0;
}

static int test_m3_loopback_evaluation_requires_exact_stable_edges(void)
{
    usac_m3_loopback_report_t report = {0u};
    uint8_t index;

    report.captured_edges = 8u;
    report.final_io2_level = 1u;
    for (index = 0u; index < 8u; ++index) {
        report.capture_ticks[index] = (uint16_t)(100u + ((uint16_t)index * 50u));
    }
    usac_m3_loopback_evaluate(&report, 50u);
    CHECK(report.result_flags == USAC_M3_LOOPBACK_PASS);
    CHECK(report.minimum_interval_ticks == 50u);
    CHECK(report.maximum_interval_ticks == 50u);

    report.capture_ticks[4] = 302u;
    usac_m3_loopback_evaluate(&report, 50u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_INTERVAL_MISMATCH) != 0u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_PASS) == 0u);

    report.capture_ticks[4] = 300u;
    report.result_flags = USAC_M3_LOOPBACK_COV_SEEN;
    usac_m3_loopback_evaluate(&report, 50u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_COV_SEEN) != 0u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_PASS) == 0u);

    report.result_flags = 0u;
    report.captured_edges = 7u;
    usac_m3_loopback_evaluate(&report, 50u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_TIMEOUT) != 0u);

    report.captured_edges = 8u;
    report.final_io2_level = 0u;
    usac_m3_loopback_evaluate(&report, 50u);
    CHECK((report.result_flags & USAC_M3_LOOPBACK_FINAL_NOT_HIGH) != 0u);
    return 0;
}

static int test_m3_capture_report_requires_exact_dma_evidence(void)
{
    usac_m3_capture_report_t report = {0u};

    report.captured_samples = USAC_M3_SAMPLE_COUNT;
    report.trigger_sample_index = USAC_M3_PRETRIGGER_COUNT;
    report.burst_completed = 1u;

    CHECK(usac_m3_capture_report_is_complete(&report) == 1u);
    report.captured_samples = 2047u;
    CHECK(usac_m3_capture_report_is_complete(&report) == 0u);
    report.captured_samples = USAC_M3_SAMPLE_COUNT;
    report.trigger_sample_index = 63u;
    CHECK(usac_m3_capture_report_is_complete(&report) == 0u);
    report.trigger_sample_index = USAC_M3_PRETRIGGER_COUNT;
    report.timed_out = 1u;
    CHECK(usac_m3_capture_report_is_complete(&report) == 0u);
    return 0;
}

static int test_m3_segmented_crc_matches_iso_hdlc_vector(void)
{
    static const uint8_t vector[9] = {
        '1','2','3','4','5','6','7','8','9'
    };
    uint32_t crc = usac_m3_crc32_begin();

    crc = usac_m3_crc32_update(crc, vector, 4u);
    crc = usac_m3_crc32_update(crc, &vector[4], 5u);
    CHECK(usac_m3_crc32_finish(crc) == 0xCBF43926ul);
    return 0;
}

static int test_m3_capture_stream_matches_python_fixed_vector(void)
{
    static const uint8_t expected_capture_id[16] = {
        0xC5u,0xA1u,0x74u,0xA9u,0xA8u,0x24u,0xD9u,0xBEu,
        0xE6u,0x5Cu,0x34u,0x1Du,0x2Cu,0x91u,0xA1u,0xE8u
    };
    static const uint8_t expected_crc[4] = {0x87u,0x57u,0xFFu,0xDCu};
    usac_config_v2_t config;
    usac_m3_capture_descriptor_t descriptor = {0u};
    usac_m3_capture_stream_t stream;
    const uint8_t *chunk;
    const uint8_t *again;
    const uint8_t *expected_segments[4];
    static const uint16_t expected_lengths[4] = {
        16u, USAC_M3_CAPTURE_METADATA_LENGTH,
        USAC_M3_SAMPLE_COUNT * 2u, 4u
    };
    uint16_t chunk_length;
    uint16_t again_length;
    uint16_t index;

    usac_config_v2_init_d10x4(&config);
    for (index = 0u; index < 16u; ++index) {
        descriptor.request_id[index] = (uint8_t)index;
        descriptor.boot_id[index] = (uint8_t)(16u + index);
        descriptor.device_id[index] = (uint8_t)(32u + index);
    }
    for (index = 0u; index < 32u; ++index) {
        descriptor.profile_sha256[index] = config.profile_sha256[index];
    }
    descriptor.device_config_crc32 = config.device_config_crc32;
    descriptor.frame_sequence = 5u;
    descriptor.capture_sequence = 1u;
    descriptor.sample_interval_ticks = 120u;
    descriptor.burst_period_ticks = 50u;
    descriptor.tuss_dev_stat = 0x08u;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        descriptor.register_pairs[index] = config.profile.registers[index];
    }
    for (index = 0u; index < USAC_M3_SAMPLE_COUNT; ++index) {
        g_usac_m3_waveform[index] = index;
    }

    usac_m3_capture_stream_init(&stream, &descriptor, g_usac_m3_waveform);
    CHECK(stream.frame_header[12] == 0xD0u && stream.frame_header[13] == 0x10u);
    for (index = 0u; index < 16u; ++index) {
        CHECK(stream.metadata[36u + index] == expected_capture_id[index]);
    }
    for (index = 0u; index < 4u; ++index) {
        CHECK(stream.frame_crc[index] == expected_crc[index]);
    }
    expected_segments[0] = stream.frame_header;
    expected_segments[1] = stream.metadata;
    expected_segments[2] = (const uint8_t *)g_usac_m3_waveform;
    expected_segments[3] = stream.frame_crc;
    for (index = 0u; index < 4u; ++index) {
        CHECK(usac_m3_capture_stream_peek(
            &stream, &chunk, &chunk_length) == 1u);
        CHECK(chunk == expected_segments[index]);
        CHECK(chunk_length == expected_lengths[index]);
        CHECK(usac_m3_capture_stream_peek(
            &stream, &again, &again_length) == 1u);
        CHECK(again == chunk && again_length == chunk_length);
        CHECK(usac_m3_capture_stream_commit(&stream) == 1u);
    }
    CHECK(usac_m3_capture_stream_peek(
        &stream, &chunk, &chunk_length) == 0u);
    CHECK(usac_m3_capture_stream_commit(&stream) == 0u);
    return 0;
}

static int test_m3_capture_tx_commits_only_completed_segments(void)
{
    static const uint16_t expected_lengths[4] = {
        16u, USAC_M3_CAPTURE_METADATA_LENGTH,
        USAC_M3_SAMPLE_COUNT * 2u, 4u
    };
    usac_m3_capture_stream_t stream = {0u};
    usac_m3_capture_tx_t tx;
    const uint8_t *data;
    const uint8_t *again;
    uint16_t length;
    uint16_t again_length;
    uint8_t index;

    stream.samples = g_usac_m3_waveform;
    stream.active = 1u;
    usac_m3_capture_tx_init(&tx, &stream);
    CHECK(tx.state == USAC_M3_TX_READY);
    CHECK(usac_m3_capture_tx_peek(&tx, &data, &length) == 1u);
    CHECK(length == expected_lengths[0]);

    usac_m3_capture_tx_on_start_result(&tx, USAC_M3_TX_START_BUSY);
    CHECK(tx.state == USAC_M3_TX_READY);
    CHECK(stream.phase == 0u);
    CHECK(usac_m3_capture_tx_peek(&tx, &again, &again_length) == 1u);
    CHECK(again == data && again_length == length);

    for (index = 0u; index < 4u; ++index) {
        CHECK(usac_m3_capture_tx_peek(&tx, &data, &length) == 1u);
        CHECK(length == expected_lengths[index]);
        usac_m3_capture_tx_on_start_result(&tx, USAC_M3_TX_START_STARTED);
        CHECK(tx.state == USAC_M3_TX_IN_FLIGHT);
        CHECK(usac_m3_capture_tx_peek(&tx, &again, &again_length) == 0u);
        usac_m3_capture_tx_on_send_completed(&tx);
        CHECK(stream.phase == (uint8_t)(index + 1u));
    }
    CHECK(tx.state == USAC_M3_TX_COMPLETE);
    CHECK(stream.active == 0u);

    stream.phase = 0u;
    stream.active = 1u;
    usac_m3_capture_tx_init(&tx, &stream);
    usac_m3_capture_tx_on_start_result(&tx, USAC_M3_TX_START_FATAL);
    CHECK(tx.state == USAC_M3_TX_FAILED);
    CHECK(stream.phase == 0u && stream.active == 1u);

    usac_m3_capture_tx_init(&tx, &stream);
    usac_m3_capture_tx_on_start_result(
        &tx, (usac_m3_capture_tx_start_result_t)0xFFu);
    CHECK(tx.state == USAC_M3_TX_FAILED);
    CHECK(stream.phase == 0u && stream.active == 1u);
    return 0;
}

static int test_device_identity_and_usb_serial_are_stable(void)
{
    static const uint8_t die_record[10] = {
        0x67u,0x45u,0x23u,0x01u,0xABu,0x89u,0xEFu,0xCDu,0x57u,0x13u
    };
    static const uint8_t expected_device_id[16] = {
        0xCFu,0x6Eu,0x00u,0x07u,0x49u,0x86u,0x51u,0x34u,
        0xA8u,0x35u,0x51u,0x0Eu,0x35u,0x34u,0x6Fu,0x35u
    };
    static const char expected_hex[] = "cf6e000749865134a835510e35346f35";
    uint8_t device_id[16];
    uint8_t descriptor[66];
    uint8_t index;

    usac_identity_derive(die_record, device_id);
    for (index = 0u; index < 16u; ++index) {
        CHECK(device_id[index] == expected_device_id[index]);
    }
    usac_identity_usb_serial_descriptor(device_id, descriptor);
    CHECK(descriptor[0] == 66u);
    CHECK(descriptor[1] == 3u);
    for (index = 0u; index < 32u; ++index) {
        CHECK(descriptor[2u + 2u * index] == (uint8_t)expected_hex[index]);
        CHECK(descriptor[3u + 2u * index] == 0u);
    }
    return 0;
}

static int test_device_identity_rejects_blank_die_records(void)
{
    uint8_t valid[USAC_DIE_RECORD_LENGTH] = {
        0x67u,0x45u,0x23u,0x01u,0xABu,0x89u,0xEFu,0xCDu,0x57u,0x13u
    };
    uint8_t all_zero[USAC_DIE_RECORD_LENGTH] = {0u};
    uint8_t all_ff[USAC_DIE_RECORD_LENGTH];
    uint8_t index;

    for (index = 0u; index < USAC_DIE_RECORD_LENGTH; ++index) {
        all_ff[index] = 0xFFu;
    }
    CHECK(usac_identity_die_record_valid(valid) == 1u);
    CHECK(usac_identity_die_record_valid(all_zero) == 0u);
    CHECK(usac_identity_die_record_valid(all_ff) == 0u);
    return 0;
}

static int test_mcu_sha256_matches_d10x4_canonical_vector(void)
{
    static const uint8_t canonical[35] = {
        0x02u,0x00u,0x78u,0x00u,0x00u,0x08u,0x40u,0x00u,
        0x0Cu,0xE4u,0x0Cu,0x00u,0x32u,0x00u,0x0Au,
        0x10u,0x2Eu,0x11u,0x00u,0x12u,0x00u,0x13u,0x00u,
        0x14u,0x03u,0x16u,0x40u,0x17u,0x07u,0x18u,0x14u,
        0x1Au,0x01u,0x1Bu,0x02u
    };
    static const uint8_t expected[32] = {
        0xB8u,0x82u,0x6Eu,0xAFu,0x27u,0x8Du,0x73u,0x60u,
        0x18u,0x9Du,0x49u,0xACu,0xEDu,0x32u,0x2Fu,0xF9u,
        0xE4u,0x04u,0xD8u,0x26u,0x6Au,0x25u,0xE7u,0x6Au,
        0x01u,0x10u,0x65u,0xC2u,0xFDu,0xA5u,0xC9u,0x98u
    };
    uint8_t digest[32];
    uint8_t index;

    usac_sha256(canonical, (uint16_t)sizeof(canonical), digest);
    for (index = 0u; index < 32u; ++index) {
        CHECK(digest[index] == expected[index]);
    }
    CHECK(usac_mcu_crc32(canonical, (uint16_t)sizeof(canonical)) ==
          0x5D4FC286ul);
    return 0;
}

static int test_config_v2_round_trip_matches_m1_contract(void)
{
    usac_config_v2_t config;
    usac_config_v2_t decoded;
    uint8_t wire[72];
    uint16_t wire_length;

    usac_config_v2_init_d10x4(&config);
    CHECK(config.device_config_crc32 == 0x5D4FC286ul);
    CHECK(usac_config_v2_encode(
              &config, wire, (uint16_t)sizeof(wire), &wire_length) ==
          USAC_CONFIG_V2_OK);
    CHECK(wire_length == 72u);
    CHECK(wire[0] == 0x02u);
    CHECK(wire[2] == 0x78u);
    CHECK(wire[14] == 10u);
    CHECK(wire[16] == 0x10u && wire[17] == 0x2Eu);
    CHECK(wire[34] == 0x1Bu && wire[35] == 0x02u);
    CHECK(usac_config_v2_decode(wire, wire_length, &decoded) ==
          USAC_CONFIG_V2_OK);
    CHECK(decoded.profile.registers[5].value == 0x40u);
    CHECK(decoded.pretrigger_count == 64u);
    CHECK(decoded.device_config_crc32 == config.device_config_crc32);

    wire[36] ^= 0x01u;
    CHECK(usac_config_v2_decode(wire, wire_length, &decoded) ==
          USAC_CONFIG_V2_HASH_MISMATCH);
    return 0;
}

static tuss4470_config_result_t fake_apply_profile(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report)
{
    uint8_t *calls = (uint8_t *)context;
    ++(*calls);
    CHECK(profile->registers[0].value == 0x2Eu);
    report->device_id = 0xB9u;
    report->revision_id = 0x02u;
    report->dev_stat = 0x08u;
    return TUSS4470_CONFIG_OK;
}

static tuss4470_config_result_t fake_apply_profile_failure(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report)
{
    (void)context;
    (void)profile;
    report->device_id = 0xB9u;
    report->revision_id = 0x02u;
    report->dev_stat = 0x02u;
    return TUSS4470_CONFIG_DRIVER_FAULT;
}

static tuss4470_config_result_t fake_force_safe(void *context)
{
    uint8_t *calls = (uint8_t *)context;
    ++(*calls);
    return TUSS4470_CONFIG_OK;
}

static tuss4470_config_result_t fake_force_safe_failure(void *context)
{
    uint8_t *calls = (uint8_t *)context;
    ++(*calls);
    return TUSS4470_CONFIG_BUS;
}

static uint8_t fake_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    usac_m3_loopback_report_t *report)
{
    uint8_t *calls = (uint8_t *)context;
    uint8_t index;

    ++(*calls);
    report->captured_edges = 8u;
    report->final_io2_level = 1u;
    report->pre_tof_config = 0x40u;
    report->pre_vdrv_ctrl = 0x20u;
    report->post_tof_config = 0x40u;
    report->post_vdrv_ctrl = 0x20u;
    for (index = 0u; index < 8u; ++index) {
        report->capture_ticks[index] = (uint16_t)(
            100u + ((uint16_t)index * burst_period_ticks));
    }
    usac_m3_loopback_evaluate(report, burst_period_ticks);
    return 1u;
}

static uint8_t fake_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report)
{
    uint8_t *calls = (uint8_t *)context;
    uint16_t index;

    ++(*calls);
    if ((sample_interval_ticks != 120u) || (burst_period_ticks != 50u)) {
        return 0u;
    }
    for (index = 0u; index < USAC_M3_SAMPLE_COUNT; ++index) {
        g_usac_m3_waveform[index] = index;
    }
    report->captured_samples = USAC_M3_SAMPLE_COUNT;
    report->trigger_sample_index = USAC_M3_PRETRIGGER_COUNT;
    report->dma_remaining = 0u;
    report->burst_completed = 1u;
    report->timed_out = 0u;
    report->tuss_dev_stat = 0x08u;
    return 1u;
}

static int test_m3_app_allows_one_bound_capture_and_returns_ack(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t capture_payload[60] = {0u};
    uint8_t response[128];
    uint8_t first_ack[44];
    uint8_t apply_calls = 0u;
    uint8_t capture_calls = 0u;
    uint8_t safe_calls = 0u;
    uint16_t response_length;
    uint16_t index;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.apply_context = &apply_calls;
    app.apply_profile = fake_apply_profile;
    app.capture_context = &capture_calls;
    app.capture_once = fake_capture_once;
    app.safety_context = &safe_calls;
    app.force_safe = fake_force_safe;
    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 70u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);

    app.loopback_authorized = 1u;
    for (index = 0u; index < 16u; ++index) {
        capture_payload[index] = (uint8_t)(0xC0u + index);
    }
    for (index = 0u; index < 32u; ++index) {
        capture_payload[16u + index] = app.config.profile_sha256[index];
    }
    capture_payload[48] = (uint8_t)app.config.device_config_crc32;
    capture_payload[49] = (uint8_t)(app.config.device_config_crc32 >> 8);
    capture_payload[50] = (uint8_t)(app.config.device_config_crc32 >> 16);
    capture_payload[51] = (uint8_t)(app.config.device_config_crc32 >> 24);
    request.message_type = 0x05u;
    request.sequence = 71u;
    request.payload_length = 60u;
    request.payload = capture_payload;

    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Eu);
    CHECK(response[32] == 0x05u);
    CHECK(apply_calls == 1u);
    CHECK(capture_calls == 1u);
    CHECK(safe_calls == 1u);
    CHECK(app.capture_pending == 1u);
    CHECK(app.loopback_authorized == 0u);
    CHECK(app.profile_active == 0u);
    CHECK(app.capture_report.captured_samples == USAC_M3_SAMPLE_COUNT);
    CHECK(g_usac_m3_waveform[0] == 0u);
    CHECK(g_usac_m3_waveform[2047] == 2047u);
    CHECK(response_length == sizeof(first_ack));
    for (index = 0u; index < response_length; ++index) {
        first_ack[index] = response[index];
    }
    app.capture_pending = 0u;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(apply_calls == 1u);
    CHECK(capture_calls == 1u);
    CHECK(safe_calls == 1u);
    CHECK(app.capture_pending == 1u);
    for (index = 0u; index < response_length; ++index) {
        CHECK(response[index] == first_ack[index]);
    }
    return 0;
}

static int test_m3_app_runs_and_caches_io2_loopback_evidence(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t loopback_payload[56] = {0u};
    uint8_t first_response[128];
    uint8_t retry_response[128];
    uint8_t calls = 0u;
    uint16_t first_length;
    uint16_t retry_length;
    uint16_t index;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.loopback_context = &calls;
    app.run_io2_loopback = fake_run_io2_loopback;
    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 60u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, first_response, sizeof(first_response),
              &first_length) == 1u);

    for (index = 0u; index < 16u; ++index) {
        loopback_payload[index] = (uint8_t)(0xA0u + index);
    }
    for (index = 0u; index < 32u; ++index) {
        loopback_payload[16u + index] = app.config.profile_sha256[index];
    }
    loopback_payload[48] = (uint8_t)app.config.device_config_crc32;
    loopback_payload[49] = (uint8_t)(app.config.device_config_crc32 >> 8);
    loopback_payload[50] = (uint8_t)(app.config.device_config_crc32 >> 16);
    loopback_payload[51] = (uint8_t)(app.config.device_config_crc32 >> 24);
    loopback_payload[52] = 8u;
    request.message_type = 0x0Eu;
    request.sequence = 61u;
    request.payload_length = 56u;
    request.payload = loopback_payload;

    CHECK(usac_m2_app_handle(
              &app, &request, first_response, sizeof(first_response),
              &first_length) == 1u);
    CHECK(calls == 1u);
    CHECK(first_length == 106u);
    CHECK(first_response[5] == 0x0Eu);
    CHECK(first_response[6] == 1u && first_response[7] == 0u);
    CHECK(first_response[71] == USAC_M3_LOOPBACK_PASS);
    CHECK(app.loopback_authorized == 1u);
    CHECK(app.profile_active == 0u);

    CHECK(usac_m2_app_handle(
              &app, &request, retry_response, sizeof(retry_response),
              &retry_length) == 1u);
    CHECK(calls == 1u);
    CHECK(retry_length == first_length);
    for (index = 0u; index < first_length; ++index) {
        CHECK(retry_response[index] == first_response[index]);
    }
    return 0;
}

static int test_m2_app_replies_and_never_captures(void)
{
    static const uint8_t device_id[16] = {
        0u,1u,2u,3u,4u,5u,6u,7u,8u,9u,10u,11u,12u,13u,14u,15u
    };
    static const uint8_t initial_boot_id[16] = {0u};
    static const uint8_t expected_boot_id[16] = {
        0xB7u,0x60u,0xF6u,0x38u,0x39u,0xD3u,0x11u,0x9Du,
        0x87u,0xC2u,0xC1u,0xFAu,0x18u,0x20u,0xB5u,0xFDu
    };
    uint8_t hello_payload[20] = {
        16u,17u,18u,19u,20u,21u,22u,23u,
        24u,25u,26u,27u,28u,29u,30u,31u,
        1u,1u,0u,0u
    };
    uint8_t capture_payload[60] = {0u};
    uint8_t response[128];
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;
    uint8_t index;

    usac_m2_app_init(&app, device_id, initial_boot_id, 3u, USAC_M2_IDLE_SAFE);
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 0x11223344ul;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response_length == 84u);
    CHECK(response[5] == 0x01u);
    CHECK(response[6] == 0x01u && response[7] == 0u);
    CHECK(response[8] == 0x44u && response[11] == 0x11u);
    CHECK(response[12] == 64u);
    CHECK(response[16] == 16u && response[31] == 31u);
    for (index = 0u; index < 16u; ++index) {
        CHECK(response[32u + index] == expected_boot_id[index]);
    }
    CHECK(response[48] == 0u && response[63] == 15u);

    request.message_type = 0x03u;
    request.sequence = 2u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x03u);
    CHECK(response[12] == 72u);

    capture_payload[52] = 0u;
    request.message_type = 0x05u;
    request.sequence = 3u;
    request.payload_length = 60u;
    request.payload = capture_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Fu);
    CHECK(response[34] == 5u && response[35] == 0u);
    CHECK(usac_m2_core_burst_permitted(&app.core) == 0u);
    return 0;
}

static int test_m2_app_requires_hello_before_other_commands(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t response[128];
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_SESSION_WAIT);
    request.message_type = 0x03u;
    request.flags = 0u;
    request.sequence = 4u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Fu);
    CHECK(response[34] == 5u && response[35] == 0u);

    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.sequence = 5u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x01u);
    CHECK(app.core.state == USAC_M2_IDLE_SAFE);
    usac_m2_app_end_session(&app);
    request.message_type = 0x03u;
    request.sequence = 6u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Fu);
    CHECK(response[34] == 5u && response[35] == 0u);

    request.message_type = 0x01u;
    request.sequence = 7u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    request.message_type = 0x03u;
    request.sequence = 8u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x03u);
    CHECK(response[12] == 72u);

    return 0;
}

static int test_dtr_gate_requires_low_then_rising_edge(void)
{
    usac_dtr_gate_t gate;

    usac_dtr_gate_reset(&gate);
    CHECK(usac_dtr_gate_ready(&gate) == 0u);
    usac_dtr_gate_update(&gate, 1u);
    CHECK(usac_dtr_gate_ready(&gate) == 0u);
    usac_dtr_gate_update(&gate, 0u);
    CHECK(usac_dtr_gate_ready(&gate) == 0u);
    usac_dtr_gate_update(&gate, 1u);
    CHECK(usac_dtr_gate_ready(&gate) == 1u);
    usac_dtr_gate_update(&gate, 1u);
    CHECK(usac_dtr_gate_ready(&gate) == 1u);
    usac_dtr_gate_update(&gate, 0u);
    CHECK(usac_dtr_gate_ready(&gate) == 0u);
    return 0;
}

static int test_tx_gate_prevents_response_buffer_reuse(void)
{
    usac_tx_gate_t gate;

    usac_tx_gate_reset(&gate);
    CHECK(usac_tx_gate_can_encode(&gate) == 1u);
    usac_tx_gate_started(&gate);
    CHECK(usac_tx_gate_can_encode(&gate) == 0u);
    usac_tx_gate_completed(&gate);
    CHECK(usac_tx_gate_can_encode(&gate) == 1u);
    return 0;
}

static int test_new_hello_nonce_ends_old_session_but_preserves_verified_config(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t response[128];
    uint8_t first_boot_id[16];
    uint8_t safe_calls = 0u;
    uint8_t index;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.safety_context = &safe_calls;
    app.force_safe = fake_force_safe;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 30u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    for (index = 0u; index < 16u; ++index) {
        first_boot_id[index] = app.boot_id[index];
    }
    request.sequence = 30u;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    for (index = 0u; index < 16u; ++index) {
        CHECK(app.boot_id[index] == first_boot_id[index]);
    }
    CHECK(app.config_valid == 1u);
    CHECK(app.profile_active == 1u);
    CHECK(safe_calls == 0u);

    hello_payload[0] = 1u;
    request.sequence = 31u;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(app.config_valid == 1u);
    CHECK(app.profile_active == 0u);
    CHECK(safe_calls == 1u);
    request.message_type = 0x03u;
    request.sequence = 32u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x03u);
    return 0;
}

static int test_failed_safe_transition_invalidates_config_and_active_profile(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t safe_calls = 0u;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.safety_context = &safe_calls;
    app.force_safe = fake_force_safe_failure;
    CHECK(app.config_valid == 1u);
    CHECK(app.profile_active == 1u);

    usac_m2_app_end_session(&app);

    CHECK(safe_calls == 1u);
    CHECK(app.core.state == USAC_M2_FAULT);
    CHECK(app.config_valid == 0u);
    CHECK(app.profile_active == 0u);
    return 0;
}

static int test_m2_set_config_acks_only_after_apply(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t request_payload[120] = {0u};
    uint8_t response[128];
    uint8_t calls = 0u;
    uint16_t config_length;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.apply_context = &calls;
    app.apply_profile = fake_apply_profile;
    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 8u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x01u);
    for (config_length = 0u; config_length < 32u; ++config_length) {
        request_payload[16u + config_length] = app.config.profile_sha256[config_length];
    }
    CHECK(usac_config_v2_encode(
              &app.config, &request_payload[48], 72u, &config_length) ==
          USAC_CONFIG_V2_OK);
    request.message_type = 0x04u;
    request.sequence = 9u;
    request.payload_length = 120u;
    request.payload = request_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(calls == 1u);
    CHECK(response[5] == 0x7Eu);
    CHECK(response[12] == 24u);
    CHECK(response[32] == 0x04u);
    CHECK(response[34] == 0u && response[35] == 0u);
    return 0;
}

static int test_m2_retransmitted_set_config_reuses_response_without_reapply(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t request_payload[120] = {0u};
    uint8_t first_response[128];
    uint8_t retry_response[128];
    uint8_t calls = 0u;
    uint16_t config_length;
    uint16_t first_length;
    uint16_t retry_length;
    uint16_t index;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    app.apply_context = &calls;
    app.apply_profile = fake_apply_profile;
    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 40u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, first_response, sizeof(first_response),
              &first_length) == 1u);
    for (index = 0u; index < 16u; ++index) {
        request_payload[index] = (uint8_t)(0x80u + index);
    }
    for (index = 0u; index < 32u; ++index) {
        request_payload[16u + index] = app.config.profile_sha256[index];
    }
    CHECK(usac_config_v2_encode(
              &app.config, &request_payload[48], 72u, &config_length) ==
          USAC_CONFIG_V2_OK);
    request.message_type = 0x04u;
    request.sequence = 41u;
    request.payload_length = 120u;
    request.payload = request_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, first_response, sizeof(first_response),
              &first_length) == 1u);
    CHECK(calls == 1u);
    CHECK(usac_m2_app_handle(
              &app, &request, retry_response, sizeof(retry_response),
              &retry_length) == 1u);
    CHECK(calls == 1u);
    CHECK(retry_length == first_length);
    for (index = 0u; index < first_length; ++index) {
        CHECK(retry_response[index] == first_response[index]);
    }
    return 0;
}

static int test_m2_failed_apply_invalidates_reported_config(void)
{
    uint8_t zero_id[16] = {0u};
    uint8_t hello_payload[20] = {0u};
    uint8_t request_payload[120] = {0u};
    uint8_t response[128];
    uint16_t index;
    uint16_t config_length;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_m2_app_t app;

    usac_m2_app_init(&app, zero_id, zero_id, 0u, USAC_M2_IDLE_SAFE);
    hello_payload[16] = 1u;
    hello_payload[17] = 1u;
    request.message_type = 0x01u;
    request.flags = 0u;
    request.sequence = 20u;
    request.payload_length = 20u;
    request.payload = hello_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);

    app.apply_profile = fake_apply_profile_failure;
    for (index = 0u; index < 32u; ++index) {
        request_payload[16u + index] = app.config.profile_sha256[index];
    }
    CHECK(usac_config_v2_encode(
              &app.config, &request_payload[48], 72u, &config_length) ==
          USAC_CONFIG_V2_OK);
    request.message_type = 0x04u;
    request.sequence = 21u;
    request.payload_length = 120u;
    request.payload = request_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Fu);

    request.message_type = 0x03u;
    request.sequence = 22u;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Fu);
    CHECK(response[34] == 5u && response[35] == 0u);

    app.apply_profile = fake_apply_profile;
    request_payload[0] = 1u;
    for (index = 0u; index < 32u; ++index) {
        request_payload[16u + index] = 0u;
    }
    request.message_type = 0x04u;
    request.sequence = 23u;
    request.payload_length = 120u;
    request.payload = request_payload;
    CHECK(usac_m2_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Eu);
    CHECK(app.config_valid == 1u);
    CHECK(app.profile_active == 1u);
    return 0;
}

volatile int g_usac_test_result = -1;

void __attribute__((noinline)) usac_test_complete(void)
{
    __no_operation();
    for (;;) {
    }
}

int main(void)
{
    int result;

    result = test_reset_is_safe();
    if (result != 0) goto complete;
    result = test_m2_never_releases_burst();
    if (result != 0) goto complete;
    result = test_timer_ranges_are_bounded();
    if (result != 0) goto complete;
    result = test_clock_gate_ignores_only_unused_xt1_fault();
    if (result != 0) goto complete;
    result = test_official_spi_vectors();
    if (result != 0) goto complete;
    result = test_d10x4_default_profile_is_complete();
    if (result != 0) goto complete;
    result = test_profile_rejects_hardware_unsafe_values();
    if (result != 0) goto complete;
    result = test_configurator_applies_safe_order_and_reaches_ready();
    if (result != 0) goto complete;
    result = test_configurator_fails_closed_on_identity_readback_and_status();
    if (result != 0) goto complete;
    result = test_mcu_parser_accepts_m1_hello_vector();
    if (result != 0) goto complete;
    result = test_mcu_encoder_reproduces_m1_hello_vector();
    if (result != 0) goto complete;
    result = test_mcu_parser_bounds_input_and_resynchronizes();
    if (result != 0) goto complete;
    result = test_mcu_parser_rejects_crc_then_accepts_next_frame();
    if (result != 0) goto complete;
    result = test_mcu_parser_timeout_discards_partial_candidate();
    if (result != 0) goto complete;
    result = test_m2_parser_rejects_short_set_config();
    if (result != 0) goto complete;
    result = test_mcu_parser_passes_unknown_bounded_command_to_app();
    if (result != 0) goto complete;
    result = test_m3_parser_validates_io2_loopback_command();
    if (result != 0) goto complete;
    result = test_m3_loopback_evaluation_requires_exact_stable_edges();
    if (result != 0) goto complete;
    result = test_m3_capture_report_requires_exact_dma_evidence();
    if (result != 0) goto complete;
    result = test_m3_segmented_crc_matches_iso_hdlc_vector();
    if (result != 0) goto complete;
    result = test_m3_capture_stream_matches_python_fixed_vector();
    if (result != 0) goto complete;
    result = test_m3_capture_tx_commits_only_completed_segments();
    if (result != 0) goto complete;
    result = test_device_identity_and_usb_serial_are_stable();
    if (result != 0) goto complete;
    result = test_device_identity_rejects_blank_die_records();
    if (result != 0) goto complete;
    result = test_mcu_sha256_matches_d10x4_canonical_vector();
    if (result != 0) goto complete;
    result = test_config_v2_round_trip_matches_m1_contract();
    if (result != 0) goto complete;
    result = test_m2_app_replies_and_never_captures();
    if (result != 0) goto complete;
    result = test_m3_app_runs_and_caches_io2_loopback_evidence();
    if (result != 0) goto complete;
    result = test_m3_app_allows_one_bound_capture_and_returns_ack();
    if (result != 0) goto complete;
    result = test_m2_app_requires_hello_before_other_commands();
    if (result != 0) goto complete;
    result = test_dtr_gate_requires_low_then_rising_edge();
    if (result != 0) goto complete;
    result = test_tx_gate_prevents_response_buffer_reuse();
    if (result != 0) goto complete;
    result = test_new_hello_nonce_ends_old_session_but_preserves_verified_config();
    if (result != 0) goto complete;
    result = test_failed_safe_transition_invalidates_config_and_active_profile();
    if (result != 0) goto complete;
    result = test_m2_set_config_acks_only_after_apply();
    if (result != 0) goto complete;
    result = test_m2_retransmitted_set_config_reuses_response_without_reapply();
    if (result != 0) goto complete;
    result = test_m2_failed_apply_invalidates_reported_config();

complete:
    g_usac_test_result = result;
    usac_test_complete();
    return 0;
}
