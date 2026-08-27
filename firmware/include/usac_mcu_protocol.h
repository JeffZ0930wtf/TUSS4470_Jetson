#ifndef USAC_MCU_PROTOCOL_H
#define USAC_MCU_PROTOCOL_H

#include <stdint.h>

#define USAC_MCU_RX_RING_SIZE 256u
#define USAC_MCU_MAX_COMMAND_PAYLOAD 192u
#define USAC_MCU_HEADER_SIZE 16u
#define USAC_MCU_CRC_SIZE 4u

typedef struct {
    uint8_t buffer[USAC_MCU_RX_RING_SIZE];
    uint16_t count;
    uint16_t expected_total;
} usac_mcu_parser_t;

typedef struct {
    uint8_t message_type;
    uint16_t flags;
    uint32_t sequence;
    uint16_t payload_length;
    const uint8_t *payload;
} usac_mcu_frame_view_t;

typedef enum {
    USAC_MCU_PARSE_INCOMPLETE = 0,
    USAC_MCU_PARSE_FRAME = 1,
    USAC_MCU_PARSE_INVALID_LENGTH = 2,
    USAC_MCU_PARSE_BAD_CRC = 3,
    USAC_MCU_PARSE_INVALID_HEADER = 4,
    USAC_MCU_PARSE_UNSUPPORTED_TYPE = 5,
    USAC_MCU_PARSE_INVALID_PAYLOAD = 6,
    USAC_MCU_PARSE_TIMEOUT = 7
} usac_mcu_parse_result_t;

void usac_mcu_parser_init(usac_mcu_parser_t *parser);
usac_mcu_parse_result_t usac_mcu_parser_expire(usac_mcu_parser_t *parser);
usac_mcu_parse_result_t usac_mcu_parser_feed(
    usac_mcu_parser_t *parser,
    uint8_t byte,
    usac_mcu_frame_view_t *frame);
uint32_t usac_mcu_crc32(const uint8_t *data, uint16_t length);
uint8_t usac_mcu_encode_frame(
    uint8_t message_type,
    uint16_t flags,
    uint32_t sequence,
    const uint8_t *payload,
    uint16_t payload_length,
    uint8_t *output,
    uint16_t output_capacity,
    uint16_t *output_length);

#endif
