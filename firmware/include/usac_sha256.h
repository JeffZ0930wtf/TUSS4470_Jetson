/* Allocation-free one-shot SHA-256 used for bounded identity/config material. */
#ifndef USAC_SHA256_H
#define USAC_SHA256_H

#include <stdint.h>

void usac_sha256(const uint8_t *data, uint16_t length, uint8_t digest[32]);

#endif
