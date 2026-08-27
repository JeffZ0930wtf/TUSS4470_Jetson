#ifndef USAC_M2_APP_H
#define USAC_M2_APP_H

#include <stdint.h>

#include "tuss4470_configurator.h"
#include "usac_config_v2.h"
#include "usac_m2_core.h"
#include "usac_mcu_protocol.h"

typedef tuss4470_config_result_t (*usac_apply_profile_fn)(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report);
typedef tuss4470_config_result_t (*usac_force_safe_fn)(void *context);

typedef struct {
    usac_m2_core_t core;
    usac_config_v2_t config;
    uint8_t device_id[16];
    uint8_t boot_id[16];
    uint8_t host_nonce[16];
    uint8_t reset_reason;
    uint8_t hello_established;
    uint8_t config_valid;
    uint8_t profile_active;
    uint8_t set_cache_valid;
    uint8_t set_cache_request_id[16];
    uint32_t set_cache_sequence;
    uint32_t set_cache_payload_crc32;
    uint16_t set_cache_response_length;
    uint8_t set_cache_response[64];
    void *apply_context;
    usac_apply_profile_fn apply_profile;
    void *safety_context;
    usac_force_safe_fn force_safe;
} usac_m2_app_t;

void usac_m2_app_init(
    usac_m2_app_t *app,
    const uint8_t device_id[16],
    const uint8_t boot_id[16],
    uint8_t reset_reason,
    usac_m2_state_t initial_state);
void usac_m2_app_end_session(usac_m2_app_t *app);
uint8_t usac_m2_app_handle(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t response_capacity,
    uint16_t *response_length);

#endif
