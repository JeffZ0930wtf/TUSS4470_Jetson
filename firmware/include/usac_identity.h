#ifndef USAC_IDENTITY_H
#define USAC_IDENTITY_H

#include <stdint.h>

#define USAC_DIE_RECORD_LENGTH 10u
#define USAC_DEVICE_ID_LENGTH 16u
#define USAC_BOOT_ID_LENGTH 16u
#define USAC_HOST_NONCE_LENGTH 16u
#define USAC_USB_SERIAL_DESCRIPTOR_LENGTH 66u

void usac_identity_derive(
    const uint8_t die_record[USAC_DIE_RECORD_LENGTH],
    uint8_t device_id[USAC_DEVICE_ID_LENGTH]);
uint8_t usac_identity_die_record_valid(
    const uint8_t die_record[USAC_DIE_RECORD_LENGTH]);
void usac_identity_usb_serial_descriptor(
    const uint8_t device_id[USAC_DEVICE_ID_LENGTH],
    uint8_t descriptor[USAC_USB_SERIAL_DESCRIPTOR_LENGTH]);
void usac_boot_id_derive(
    const uint8_t device_id[USAC_DEVICE_ID_LENGTH],
    const uint8_t host_nonce[USAC_HOST_NONCE_LENGTH],
    uint8_t boot_id[USAC_BOOT_ID_LENGTH]);

#endif
