/* Small allocation-free SHA-256 implementation for fixed identity and profile
 * material on MSP430. It is first-party code and has no streaming API because
 * all M2 inputs are short, bounded buffers. */
#include "usac_sha256.h"

static const uint32_t round_constants[64] = {
    0x428A2F98ul,0x71374491ul,0xB5C0FBCFul,0xE9B5DBA5ul,
    0x3956C25Bul,0x59F111F1ul,0x923F82A4ul,0xAB1C5ED5ul,
    0xD807AA98ul,0x12835B01ul,0x243185BEul,0x550C7DC3ul,
    0x72BE5D74ul,0x80DEB1FEul,0x9BDC06A7ul,0xC19BF174ul,
    0xE49B69C1ul,0xEFBE4786ul,0x0FC19DC6ul,0x240CA1CCul,
    0x2DE92C6Ful,0x4A7484AAul,0x5CB0A9DCul,0x76F988DAul,
    0x983E5152ul,0xA831C66Dul,0xB00327C8ul,0xBF597FC7ul,
    0xC6E00BF3ul,0xD5A79147ul,0x06CA6351ul,0x14292967ul,
    0x27B70A85ul,0x2E1B2138ul,0x4D2C6DFCul,0x53380D13ul,
    0x650A7354ul,0x766A0ABBul,0x81C2C92Eul,0x92722C85ul,
    0xA2BFE8A1ul,0xA81A664Bul,0xC24B8B70ul,0xC76C51A3ul,
    0xD192E819ul,0xD6990624ul,0xF40E3585ul,0x106AA070ul,
    0x19A4C116ul,0x1E376C08ul,0x2748774Cul,0x34B0BCB5ul,
    0x391C0CB3ul,0x4ED8AA4Aul,0x5B9CCA4Ful,0x682E6FF3ul,
    0x748F82EEul,0x78A5636Ful,0x84C87814ul,0x8CC70208ul,
    0x90BEFFFAul,0xA4506CEBul,0xBEF9A3F7ul,0xC67178F2ul
};

static uint32_t rotate_right(uint32_t value, uint8_t count)
{
    return (value >> count) | (value << (32u - count));
}

static uint32_t read_be32(const uint8_t *data)
{
    return ((uint32_t)data[0] << 24) |
           ((uint32_t)data[1] << 16) |
           ((uint32_t)data[2] << 8) |
           (uint32_t)data[3];
}

static void transform(uint32_t state[8], const uint8_t block[64])
{
    uint32_t words[64];
    uint32_t a, b, c, d, e, f, g, h;
    uint32_t s0, s1, choice, majority, temp1, temp2;
    uint8_t index;

    for (index = 0u; index < 16u; ++index) {
        words[index] = read_be32(&block[4u * index]);
    }
    for (index = 16u; index < 64u; ++index) {
        s0 = rotate_right(words[index - 15u], 7u) ^
             rotate_right(words[index - 15u], 18u) ^
             (words[index - 15u] >> 3);
        s1 = rotate_right(words[index - 2u], 17u) ^
             rotate_right(words[index - 2u], 19u) ^
             (words[index - 2u] >> 10);
        words[index] = words[index - 16u] + s0 +
                       words[index - 7u] + s1;
    }

    a = state[0]; b = state[1]; c = state[2]; d = state[3];
    e = state[4]; f = state[5]; g = state[6]; h = state[7];
    for (index = 0u; index < 64u; ++index) {
        s1 = rotate_right(e, 6u) ^ rotate_right(e, 11u) ^
             rotate_right(e, 25u);
        choice = (e & f) ^ ((~e) & g);
        temp1 = h + s1 + choice + round_constants[index] + words[index];
        s0 = rotate_right(a, 2u) ^ rotate_right(a, 13u) ^
             rotate_right(a, 22u);
        majority = (a & b) ^ (a & c) ^ (b & c);
        temp2 = s0 + majority;
        h = g; g = f; f = e; e = d + temp1;
        d = c; c = b; b = a; a = temp1 + temp2;
    }
    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

void usac_sha256(const uint8_t *data, uint16_t length, uint8_t digest[32])
{
    uint32_t state[8] = {
        0x6A09E667ul,0xBB67AE85ul,0x3C6EF372ul,0xA54FF53Aul,
        0x510E527Ful,0x9B05688Cul,0x1F83D9ABul,0x5BE0CD19ul
    };
    uint8_t block[64];
    uint16_t offset = 0u;
    uint16_t remaining;
    uint32_t bit_length = (uint32_t)length * 8u;
    uint8_t index;

    while ((uint16_t)(length - offset) >= 64u) {
        transform(state, &data[offset]);
        offset = (uint16_t)(offset + 64u);
    }
    remaining = (uint16_t)(length - offset);
    for (index = 0u; index < 64u; ++index) {
        block[index] = 0u;
    }
    for (index = 0u; index < remaining; ++index) {
        block[index] = data[offset + index];
    }
    block[remaining] = 0x80u;
    if (remaining >= 56u) {
        transform(state, block);
        for (index = 0u; index < 64u; ++index) {
            block[index] = 0u;
        }
    }
    block[60] = (uint8_t)(bit_length >> 24);
    block[61] = (uint8_t)(bit_length >> 16);
    block[62] = (uint8_t)(bit_length >> 8);
    block[63] = (uint8_t)bit_length;
    transform(state, block);

    for (index = 0u; index < 8u; ++index) {
        digest[4u * index] = (uint8_t)(state[index] >> 24);
        digest[4u * index + 1u] = (uint8_t)(state[index] >> 16);
        digest[4u * index + 2u] = (uint8_t)(state[index] >> 8);
        digest[4u * index + 3u] = (uint8_t)state[index];
    }
}
