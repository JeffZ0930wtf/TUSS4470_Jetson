#include "usac_identity.h"

#include "usac_sha256.h"

uint8_t usac_identity_die_record_valid(
    const uint8_t die_record[USAC_DIE_RECORD_LENGTH])
{
    uint8_t any_nonzero = 0u;
    uint8_t any_non_ff = 0u;
    uint8_t index;

    if (die_record == 0) {
        return 0u;
    }
    for (index = 0u; index < USAC_DIE_RECORD_LENGTH; ++index) {
        any_nonzero |= die_record[index];
        any_non_ff |= (uint8_t)(die_record[index] ^ 0xFFu);
    }
    return (uint8_t)((any_nonzero != 0u) && (any_non_ff != 0u));
}

void usac_identity_derive(
    const uint8_t die_record[USAC_DIE_RECORD_LENGTH],
    uint8_t device_id[USAC_DEVICE_ID_LENGTH])
{
    static const uint8_t domain[17] = {
        'U','S','A','C','-','D','E','V','I','C','E','-','I','D','-','V','1'
    };
    uint8_t input[27];
    uint8_t digest[32];
    uint8_t index;

    for (index = 0u; index < 17u; ++index) {
        input[index] = domain[index];
    }
    for (index = 0u; index < USAC_DIE_RECORD_LENGTH; ++index) {
        input[17u + index] = die_record[index];
    }
    usac_sha256(input, (uint16_t)sizeof(input), digest);
    for (index = 0u; index < USAC_DEVICE_ID_LENGTH; ++index) {
        device_id[index] = digest[index];
    }
}

void usac_identity_usb_serial_descriptor(
    const uint8_t device_id[USAC_DEVICE_ID_LENGTH],
    uint8_t descriptor[USAC_USB_SERIAL_DESCRIPTOR_LENGTH])
{
    static const uint8_t hex[] = "0123456789abcdef";
    uint8_t index;

    descriptor[0] = USAC_USB_SERIAL_DESCRIPTOR_LENGTH;
    descriptor[1] = 3u;
    for (index = 0u; index < USAC_DEVICE_ID_LENGTH; ++index) {
        descriptor[2u + 4u * index] = hex[device_id[index] >> 4];
        descriptor[3u + 4u * index] = 0u;
        descriptor[4u + 4u * index] = hex[device_id[index] & 0x0Fu];
        descriptor[5u + 4u * index] = 0u;
    }
}

void usac_boot_id_derive(
    const uint8_t device_id[USAC_DEVICE_ID_LENGTH],
    const uint8_t host_nonce[USAC_HOST_NONCE_LENGTH],
    uint8_t boot_id[USAC_BOOT_ID_LENGTH])
{
    static const uint8_t domain[15] = {
        'U','S','A','C','-','B','O','O','T','-','I','D','-','V','1'
    };
    uint8_t input[47];
    uint8_t digest[32];
    uint8_t index;

    for (index = 0u; index < 15u; ++index) {
        input[index] = domain[index];
    }
    for (index = 0u; index < USAC_DEVICE_ID_LENGTH; ++index) {
        input[15u + index] = device_id[index];
    }
    for (index = 0u; index < USAC_HOST_NONCE_LENGTH; ++index) {
        input[31u + index] = host_nonce[index];
    }
    usac_sha256(input, (uint16_t)sizeof(input), digest);
    for (index = 0u; index < USAC_BOOT_ID_LENGTH; ++index) {
        boot_id[index] = digest[index];
    }
}
