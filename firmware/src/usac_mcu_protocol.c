/* Bounded USAC v1 parser/encoder for the 8 KB MSP430. It validates header,
 * message-specific length, and CRC without allocating a host-sized frame;
 * malformed candidates are discarded deterministically for resynchronization. */
#include "usac_mcu_protocol.h"

#define USAC_PROTOCOL_VERSION 1u
#define USAC_MESSAGE_HELLO 0x01u
#define USAC_MESSAGE_GET_CAPABILITIES 0x02u
#define USAC_MESSAGE_GET_CONFIG 0x03u
#define USAC_MESSAGE_SET_CONFIG 0x04u
#define USAC_MESSAGE_CAPTURE_ONCE 0x05u
#define USAC_MESSAGE_START_PERIODIC 0x06u
#define USAC_MESSAGE_STOP 0x07u
#define USAC_MESSAGE_GET_STATUS 0x08u
#define USAC_MESSAGE_RENEW_PERIODIC_LEASE 0x0Cu
#define USAC_MESSAGE_RUN_IO2_LOOPBACK_TEST 0x0Eu

static const uint8_t magic[4] = {0x55u, 0x53u, 0x41u, 0x43u};

static uint16_t read_u16_le(const uint8_t *data)
{
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

static uint32_t read_u32_le(const uint8_t *data)
{
    return (uint32_t)data[0] |
           ((uint32_t)data[1] << 8) |
           ((uint32_t)data[2] << 16) |
           ((uint32_t)data[3] << 24);
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

uint32_t usac_mcu_crc32(const uint8_t *data, uint16_t length)
{
    uint32_t crc = 0xFFFFFFFFul;
    uint16_t index;
    uint8_t bit;

    for (index = 0u; index < length; ++index) {
        crc ^= data[index];
        for (bit = 0u; bit < 8u; ++bit) {
            if ((crc & 1u) != 0u) {
                crc = (crc >> 1) ^ 0xEDB88320ul;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc ^ 0xFFFFFFFFul;
}

uint8_t usac_mcu_encode_frame(
    uint8_t message_type,
    uint16_t flags,
    uint32_t sequence,
    const uint8_t *payload,
    uint16_t payload_length,
    uint8_t *output,
    uint16_t output_capacity,
    uint16_t *output_length)
{
    uint16_t total_length = (uint16_t)(
        USAC_MCU_HEADER_SIZE + payload_length + USAC_MCU_CRC_SIZE);
    uint16_t index;
    uint32_t crc;

    if ((output == 0) || (output_length == 0) ||
        (payload_length > USAC_MCU_MAX_COMMAND_PAYLOAD) ||
        ((payload_length != 0u) && (payload == 0)) ||
        (output_capacity < total_length) || ((flags & (uint16_t)~0x0007u) != 0u)) {
        return 0u;
    }
    output[0] = magic[0];
    output[1] = magic[1];
    output[2] = magic[2];
    output[3] = magic[3];
    output[4] = USAC_PROTOCOL_VERSION;
    output[5] = message_type;
    write_u16_le(&output[6], flags);
    write_u32_le(&output[8], sequence);
    write_u32_le(&output[12], payload_length);
    for (index = 0u; index < payload_length; ++index) {
        output[USAC_MCU_HEADER_SIZE + index] = payload[index];
    }
    crc = usac_mcu_crc32(&output[4], (uint16_t)(12u + payload_length));
    write_u32_le(&output[USAC_MCU_HEADER_SIZE + payload_length], crc);
    *output_length = total_length;
    return 1u;
}

void usac_mcu_parser_init(usac_mcu_parser_t *parser)
{
    parser->count = 0u;
    parser->expected_total = 0u;
}

static void reset_parser(usac_mcu_parser_t *parser)
{
    parser->count = 0u;
    parser->expected_total = 0u;
}

usac_mcu_parse_result_t usac_mcu_parser_expire(usac_mcu_parser_t *parser)
{
    reset_parser(parser);
    return USAC_MCU_PARSE_TIMEOUT;
}

static usac_mcu_parse_result_t validate_header(
    usac_mcu_parser_t *parser,
    uint32_t payload_length)
{
    uint8_t message_type = parser->buffer[5];
    uint16_t flags = read_u16_le(&parser->buffer[6]);

    if ((parser->buffer[4] != USAC_PROTOCOL_VERSION) ||
        ((flags & (uint16_t)~0x0007u) != 0u)) {
        reset_parser(parser);
        return USAC_MCU_PARSE_INVALID_HEADER;
    }
    if (payload_length > USAC_MCU_MAX_COMMAND_PAYLOAD) {
        reset_parser(parser);
        return USAC_MCU_PARSE_INVALID_LENGTH;
    }
    if (((message_type == USAC_MESSAGE_HELLO) && (payload_length != 20u)) ||
        ((message_type == USAC_MESSAGE_GET_CAPABILITIES) &&
         (payload_length != 0u)) ||
        ((message_type == USAC_MESSAGE_GET_CONFIG) && (payload_length != 0u)) ||
        ((message_type == USAC_MESSAGE_CAPTURE_ONCE) &&
         (payload_length != 60u)) ||
        ((message_type == USAC_MESSAGE_RUN_IO2_LOOPBACK_TEST) &&
         (payload_length != 56u)) ||
        ((message_type == USAC_MESSAGE_START_PERIODIC) &&
         (payload_length != 80u)) ||
        ((message_type == USAC_MESSAGE_STOP) && (payload_length != 32u)) ||
        ((message_type == USAC_MESSAGE_GET_STATUS) &&
         (payload_length != 0u)) ||
        ((message_type == USAC_MESSAGE_RENEW_PERIODIC_LEASE) &&
         (payload_length != 40u)) ||
        ((message_type == USAC_MESSAGE_SET_CONFIG) &&
         (payload_length != 120u))) {
        reset_parser(parser);
        return USAC_MCU_PARSE_INVALID_LENGTH;
    }
    parser->expected_total = (uint16_t)(
        USAC_MCU_HEADER_SIZE + payload_length + USAC_MCU_CRC_SIZE);
    return USAC_MCU_PARSE_INCOMPLETE;
}

static usac_mcu_parse_result_t validate_payload(
    const usac_mcu_parser_t *parser)
{
    const uint8_t *payload = &parser->buffer[USAC_MCU_HEADER_SIZE];
    uint8_t message_type = parser->buffer[5];

    if (message_type == USAC_MESSAGE_HELLO) {
        if ((payload[16] > payload[17]) || (payload[18] != 0u) ||
            (payload[19] != 0u) || (payload[16] > USAC_PROTOCOL_VERSION) ||
            (payload[17] < USAC_PROTOCOL_VERSION)) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    } else if (message_type == USAC_MESSAGE_SET_CONFIG) {
        uint8_t register_count = payload[62u];
        if (register_count != 10u) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    } else if (message_type == USAC_MESSAGE_CAPTURE_ONCE) {
        if ((payload[53] != 0u) || (payload[54] != 0u) ||
            (payload[55] != 0u) || (payload[52] > 2u)) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    } else if (message_type == USAC_MESSAGE_RUN_IO2_LOOPBACK_TEST) {
        if ((payload[52] != 8u) || (payload[53] != 0u) ||
            (payload[54] != 0u) || (payload[55] != 0u)) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    } else if (message_type == USAC_MESSAGE_START_PERIODIC) {
        uint8_t id_bits = 0u;
        uint8_t index;
        uint32_t period_us = read_u32_le(&payload[68]);
        uint32_t lease_timeout_ms = read_u32_le(&payload[76]);
        for (index = 16u; index < 32u; ++index) {
            id_bits |= payload[index];
        }
        if ((id_bits == 0u) || (period_us < 100000ul) ||
            (lease_timeout_ms < 1000ul) ||
            (lease_timeout_ms > 10000ul)) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    } else if (message_type == USAC_MESSAGE_RENEW_PERIODIC_LEASE) {
        if ((read_u32_le(&payload[32]) == 0ul) ||
            (read_u32_le(&payload[36]) < 1000ul) ||
            (read_u32_le(&payload[36]) > 10000ul)) {
            return USAC_MCU_PARSE_INVALID_PAYLOAD;
        }
    }
    return USAC_MCU_PARSE_FRAME;
}

usac_mcu_parse_result_t usac_mcu_parser_feed(
    usac_mcu_parser_t *parser,
    uint8_t byte,
    usac_mcu_frame_view_t *frame)
{
    uint32_t payload_length;
    uint32_t expected_crc;
    uint32_t actual_crc;
    usac_mcu_parse_result_t result;

    if (parser->count < 4u) {
        if (byte != magic[parser->count]) {
            parser->count = (byte == magic[0]) ? 1u : 0u;
            if (parser->count == 1u) {
                parser->buffer[0] = byte;
            }
            return USAC_MCU_PARSE_INCOMPLETE;
        }
    }

    if (parser->count >= USAC_MCU_RX_RING_SIZE) {
        reset_parser(parser);
        return USAC_MCU_PARSE_INVALID_LENGTH;
    }
    parser->buffer[parser->count++] = byte;

    if (parser->count == USAC_MCU_HEADER_SIZE) {
        payload_length = read_u32_le(&parser->buffer[12]);
        result = validate_header(parser, payload_length);
        if (result != USAC_MCU_PARSE_INCOMPLETE) {
            return result;
        }
    }
    if ((parser->expected_total == 0u) ||
        (parser->count < parser->expected_total)) {
        return USAC_MCU_PARSE_INCOMPLETE;
    }

    payload_length = read_u32_le(&parser->buffer[12]);
    expected_crc = read_u32_le(&parser->buffer[16u + payload_length]);
    actual_crc = usac_mcu_crc32(
        &parser->buffer[4],
        (uint16_t)(12u + payload_length));
    if (expected_crc != actual_crc) {
        reset_parser(parser);
        return USAC_MCU_PARSE_BAD_CRC;
    }

    result = validate_payload(parser);
    if (result != USAC_MCU_PARSE_FRAME) {
        reset_parser(parser);
        return result;
    }
    frame->message_type = parser->buffer[5];
    frame->flags = read_u16_le(&parser->buffer[6]);
    frame->sequence = read_u32_le(&parser->buffer[8]);
    frame->payload_length = (uint16_t)payload_length;
    frame->payload = &parser->buffer[USAC_MCU_HEADER_SIZE];
    reset_parser(parser);
    return USAC_MCU_PARSE_FRAME;
}
