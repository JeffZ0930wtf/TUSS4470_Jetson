/* Implements M2 request semantics above the bounded byte parser. It owns
 * HELLO/configuration state, duplicate SET_CONFIG responses, and safe session
 * shutdown. CAPTURE_ONCE is intentionally rejected in every M2 state. */
#include "usac_m2_app.h"

#include "usac_identity.h"

#define USAC_FLAG_RESPONSE 0x0001u
#define USAC_MESSAGE_HELLO 0x01u
#define USAC_MESSAGE_GET_CONFIG 0x03u
#define USAC_MESSAGE_SET_CONFIG 0x04u
#define USAC_MESSAGE_CAPTURE_ONCE 0x05u
#define USAC_MESSAGE_ACK 0x7Eu
#define USAC_MESSAGE_ERROR 0x7Fu

#define USAC_ERROR_INVALID_MESSAGE 1u
#define USAC_ERROR_UNSUPPORTED_TYPE 4u
#define USAC_ERROR_INVALID_STATE 5u
#define USAC_ERROR_CONFIG_MISMATCH 6u
#define USAC_ERROR_VDRV_NOT_READY 9u
#define USAC_ERROR_TUSS_DRIVER_FAULT 10u
#define USAC_ERROR_INTERNAL 15u
#define USAC_ERROR_UNSAFE_CONFIG 25u
#define USAC_ERROR_UNSUPPORTED_HARDWARE 27u

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

static void copy_bytes(uint8_t *target, const uint8_t *source, uint8_t length)
{
    uint8_t index;
    for (index = 0u; index < length; ++index) {
        target[index] = source[index];
    }
}

static uint8_t bytes_equal(
    const uint8_t *left,
    const uint8_t *right,
    uint8_t length)
{
    uint8_t difference = 0u;
    uint8_t index;

    for (index = 0u; index < length; ++index) {
        difference |= (uint8_t)(left[index] ^ right[index]);
    }
    return (uint8_t)(difference == 0u);
}

static uint8_t encode_error(
    const usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint16_t error_code,
    uint32_t detail0,
    uint32_t detail1,
    uint8_t *response,
    uint16_t capacity,
    uint16_t *response_length)
{
    uint8_t payload[29];
    uint8_t index;

    for (index = 0u; index < 16u; ++index) {
        payload[index] = (request->payload_length >= 16u) ?
            request->payload[index] : 0u;
    }
    payload[16] = request->message_type;
    payload[17] = (uint8_t)app->core.state;
    write_u16_le(&payload[18], error_code);
    write_u32_le(&payload[20], detail0);
    write_u32_le(&payload[24], detail1);
    payload[28] = 0u;
    return usac_mcu_encode_frame(
        USAC_MESSAGE_ERROR,
        USAC_FLAG_RESPONSE,
        request->sequence,
        payload,
        (uint16_t)sizeof(payload),
        response,
        capacity,
        response_length);
}

static uint8_t handle_hello(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t capacity,
    uint16_t *response_length)
{
    uint8_t payload[64] = {0u};
    uint8_t nonce_changed = 0u;
    uint8_t index;

    if (app->hello_established != 0u) {
        for (index = 0u; index < 16u; ++index) {
            nonce_changed |= (uint8_t)(
                app->host_nonce[index] ^ request->payload[index]);
        }
        if (nonce_changed != 0u) {
            usac_m2_app_end_session(app);
        }
    }

    usac_boot_id_derive(app->device_id, request->payload, app->boot_id);
    copy_bytes(app->host_nonce, request->payload, 16u);
    app->hello_established = 1u;
    if (app->core.state == USAC_M2_SESSION_WAIT) {
        app->core.state = USAC_M2_IDLE_SAFE;
    }
    copy_bytes(&payload[0], request->payload, 16u);
    copy_bytes(&payload[16], app->boot_id, 16u);
    copy_bytes(&payload[32], app->device_id, 16u);
    payload[48] = 1u;
    payload[49] = app->reset_reason;
    write_u16_le(&payload[50], 0u);
    write_u16_le(&payload[52], 2u);
    write_u16_le(&payload[54], 0u);
    write_u32_le(&payload[56], 2u);
    payload[60] = (uint8_t)app->core.state;
    return usac_mcu_encode_frame(
        USAC_MESSAGE_HELLO,
        USAC_FLAG_RESPONSE,
        request->sequence,
        payload,
        (uint16_t)sizeof(payload),
        response,
        capacity,
        response_length);
}

static uint8_t handle_get_config(
    const usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t capacity,
    uint16_t *response_length)
{
    uint8_t payload[USAC_CONFIG_V2_WIRE_LENGTH];
    uint16_t payload_length;

    if (app->config_valid == 0u) {
        return encode_error(
            app, request, USAC_ERROR_INVALID_STATE, 0u, 0u,
            response, capacity, response_length);
    }
    if (usac_config_v2_encode(
            &app->config,
            payload,
            (uint16_t)sizeof(payload),
            &payload_length) != USAC_CONFIG_V2_OK) {
        return encode_error(
            app, request, USAC_ERROR_INTERNAL, 0u, 0u,
            response, capacity, response_length);
    }
    return usac_mcu_encode_frame(
        USAC_MESSAGE_GET_CONFIG,
        USAC_FLAG_RESPONSE,
        request->sequence,
        payload,
        payload_length,
        response,
        capacity,
        response_length);
}

static uint16_t map_config_error(tuss4470_config_result_t result)
{
    if (result == TUSS4470_CONFIG_VDRV_TIMEOUT) {
        return USAC_ERROR_VDRV_NOT_READY;
    }
    if ((result == TUSS4470_CONFIG_DRIVER_FAULT) ||
        (result == TUSS4470_CONFIG_READBACK) ||
        (result == TUSS4470_CONFIG_BUS)) {
        return USAC_ERROR_TUSS_DRIVER_FAULT;
    }
    if (result == TUSS4470_CONFIG_IDENTITY) {
        return USAC_ERROR_UNSUPPORTED_HARDWARE;
    }
    return USAC_ERROR_UNSAFE_CONFIG;
}

static uint8_t execute_set_config(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t capacity,
    uint16_t *response_length)
{
    usac_config_v2_t candidate;
    tuss4470_config_report_t report = {0u, 0u, 0u};
    tuss4470_config_result_t apply_result;
    uint8_t ack[24] = {0u};
    uint8_t index;

    for (index = 0u; index < 32u; ++index) {
        uint8_t expected = request->payload[16u + index];
        uint8_t mismatch = (app->config_valid != 0u) ?
            (uint8_t)(expected != app->config.profile_sha256[index]) :
            (uint8_t)(expected != 0u);
        if (mismatch != 0u) {
            return encode_error(
                app, request, USAC_ERROR_CONFIG_MISMATCH, index, 0u,
                response, capacity, response_length);
        }
    }
    if (usac_config_v2_decode(
            &request->payload[48],
            USAC_CONFIG_V2_WIRE_LENGTH,
            &candidate) != USAC_CONFIG_V2_OK) {
        return encode_error(
            app, request, USAC_ERROR_UNSAFE_CONFIG, 0u, 0u,
            response, capacity, response_length);
    }
    if (app->apply_profile == 0) {
        return encode_error(
            app, request, USAC_ERROR_INTERNAL, 0u, 0u,
            response, capacity, response_length);
    }

    app->core.state = USAC_M2_CONFIGURING;
    apply_result = app->apply_profile(
        app->apply_context, &candidate.profile, &report);
    if (apply_result != TUSS4470_CONFIG_OK) {
        app->config_valid = 0u;
        app->profile_active = 0u;
        app->core.state = USAC_M2_FAULT;
        return encode_error(
            app, request, map_config_error(apply_result), report.dev_stat, 0u,
            response, capacity, response_length);
    }
    app->config = candidate;
    app->config_valid = 1u;
    app->profile_active = 1u;
    app->core.state = USAC_M2_IDLE_SAFE;
    copy_bytes(&ack[0], request->payload, 16u);
    ack[16] = USAC_MESSAGE_SET_CONFIG;
    ack[17] = (uint8_t)app->core.state;
    write_u16_le(&ack[18], 0u);
    write_u32_le(&ack[20], app->config.device_config_crc32);
    return usac_mcu_encode_frame(
        USAC_MESSAGE_ACK,
        USAC_FLAG_RESPONSE,
        request->sequence,
        ack,
        (uint16_t)sizeof(ack),
        response,
        capacity,
        response_length);
}

static uint8_t handle_set_config(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t capacity,
    uint16_t *response_length)
{
    uint32_t payload_crc = usac_mcu_crc32(
        request->payload, request->payload_length);
    uint8_t request_id_matches = 0u;
    uint8_t result;
    uint16_t index;

    if (app->set_cache_valid != 0u) {
        request_id_matches = bytes_equal(
            request->payload, app->set_cache_request_id, 16u);
        if ((request_id_matches != 0u) &&
            (request->sequence == app->set_cache_sequence) &&
            (payload_crc == app->set_cache_payload_crc32)) {
            if (capacity < app->set_cache_response_length) {
                return 0u;
            }
            for (index = 0u; index < app->set_cache_response_length; ++index) {
                response[index] = app->set_cache_response[index];
            }
            *response_length = app->set_cache_response_length;
            return 1u;
        }
        if (request_id_matches != 0u) {
            return encode_error(
                app, request, USAC_ERROR_INVALID_MESSAGE,
                app->set_cache_sequence, request->sequence,
                response, capacity, response_length);
        }
    }

    result = execute_set_config(
        app, request, response, capacity, response_length);
    if ((result == 0u) ||
        (*response_length > (uint16_t)sizeof(app->set_cache_response))) {
        return result;
    }
    copy_bytes(app->set_cache_request_id, request->payload, 16u);
    app->set_cache_sequence = request->sequence;
    app->set_cache_payload_crc32 = payload_crc;
    app->set_cache_response_length = *response_length;
    for (index = 0u; index < *response_length; ++index) {
        app->set_cache_response[index] = response[index];
    }
    app->set_cache_valid = 1u;
    return result;
}

void usac_m2_app_init(
    usac_m2_app_t *app,
    const uint8_t device_id[16],
    const uint8_t boot_id[16],
    uint8_t reset_reason,
    usac_m2_state_t initial_state)
{
    uint8_t index;

    usac_m2_core_reset(&app->core);
    app->core.state = initial_state;
    usac_config_v2_init_d10x4(&app->config);
    copy_bytes(app->device_id, device_id, 16u);
    copy_bytes(app->boot_id, boot_id, 16u);
    for (index = 0u; index < 16u; ++index) {
        app->host_nonce[index] = 0u;
    }
    app->reset_reason = reset_reason;
    app->hello_established = 0u;
    app->config_valid = (uint8_t)(
        (initial_state == USAC_M2_SESSION_WAIT) ||
        (initial_state == USAC_M2_IDLE_SAFE));
    app->profile_active = app->config_valid;
    app->set_cache_valid = 0u;
    app->set_cache_sequence = 0u;
    app->set_cache_payload_crc32 = 0u;
    app->set_cache_response_length = 0u;
    app->apply_context = 0;
    app->apply_profile = 0;
    app->safety_context = 0;
    app->force_safe = 0;
}

void usac_m2_app_end_session(usac_m2_app_t *app)
{
    uint8_t index;

    app->hello_established = 0u;
    app->set_cache_valid = 0u;
    app->profile_active = 0u;
    if ((app->force_safe != 0) &&
        (app->force_safe(app->safety_context) != TUSS4470_CONFIG_OK)) {
        app->config_valid = 0u;
        app->core.state = USAC_M2_FAULT;
    }
    for (index = 0u; index < 16u; ++index) {
        app->boot_id[index] = 0u;
        app->host_nonce[index] = 0u;
    }
    if (app->core.state != USAC_M2_FAULT) {
        app->core.state = USAC_M2_SESSION_WAIT;
    }
}

uint8_t usac_m2_app_handle(
    usac_m2_app_t *app,
    const usac_mcu_frame_view_t *request,
    uint8_t *response,
    uint16_t response_capacity,
    uint16_t *response_length)
{
    if (request->flags != 0u) {
        return encode_error(
            app, request, USAC_ERROR_INVALID_MESSAGE, request->flags, 0u,
            response, response_capacity, response_length);
    }
    if (request->message_type == USAC_MESSAGE_HELLO) {
        return handle_hello(
            app, request, response, response_capacity, response_length);
    }
    if (app->hello_established == 0u) {
        return encode_error(
            app, request, USAC_ERROR_INVALID_STATE, 0u, 0u,
            response, response_capacity, response_length);
    }
    if (request->message_type == USAC_MESSAGE_GET_CONFIG) {
        return handle_get_config(
            app, request, response, response_capacity, response_length);
    }
    if (request->message_type == USAC_MESSAGE_SET_CONFIG) {
        return handle_set_config(
            app, request, response, response_capacity, response_length);
    }
    if (request->message_type == USAC_MESSAGE_CAPTURE_ONCE) {
        return encode_error(
            app, request, USAC_ERROR_INVALID_STATE, 2u, 0u,
            response, response_capacity, response_length);
    }
    return encode_error(
        app, request, USAC_ERROR_UNSUPPORTED_TYPE, 0u, 0u,
        response, response_capacity, response_length);
}
