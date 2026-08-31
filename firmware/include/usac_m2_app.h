/* M2 application state and command dispatcher. Hardware actions are injected
 * as callbacks so simulator tests can verify state transitions and failure
 * closure without accessing the real board. */
#ifndef USAC_M2_APP_H
#define USAC_M2_APP_H

#include <stdint.h>

#include "tuss4470_configurator.h"
#include "usac_config_v2.h"
#include "usac_m2_core.h"
#include "usac_m3_loopback.h"
#include "usac_m3_capture.h"
#include "usac_mcu_protocol.h"

typedef tuss4470_config_result_t (*usac_apply_profile_fn)(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report);
typedef tuss4470_config_result_t (*usac_force_safe_fn)(void *context);
typedef uint8_t (*usac_run_io2_loopback_fn)(
    void *context,
    uint16_t burst_period_ticks,
    usac_m3_loopback_report_t *report);
typedef uint8_t (*usac_capture_once_fn)(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report);

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
    uint8_t loopback_cache_valid;
    uint8_t loopback_cache_request_id[16];
    uint32_t loopback_cache_sequence;
    uint32_t loopback_cache_payload_crc32;
    uint16_t loopback_cache_response_length;
    uint8_t loopback_cache_response[128];
    uint8_t loopback_authorized;
    uint8_t capture_pending;
    uint8_t capture_request_id[16];
    uint32_t capture_request_sequence;
    uint32_t capture_sequence;
    usac_m3_capture_report_t capture_report;
    uint8_t capture_cache_valid;
    uint8_t capture_cache_request_id[16];
    uint32_t capture_cache_request_sequence;
    uint32_t capture_cache_payload_crc32;
    uint16_t capture_cache_ack_length;
    uint8_t capture_cache_ack[44];
    void *apply_context;
    usac_apply_profile_fn apply_profile;
    void *safety_context;
    usac_force_safe_fn force_safe;
    void *loopback_context;
    usac_run_io2_loopback_fn run_io2_loopback;
    void *capture_context;
    usac_capture_once_fn capture_once;
} usac_m2_app_t;

void usac_m2_app_init(
    usac_m2_app_t *app,
    const uint8_t device_id[16],
    const uint8_t boot_id[16],
    uint8_t reset_reason,
    usac_m2_state_t initial_state);
/* Ends host ownership and forces safe hardware before clearing session state. */
void usac_m2_app_end_session(usac_m2_app_t *app);
/* Encodes one response into caller storage; returns false if it cannot do so. */
uint8_t usac_m2_app_handle(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t response_capacity,
    uint16_t *response_length);

#endif
