#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_VECTOR_BYTES 5000u

static uint32_t crc32_iso_hdlc(const uint8_t *data, size_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    size_t index;
    unsigned int bit;

    for (index = 0; index < length; ++index) {
        crc ^= data[index];
        for (bit = 0; bit < 8u; ++bit) {
            crc = (crc >> 1) ^ (UINT32_C(0xEDB88320) & (0u - (crc & 1u)));
        }
    }
    return crc ^ UINT32_C(0xFFFFFFFF);
}

static uint32_t read_u32_le(const uint8_t *data)
{
    return (uint32_t)data[0] |
           ((uint32_t)data[1] << 8) |
           ((uint32_t)data[2] << 16) |
           ((uint32_t)data[3] << 24);
}

static void write_u16_le(uint8_t *output, uint16_t value)
{
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8);
}

static void write_u32_le(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8);
    output[2] = (uint8_t)(value >> 16);
    output[3] = (uint8_t)(value >> 24);
}

static size_t read_hex_file(const char *path, uint8_t *output, size_t capacity)
{
    FILE *stream = fopen(path, "r");
    size_t length = 0u;
    unsigned int byte;

    if (stream == NULL) {
        perror(path);
        exit(2);
    }
    while (fscanf(stream, "%2x", &byte) == 1) {
        if (length >= capacity) {
            fprintf(stderr, "%s exceeds test vector capacity\n", path);
            exit(2);
        }
        output[length++] = (uint8_t)byte;
    }
    if (fclose(stream) != 0) {
        perror(path);
        exit(2);
    }
    return length;
}

static int check_frame(const uint8_t *frame, size_t length, uint8_t type,
                       uint32_t sequence, uint32_t payload_length)
{
    uint32_t supplied_crc;
    uint32_t calculated_crc;

    if (length != 16u + payload_length + 4u ||
        memcmp(frame, "USAC", 4u) != 0 || frame[4] != 1u || frame[5] != type ||
        read_u32_le(frame + 8u) != sequence || read_u32_le(frame + 12u) != payload_length) {
        return 0;
    }
    supplied_crc = read_u32_le(frame + length - 4u);
    calculated_crc = crc32_iso_hdlc(frame + 4u, length - 8u);
    return supplied_crc == calculated_crc;
}

static size_t encode_frame(uint8_t *output, uint8_t type, uint16_t flags,
                           uint32_t sequence, const uint8_t *payload,
                           uint32_t payload_length)
{
    size_t length = 16u + payload_length + 4u;
    memcpy(output, "USAC", 4u);
    output[4] = 1u;
    output[5] = type;
    write_u16_le(output + 6u, flags);
    write_u32_le(output + 8u, sequence);
    write_u32_le(output + 12u, payload_length);
    memcpy(output + 16u, payload, payload_length);
    write_u32_le(output + length - 4u, crc32_iso_hdlc(output + 4u, length - 8u));
    return length;
}

static uint16_t encode_spi(uint8_t address, uint8_t value, int read)
{
    uint16_t frame = (uint16_t)(((uint16_t)(read != 0) << 15) |
                                ((uint16_t)address << 9) | value);
    uint16_t bits = frame;
    unsigned int ones = 0u;

    while (bits != 0u) {
        ones += bits & 1u;
        bits >>= 1;
    }
    if ((ones & 1u) == 0u) {
        frame |= UINT16_C(0x0100);
    }
    return frame;
}

int main(void)
{
    uint8_t hello[MAX_VECTOR_BYTES];
    uint8_t profile[MAX_VECTOR_BYTES];
    uint8_t capture[MAX_VECTOR_BYTES];
    uint8_t rebuilt[MAX_VECTOR_BYTES];
    uint8_t rebuilt_profile[35];
    static const uint8_t pairs[20] = {
        0x10,0x2E,0x11,0x00,0x12,0x00,0x13,0x00,0x14,0x03,
        0x16,0x40,0x17,0x07,0x18,0x14,0x1A,0x01,0x1B,0x02
    };
    size_t hello_length = read_hex_file("protocol/vectors/hello-request-v1.hex", hello, sizeof hello);
    size_t profile_length = read_hex_file("protocol/vectors/d10x4-profile-canonical-v2.hex", profile, sizeof profile);
    size_t capture_length = read_hex_file("protocol/vectors/capture-data-v1.hex", capture, sizeof capture);
    size_t rebuilt_length;

    if (!check_frame(hello, hello_length, 0x01u, 1u, 20u) ||
        read_u32_le(hello + hello_length - 4u) != UINT32_C(0xCD2E6207)) {
        fputs("HELLO vector failed\n", stderr);
        return 1;
    }
    rebuilt_length = encode_frame(rebuilt, 0x01u, 0u, 1u, hello + 16u, 20u);
    if (rebuilt_length != hello_length || memcmp(rebuilt, hello, hello_length) != 0) {
        fputs("HELLO re-encode failed\n", stderr);
        return 1;
    }

    memset(rebuilt_profile, 0, sizeof rebuilt_profile);
    write_u16_le(rebuilt_profile + 0u, 2u);
    write_u16_le(rebuilt_profile + 2u, 120u);
    write_u16_le(rebuilt_profile + 4u, 2048u);
    write_u16_le(rebuilt_profile + 6u, 64u);
    rebuilt_profile[8] = 12u;
    write_u16_le(rebuilt_profile + 9u, 3300u);
    rebuilt_profile[11] = 0u;
    write_u16_le(rebuilt_profile + 12u, 50u);
    rebuilt_profile[14] = 10u;
    memcpy(rebuilt_profile + 15u, pairs, sizeof pairs);
    if (profile_length != sizeof rebuilt_profile ||
        memcmp(profile, rebuilt_profile, sizeof rebuilt_profile) != 0 ||
        crc32_iso_hdlc(profile, profile_length) != UINT32_C(0x5D4FC286)) {
        fputs("profile canonical vector failed\n", stderr);
        return 1;
    }

    if (!check_frame(capture, capture_length, 0x40u, 7u, 232u)) {
        fputs("CAPTURE_DATA vector failed\n", stderr);
        return 1;
    }
    rebuilt_length = encode_frame(rebuilt, 0x40u, 1u, 7u, capture + 16u, 232u);
    if (rebuilt_length != capture_length || memcmp(rebuilt, capture, capture_length) != 0 ||
        read_u32_le(capture + capture_length - 4u) != UINT32_C(0x2E7902E2)) {
        fputs("CAPTURE_DATA re-encode failed\n", stderr);
        return 1;
    }
    if (capture[capture_length - 12u] != 0u || capture[capture_length - 11u] != 0u ||
        capture[capture_length - 10u] != 1u || capture[capture_length - 9u] != 0u ||
        capture[capture_length - 8u] != 0xFFu || capture[capture_length - 7u] != 0x0Fu ||
        capture[capture_length - 6u] != 0u || capture[capture_length - 5u] != 8u) {
        fputs("CAPTURE_DATA sample decode failed\n", stderr);
        return 1;
    }
    if (encode_spi(0x10u, 0x2Eu, 0) != UINT16_C(0x202E) ||
        encode_spi(0x10u, 0u, 1) != UINT16_C(0xA100) ||
        encode_spi(0x16u, 0x40u, 0) != UINT16_C(0x2D40) ||
        encode_spi(0x16u, 0u, 1) != UINT16_C(0xAD00) ||
        encode_spi(0x1Au, 0x01u, 0) != UINT16_C(0x3501) ||
        encode_spi(0x1Au, 0u, 1) != UINT16_C(0xB500)) {
        fputs("TUSS4470 SPI odd-parity vectors failed\n", stderr);
        return 1;
    }

    puts("C protocol vectors: PASS");
    return 0;
}
/* Cross-language fixed-vector check. This host test validates committed USAC
 * bytes and CRC behavior; it is not compiled into MSP430 firmware. */
