#include <stdint.h>
#include <msp430.h>

#include "usac_firmware_app.h"
#include "usac_capture_stream.h"

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

static uint8_t fake_capture_sync_timeout;
static uint8_t fake_capture_adc_dma_timeout;

static int establish_hello(
    usac_firmware_app_t *app,
    usac_mcu_frame_view_t *request,
    uint8_t response[128]);

static void write_u32_le(uint8_t *target, uint32_t value)
{
    target[0] = (uint8_t)value;
    target[1] = (uint8_t)(value >> 8);
    target[2] = (uint8_t)(value >> 16);
    target[3] = (uint8_t)(value >> 24);
}

static tuss4470_config_result_t fake_apply(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report)
{
    uint8_t *calls = (uint8_t *)context;
    (void)profile;
    ++(*calls);
    report->dev_stat = TUSS4470_DEV_STAT_VDRV_READY;
    return TUSS4470_CONFIG_OK;
}

static tuss4470_config_result_t fake_safe(void *context)
{
    uint8_t *calls = (uint8_t *)context;
    ++(*calls);
    return TUSS4470_CONFIG_OK;
}

static uint8_t fake_capture(
    void *context,
    const usac_config_v2_t *config,
    uint8_t trigger_source,
    uint32_t sync_timeout_ms,
    usac_capture_report_t *report)
{
    uint8_t *calls = (uint8_t *)context;
    (void)trigger_source;
    (void)sync_timeout_ms;
    ++(*calls);
    if (fake_capture_adc_dma_timeout != 0u) {
        report->captured_samples = 0u;
        report->dma_remaining = USAC_CAPTURE_SAMPLE_COUNT;
        report->diagnostic_flags = 0x0035u;
        report->diagnostic_timer_tick = 0x4567u;
        return 0u;
    }
    if ((trigger_source == 1u) && (fake_capture_sync_timeout != 0u)) {
        report->sync_timed_out = 1u;
        return 0u;
    }
    report->captured_samples = USAC_CAPTURE_SAMPLE_COUNT;
    report->trigger_sample_index = config->pretrigger_count;
    report->dma_remaining = 0u;
    report->burst_completed = 1u;
    report->tuss_dev_stat = TUSS4470_DEV_STAT_VDRV_READY;
    return 1u;
}

static int test_adc_dma_timeout_preserves_compact_hardware_snapshot(void)
{
    uint8_t device_id[16] = {12u};
    uint8_t boot_id[16] = {0u};
    uint8_t payload[60] = {0u};
    uint8_t response[128];
    uint8_t apply_calls = 0u;
    uint8_t capture_calls = 0u;
    uint8_t safe_calls = 0u;
    uint8_t index;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.apply_context = &apply_calls;
    app.apply_profile = fake_apply;
    app.capture_context = &capture_calls;
    app.capture = fake_capture;
    app.safety_context = &safe_calls;
    app.force_safe = fake_safe;
    CHECK(establish_hello(&app, &request, response) == 0);
    payload[0] = 0xE5u;
    for (index = 0u; index < 32u; ++index) {
        payload[16u + index] = app.config.profile_sha256[index];
    }
    write_u32_le(&payload[48], app.config.device_config_crc32);
    request.message_type = 0x05u;
    request.sequence = 9ul;
    request.payload_length = 60u;
    request.payload = payload;
    fake_capture_adc_dma_timeout = 1u;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    fake_capture_adc_dma_timeout = 0u;
    CHECK(response[5] == 0x7Fu && response[34] == 11u);
    /* ERROR detail0/detail1 retain the original low-16 values and place the
     * bounded snapshot in the high halves for offline root-cause analysis. */
    CHECK(response[36] == 0x00u && response[37] == 0x00u);
    CHECK(response[38] == 0x35u && response[39] == 0x00u);
    CHECK(response[40] == 0x00u && response[41] == 0x08u);
    CHECK(response[42] == 0x67u && response[43] == 0x45u);
    CHECK(apply_calls == 1u && capture_calls == 1u && safe_calls == 1u);
    return 0;
}

static int establish_hello(
    usac_firmware_app_t *app,
    usac_mcu_frame_view_t *request,
    uint8_t response[128])
{
    static uint8_t hello[20] = {1u};
    uint16_t response_length;

    hello[16] = 1u;
    hello[17] = 1u;
    request->message_type = 0x01u;
    request->flags = 0u;
    request->sequence = 1ul;
    request->payload_length = 20u;
    request->payload = hello;
    CHECK(usac_firmware_app_handle(
              app, request, response, 128u, &response_length) == 1u);
    CHECK(response[5] == 0x01u);
    return 0;
}

static void make_start_payload(
    const usac_firmware_app_t *app,
    uint8_t payload[80],
    uint32_t capture_count)
{
    uint8_t index;

    for (index = 0u; index < 80u; ++index) payload[index] = 0u;
    payload[0] = 0xA1u;
    payload[16] = 0xB2u;
    for (index = 0u; index < 32u; ++index) {
        payload[32u + index] = app->config.profile_sha256[index];
    }
    write_u32_le(&payload[64], app->config.device_config_crc32);
    write_u32_le(&payload[68], 100000ul);
    write_u32_le(&payload[72], capture_count);
    write_u32_le(&payload[76], 1000ul);
}

static int test_firmware_commands_drive_a_finite_schedule(void)
{
    uint8_t device_id[16] = {7u};
    uint8_t boot_id[16] = {0u};
    uint8_t start[80];
    uint8_t response[128];
    uint8_t apply_calls = 0u;
    uint8_t capture_calls = 0u;
    uint8_t safe_calls = 0u;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.apply_context = &apply_calls;
    app.apply_profile = fake_apply;
    app.capture_context = &capture_calls;
    app.capture = fake_capture;
    app.safety_context = &safe_calls;
    app.force_safe = fake_safe;
    CHECK(establish_hello(&app, &request, response) == 0);

    request.message_type = 0x02u;
    request.sequence = 2ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x02u && response[12] == 24u);
    CHECK(response[16] == 0x7Fu && response[33] == 1u);
    CHECK(response[34] == 16u && response[36] == 0x0Fu);

    make_start_payload(&app, start, 1ul);
    request.message_type = 0x06u;
    request.sequence = 3ul;
    request.payload_length = 80u;
    request.payload = start;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Eu && app.periodic.active == 1u);
    usac_firmware_app_advance_time(&app, 100000ul);
    CHECK(usac_firmware_app_periodic_due(&app) == 1u);
    CHECK(usac_firmware_app_run_periodic_capture(&app) == 1u);
    CHECK(app.capture_pending == 1u && app.capture_is_async == 1u);
    CHECK(app.capture_schedule_id[0] == 0xB2u);
    CHECK(app.periodic.active == 0u);
    CHECK(apply_calls == 1u && capture_calls == 1u && safe_calls == 1u);
    return 0;
}

static int test_firmware_lease_expiry_forces_safe_and_status_reports_error(void)
{
    uint8_t device_id[16] = {8u};
    uint8_t boot_id[16] = {0u};
    uint8_t start[80];
    uint8_t response[128];
    uint8_t safe_calls = 0u;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.safety_context = &safe_calls;
    app.force_safe = fake_safe;
    CHECK(establish_hello(&app, &request, response) == 0);
    make_start_payload(&app, start, 0ul);
    request.message_type = 0x06u;
    request.sequence = 4ul;
    request.payload_length = 80u;
    request.payload = start;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    usac_firmware_app_advance_time(&app, 1000000ul);
    CHECK(app.periodic.active == 0u && safe_calls == 1u);

    request.message_type = 0x08u;
    request.sequence = 5ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x08u && response[12] == 100u);
    CHECK(response[34] == 18u && response[35] == 0u);
    return 0;
}

static int test_set_config_status_reports_latest_tuss_dev_stat(void)
{
    uint8_t device_id[16] = {11u};
    uint8_t boot_id[16] = {0u};
    uint8_t payload[120] = {0u};
    uint8_t response[128];
    uint8_t apply_calls = 0u;
    uint8_t index;
    uint16_t config_length;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.apply_context = &apply_calls;
    app.apply_profile = fake_apply;
    CHECK(establish_hello(&app, &request, response) == 0);
    payload[0] = 0xD4u;
    for (index = 0u; index < 32u; ++index) {
        payload[16u + index] = app.config.profile_sha256[index];
    }
    CHECK(usac_config_v2_encode(
              &app.config, &payload[48], 72u, &config_length) ==
          USAC_CONFIG_V2_OK);
    request.message_type = 0x04u;
    request.sequence = 2ul;
    request.payload_length = 120u;
    request.payload = payload;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x7Eu && apply_calls == 1u);

    request.message_type = 0x08u;
    request.sequence = 3ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x08u && response[84] == TUSS4470_DEV_STAT_VDRV_READY);
    CHECK(response[85] == 1u);
    return 0;
}

static int test_boot_config_status_is_visible_through_get_status(void)
{
    uint8_t device_id[16] = {13u};
    uint8_t boot_id[16] = {0u};
    uint8_t response[128];
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_SESSION_WAIT);
    usac_firmware_app_record_boot_config(
        &app, TUSS4470_CONFIG_OK, TUSS4470_DEV_STAT_VDRV_READY);
    CHECK(establish_hello(&app, &request, response) == 0);

    request.message_type = 0x08u;
    request.sequence = 2ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[5] == 0x08u);
    CHECK(response[34] == 0u && response[35] == 0u);
    CHECK(response[84] == TUSS4470_DEV_STAT_VDRV_READY);
    CHECK(response[85] == 1u);
    return 0;
}

static int test_boot_vdrv_timeout_is_visible_through_get_status(void)
{
    uint8_t device_id[16] = {14u};
    uint8_t boot_id[16] = {0u};
    uint8_t response[128];
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_FAULT);
    usac_firmware_app_record_boot_config(
        &app, TUSS4470_CONFIG_VDRV_TIMEOUT, 0u);
    CHECK(establish_hello(&app, &request, response) == 0);

    request.message_type = 0x08u;
    request.sequence = 2ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[34] == 9u && response[35] == 0u);
    CHECK(response[84] == 0u && response[85] == 0u);
    return 0;
}

static int test_firmware_capture_stream_encodes_one_hardware_event(void)
{
    usac_config_v2_t config;
    usac_capture_descriptor_t descriptor = {0u};
    usac_capture_stream_t stream;
    uint8_t index;

    usac_config_v2_init_d10x4(&config);
    descriptor.pretrigger_count = 64u;
    descriptor.sample_interval_ticks = 120u;
    descriptor.burst_period_ticks = 50u;
    descriptor.out3_start_level = 0u;
    descriptor.out4_start_level = 0xFFu;
    descriptor.event_count = 1u;
    descriptor.quality_flags = USAC_QUALITY_TIMING_UNCALIBRATED;
    descriptor.events[0].channel = 3u;
    descriptor.events[0].edge = 1u;
    descriptor.events[0].capture_method = 2u;
    descriptor.events[0].level_after = 1u;
    descriptor.events[0].sample_index = 2;
    descriptor.events[0].subsample_tick = 10u;
    descriptor.events[0].uncertainty_ticks = 1u;
    descriptor.events[0].frame_offset_ticks = 250u;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        descriptor.register_pairs[index] = config.profile.registers[index];
    }
    usac_capture_stream_init(&stream, &descriptor, g_usac_capture_waveform);
    CHECK(stream.metadata_length == 224u);
    CHECK(stream.frame_header[12] == 0xE0u && stream.frame_header[13] == 0x10u);
    CHECK(stream.metadata[177] == 0u);
    CHECK(stream.metadata[178] == 0xFFu);
    CHECK(stream.metadata[179] == 1u);
    CHECK(stream.metadata[208] == 3u && stream.metadata[209] == 1u);
    CHECK(stream.metadata[210] == 2u && stream.metadata[211] == 1u);
    CHECK(stream.metadata[216] == 10u && stream.metadata[217] == 0u);
    return 0;
}

static int test_slave_sync_timeout_is_reported_without_retry(void)
{
    uint8_t device_id[16] = {9u};
    uint8_t boot_id[16] = {0u};
    uint8_t payload[60] = {0u};
    uint8_t response[128];
    uint8_t apply_calls = 0u;
    uint8_t capture_calls = 0u;
    uint8_t safe_calls = 0u;
    uint8_t index;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.apply_context = &apply_calls;
    app.apply_profile = fake_apply;
    app.capture_context = &capture_calls;
    app.capture = fake_capture;
    app.safety_context = &safe_calls;
    app.force_safe = fake_safe;
    CHECK(establish_hello(&app, &request, response) == 0);
    payload[0] = 0xC3u;
    for (index = 0u; index < 32u; ++index) {
        payload[16u + index] = app.config.profile_sha256[index];
    }
    write_u32_le(&payload[48], app.config.device_config_crc32);
    payload[52] = 1u;
    write_u32_le(&payload[56], 500ul);
    request.message_type = 0x05u;
    request.sequence = 6ul;
    request.payload_length = 60u;
    request.payload = payload;
    fake_capture_sync_timeout = 1u;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    fake_capture_sync_timeout = 0u;
    CHECK(response[5] == 0x7Fu && response[34] == 26u);
    CHECK(apply_calls == 1u && capture_calls == 1u && safe_calls == 1u);
    CHECK(app.capture_pending == 0u);
    return 0;
}

static int test_runtime_clock_fault_stops_schedule_and_is_reported(void)
{
    uint8_t device_id[16] = {10u};
    uint8_t boot_id[16] = {0u};
    uint8_t start[80];
    uint8_t response[128];
    uint8_t safe_calls = 0u;
    uint16_t response_length;
    usac_mcu_frame_view_t request;
    usac_firmware_app_t app;

    usac_firmware_app_init(&app, device_id, boot_id, 0u, USAC_FIRMWARE_IDLE_SAFE);
    app.safety_context = &safe_calls;
    app.force_safe = fake_safe;
    CHECK(establish_hello(&app, &request, response) == 0);
    make_start_payload(&app, start, 0ul);
    request.message_type = 0x06u;
    request.sequence = 7ul;
    request.payload_length = 80u;
    request.payload = start;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(app.periodic.active == 1u);

    usac_firmware_app_update_clock_faults(&app, 0x0004u);
    CHECK(app.periodic.active == 0u && safe_calls == 1u);
    CHECK(app.clock_fault_flags == 0x0004u && app.last_error == 16u);
    usac_firmware_app_update_clock_faults(&app, 0x0008u);
    CHECK(safe_calls == 1u && app.clock_fault_flags == 0x0004u);

    request.message_type = 0x08u;
    request.sequence = 8ul;
    request.payload_length = 0u;
    request.payload = 0;
    CHECK(usac_firmware_app_handle(
              &app, &request, response, sizeof(response), &response_length) == 1u);
    CHECK(response[34] == 16u && response[88] == 4u && response[89] == 0u);
    return 0;
}

volatile int g_usac_test_result = -1;
void __attribute__((noinline)) usac_test_complete(void)
{
    __no_operation();
    for (;;) {
    }
}

int main(void)
{
    int result = test_firmware_commands_drive_a_finite_schedule();
    if (result == 0) {
        result = test_firmware_lease_expiry_forces_safe_and_status_reports_error();
    }
    if (result == 0) {
        result = test_set_config_status_reports_latest_tuss_dev_stat();
    }
    if (result == 0) {
        result = test_boot_config_status_is_visible_through_get_status();
    }
    if (result == 0) {
        result = test_boot_vdrv_timeout_is_visible_through_get_status();
    }
    if (result == 0) {
        result = test_firmware_capture_stream_encodes_one_hardware_event();
    }
    if (result == 0) {
        result = test_slave_sync_timeout_is_reported_without_retry();
    }
    if (result == 0) {
        result = test_runtime_clock_fault_stops_schedule_and_is_reported();
    }
    if (result == 0) {
        result = test_adc_dma_timeout_preserves_compact_hardware_snapshot();
    }
    g_usac_test_result = result;
    usac_test_complete();
    return 0;
}
