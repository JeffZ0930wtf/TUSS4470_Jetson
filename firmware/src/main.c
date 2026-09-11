/* firmware hardware entry point. It owns reset-safe ordering, the TI USB CDC stack,
 * clock bring-up, bounded command processing, and TUSS4470 configuration.
 * This image deliberately contains no acquisition or Burst execution path. */
#include <msp430.h>
#include <stdint.h>

#include "driverlib.h"
#include "USB_config/descriptors.h"
#include "USB_API/USB_Common/device.h"
#include "USB_API/USB_Common/usb.h"
#include "USB_API/USB_CDC_API/UsbCdc.h"
#include "USB_app/usbConstructs.h"

#include "tuss4470_configurator.h"
#include "tuss4470_profile.h"
#include "usac_identity.h"
#include "usac_firmware_app.h"
#include "usac_firmware_core.h"
#include "usac_capture_schedule.h"
#include "usac_capture_stream.h"
#include "usac_capture_tx.h"
#include "usac_mcu_protocol.h"
#include "usac_platform_msp430.h"
#ifdef USAC_ENABLE_LOOPBACK
#include "usac_acquisition_platform_msp430.h"
#endif
#include "usac_tx_gate.h"

#define USAC_USB_DETACH_CYCLES 14400000ul
#define USAC_VDRV_READY_POLL_LIMIT 70u
#define USAC_CDC_BUFFER_SIZE 1u

extern volatile uint8_t g_usac_usb_data_pending;
extern volatile uint8_t g_usac_usb_send_complete;
extern volatile uint8_t g_usac_dtr_present;
extern volatile uint8_t g_usac_dtr_session_ready;
extern uint8_t abramSerialStringDescriptor[USAC_USB_SERIAL_DESCRIPTOR_LENGTH];

volatile uint8_t g_usac_tuss_config_result;
volatile uint8_t g_usac_tuss_device_id;
volatile uint8_t g_usac_tuss_revision_id;
volatile uint8_t g_usac_tuss_dev_stat;
volatile uint8_t g_usac_last_parse_result;
volatile uint8_t g_usac_last_message_type;
volatile uint8_t g_usac_last_send_result;
volatile uint8_t g_usac_frame_timeout_pending;
volatile uint8_t g_usac_clock_valid;
volatile uint8_t g_usac_clock_stage;
volatile uint8_t g_usac_xt2_start_result;
#ifdef USAC_ENABLE_ACQUISITION
volatile uint8_t g_usac_xt1_start_result;
#endif
volatile uint8_t g_usac_clock_ucsctl7;
volatile uint8_t g_usac_clock_sfrifg1;
volatile uint8_t g_usac_force_safe_result;
#ifdef USAC_ENABLE_ACQUISITION
static volatile uint16_t g_usac_elapsed_quanta;
#endif

static uint8_t device_id[USAC_DEVICE_ID_LENGTH];
static uint8_t response_buffer[128];
static usac_mcu_parser_t parser;
static usac_firmware_app_t app;
static tuss4470_bus_t tuss_bus;
static usac_tx_gate_t tx_gate;
#ifdef USAC_ENABLE_LOOPBACK
static usac_capture_stream_t capture_stream;
static usac_capture_tx_t capture_tx;
static uint8_t capture_stream_started;
#endif

static void abort_usb_response(void)
{
    uint16_t bytes_sent = 0u;

    if (usac_tx_gate_can_encode(&tx_gate) == 0u) {
        (void)USBCDC_abortSend(&bytes_sent, CDC0_INTFNUM);
    }
    usac_tx_gate_reset(&tx_gate);
    g_usac_usb_send_complete = 0u;
#ifdef USAC_ENABLE_LOOPBACK
    if (capture_stream_started != 0u) {
        usac_capture_tx_abort(&capture_tx);
    }
    capture_stream_started = 0u;
#endif
}

#ifdef USAC_ENABLE_LOOPBACK
static void initialize_pending_capture_stream(void)
{
    usac_capture_descriptor_t descriptor;
    uint8_t index;

    for (index = 0u; index < 16u; ++index) {
        descriptor.request_id[index] = app.capture_request_id[index];
        descriptor.schedule_id[index] = app.capture_schedule_id[index];
        descriptor.boot_id[index] = app.boot_id[index];
        descriptor.device_id[index] = app.device_id[index];
    }
    for (index = 0u; index < 32u; ++index) {
        descriptor.profile_sha256[index] = app.config.profile_sha256[index];
    }
    descriptor.device_config_crc32 = app.config.device_config_crc32;
    descriptor.frame_sequence = app.capture_request_sequence;
    descriptor.capture_sequence = app.capture_sequence;
    descriptor.async_capture = app.capture_is_async;
    descriptor.sample_interval_ticks = app.config.profile.sample_interval_ticks;
    descriptor.burst_period_ticks = app.config.profile.burst_period_ticks;
    descriptor.pretrigger_count = app.config.pretrigger_count;
    descriptor.tuss_dev_stat = app.capture_report.tuss_dev_stat;
    descriptor.out3_start_level =
        ((app.config.aux_flags & 0x01u) != 0u) ?
            app.capture_report.out3_start_level : 0xFFu;
    descriptor.out4_start_level =
        ((app.config.aux_flags & 0x02u) != 0u) ?
            app.capture_report.out4_start_level : 0xFFu;
    descriptor.event_count = app.capture_report.event_count;
    descriptor.quality_flags = app.capture_report.quality_flags |
        USAC_QUALITY_TIMING_UNCALIBRATED;
    for (index = 0u; index < app.capture_report.event_count; ++index) {
        descriptor.events[index] = app.capture_report.events[index];
    }
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        descriptor.register_pairs[index] = app.config.profile.registers[index];
    }
    usac_capture_stream_init(
        &capture_stream, &descriptor, g_usac_capture_waveform);
    usac_capture_tx_init(&capture_tx, &capture_stream);
    capture_stream_started = 1u;
}

static void send_next_capture_segment(void)
{
    const uint8_t *data;
    uint16_t length;

    if (capture_stream_started == 0u) {
        initialize_pending_capture_stream();
    }
    if (usac_capture_tx_peek(&capture_tx, &data, &length) == 0u) {
        if (capture_tx.state == USAC_CAPTURE_TX_COMPLETE) {
            app.capture_pending = 0u;
            capture_stream_started = 0u;
        } else if (capture_tx.state == USAC_CAPTURE_TX_FAILED) {
            usac_firmware_app_end_session(&app);
            capture_stream_started = 0u;
        }
        return;
    }
    g_usac_usb_send_complete = 0u;
    g_usac_last_send_result = USBCDC_sendData(
        (uint8_t *)data, length, CDC0_INTFNUM);
    if (g_usac_last_send_result == USBCDC_SEND_STARTED) {
        usac_capture_tx_on_start_result(
            &capture_tx, USAC_CAPTURE_TX_START_STARTED);
        usac_tx_gate_started(&tx_gate);
    } else if (g_usac_last_send_result == USBCDC_INTERFACE_BUSY_ERROR) {
        usac_capture_tx_on_start_result(
            &capture_tx, USAC_CAPTURE_TX_START_BUSY);
    } else {
        usac_capture_tx_on_start_result(
            &capture_tx, USAC_CAPTURE_TX_START_FATAL);
        usac_firmware_app_end_session(&app);
        capture_stream_started = 0u;
    }
}
#endif

static void initialize_frame_timeout_timer(void)
{
#ifdef USAC_ENABLE_ACQUISITION
    TA1CCTL0 = 0u;
    TA1CTL = TASSEL_1 | MC_2 | TACLR;
    /* TA1/ACLK owns both the parser timeout and lease wake-up. TA0 remains
     * free for the 24 MHz OUT3/OUT4 extended capture timebase. */
    g_usac_elapsed_quanta = 0u;
    TA1CCR1 = USAC_ACLK_QUANTUM_TICKS;
    TA1CCTL1 = CCIE;
#else
    TA0CCTL0 = 0u;
    TA0CTL = TASSEL_1 | MC_2 | TACLR;
#endif
}

static void arm_frame_timeout(void)
{
    /* One full 16-bit ACLK span is 2000 ms at 32768 Hz. */
#ifdef USAC_ENABLE_ACQUISITION
    TA1CCR0 = (uint16_t)(TA1R - 1u);
    TA1CCTL0 = CCIE;
#else
    TA0CCR0 = (uint16_t)(TA0R - 1u);
    TA0CCTL0 = CCIE;
#endif
    g_usac_frame_timeout_pending = 0u;
}

static void cancel_frame_timeout(void)
{
#ifdef USAC_ENABLE_ACQUISITION
    TA1CCTL0 = 0u;
#else
    TA0CCTL0 = 0u;
#endif
    g_usac_frame_timeout_pending = 0u;
}

static void write_u16_le(uint8_t *target, uint16_t value)
{
    target[0] = (uint8_t)value;
    target[1] = (uint8_t)(value >> 8);
}

static void write_u32_le(uint8_t *target, uint32_t value)
{
    target[0] = (uint8_t)value;
    target[1] = (uint8_t)(value >> 8);
    target[2] = (uint8_t)(value >> 16);
    target[3] = (uint8_t)(value >> 24);
}

static uint8_t initialize_identity(void)
{
    uint8_t byte_count;
    uint16_t *record_address;
    uint8_t encoded_record[USAC_DIE_RECORD_LENGTH];
    const struct s_TLV_Die_Record *die_record;

    byte_count = 0u;
    record_address = 0;
    TLV_getInfo(TLV_TAG_DIERECORD, 0u, &byte_count, &record_address);
    if ((record_address == 0) ||
        (byte_count < (uint8_t)sizeof(struct s_TLV_Die_Record))) {
        return 0u;
    }
    die_record = (const struct s_TLV_Die_Record *)record_address;
    write_u32_le(&encoded_record[0], die_record->wafer_id);
    write_u16_le(&encoded_record[4], die_record->die_x_position);
    write_u16_le(&encoded_record[6], die_record->die_y_position);
    write_u16_le(&encoded_record[8], die_record->test_results);
    if (usac_identity_die_record_valid(encoded_record) == 0u) {
        return 0u;
    }
    usac_identity_derive(encoded_record, device_id);
    return 1u;
}

static uint8_t initialize_clocks(void)
{
    g_usac_clock_stage = 1u;
    UCS_setExternalClockSource(32768ul, 4000000ul);
#ifdef USAC_ENABLE_ACQUISITION
    /* V1 lease expiry must keep advancing independently of USB and the DCO.
     * LaunchPad P5.4/P5.5 carry the populated 32.768 kHz XT1 crystal. */
    GPIO_setAsPeripheralModuleFunctionOutputPin(
        GPIO_PORT_P5,
        GPIO_PIN4 | GPIO_PIN5);
    g_usac_xt1_start_result = (uint8_t)UCS_turnOnLFXT1WithTimeout(
        UCS_XT1_DRIVE_0, UCS_XCAP_3, 65535u);
    if (g_usac_xt1_start_result == 0u) {
        return 0u;
    }
#endif
    /* TI USB stack requires the MSP430F5529 XT2 pins to be mapped before
     * starting the oscillator (P5.2=XT2IN, P5.3=XT2OUT).
     */
    GPIO_setAsPeripheralModuleFunctionOutputPin(
        GPIO_PORT_P5,
        GPIO_PIN2 | GPIO_PIN3);
    g_usac_xt2_start_result = (uint8_t)UCS_turnOnXT2WithTimeout(
        UCS_XT2_DRIVE_4MHZ_8MHZ, 65535u);
    if (g_usac_xt2_start_result == 0u) {
        return 0u;
    }
    g_usac_clock_stage = 2u;
    UCS_initClockSignal(
        UCS_FLLREF,
        UCS_XT2CLK_SELECT,
        UCS_CLOCK_DIVIDER_1);
    UCS_initClockSignal(
        UCS_ACLK,
#ifdef USAC_ENABLE_ACQUISITION
        UCS_XT1CLK_SELECT,
#else
        UCS_REFOCLK_SELECT,
#endif
        UCS_CLOCK_DIVIDER_1);
    /* 24 MHz / 4 MHz = 6; DriverLib selects DCORSEL=6. */
    UCS_initFLLSettle(24000u, 6u);
    g_usac_clock_stage = 3u;
    g_usac_clock_ucsctl7 = (uint8_t)UCSCTL7;
    g_usac_clock_sfrifg1 = (uint8_t)SFRIFG1;
#ifdef USAC_ENABLE_ACQUISITION
    if (((UCSCTL7 & (XT1LFOFFG | XT2OFFG | DCOFFG)) != 0u) ||
        ((SFRIFG1 & OFIFG) != 0u)) {
        return 0u;
    }
#else
    /* firmware/acquisition keep their accepted REFO path. XT1 is intentionally unused, so
     * the base image ignores only the corresponding unused-oscillator flag. */
    if (usac_firmware_clock_faults_safe((uint8_t)UCSCTL7) == 0u) {
        return 0u;
    }
#endif
    g_usac_clock_stage = 4u;
    return 1u;
}

#ifdef USAC_ENABLE_ACQUISITION
static uint16_t read_clock_fault_flags(void)
{
    uint16_t flags = 0u;

    if ((UCSCTL7 & XT2OFFG) != 0u) flags |= 0x0001u;
    if ((UCSCTL7 & DCOFFG) != 0u) flags |= 0x0002u;
    if ((UCSCTL7 & XT1LFOFFG) != 0u) flags |= 0x0004u;
    if ((SFRIFG1 & OFIFG) != 0u) flags |= 0x0008u;
    return flags;
}
#endif

static tuss4470_config_result_t initialize_tuss4470(
    tuss4470_config_report_t *report)
{
    tuss4470_profile_t profile;
    usac_firmware_timing_stage_t requested;
    usac_firmware_timing_stage_t readback;

    tuss4470_profile_init_d10x4(&profile);
    if ((usac_firmware_build_timing_stage(
             profile.sample_interval_ticks,
             profile.burst_period_ticks,
             &requested) != USAC_FIRMWARE_OK) ||
        (usac_platform_stage_timing(&requested, &readback) == 0u)) {
        return TUSS4470_CONFIG_INVALID_PROFILE;
    }
    return tuss4470_configure_firmware(
        &tuss_bus,
        &profile,
        USAC_VDRV_READY_POLL_LIMIT,
        report);
}

static tuss4470_config_result_t apply_profile(
    void *context,
    const tuss4470_profile_t *profile,
    tuss4470_config_report_t *report)
{
    usac_firmware_timing_stage_t requested;
    usac_firmware_timing_stage_t readback;

    (void)context;
    if ((usac_firmware_build_timing_stage(
             profile->sample_interval_ticks,
             profile->burst_period_ticks,
             &requested) != USAC_FIRMWARE_OK) ||
        (usac_platform_stage_timing(&requested, &readback) == 0u)) {
        return TUSS4470_CONFIG_INVALID_PROFILE;
    }
    return tuss4470_configure_firmware(
        &tuss_bus,
        profile,
        USAC_VDRV_READY_POLL_LIMIT,
        report);
}

static tuss4470_config_result_t force_safe(void *context)
{
    g_usac_force_safe_result = (uint8_t)tuss4470_force_safe(
        (const tuss4470_bus_t *)context);
    return (tuss4470_config_result_t)g_usac_force_safe_result;
}

static void process_usb_input(void)
{
    uint8_t receive_buffer[USAC_CDC_BUFFER_SIZE];
    uint16_t count;
    uint16_t index;
    usac_mcu_frame_view_t frame;
    usac_mcu_parse_result_t result;
    uint16_t response_length;

    g_usac_usb_data_pending = 0u;
    do {
        count = USBCDC_receiveDataInBuffer(
            receive_buffer,
            USAC_CDC_BUFFER_SIZE,
            CDC0_INTFNUM);
        for (index = 0u; index < count; ++index) {
            result = usac_mcu_parser_feed(&parser, receive_buffer[index], &frame);
            if ((result == USAC_MCU_PARSE_INCOMPLETE) &&
                (parser.count == 1u) && (receive_buffer[index] == 0x55u)) {
                arm_frame_timeout();
            } else if (result != USAC_MCU_PARSE_INCOMPLETE) {
                cancel_frame_timeout();
            } else if (parser.count == 0u) {
                cancel_frame_timeout();
            }
            if (result != USAC_MCU_PARSE_INCOMPLETE) {
                g_usac_last_parse_result = (uint8_t)result;
                if (result == USAC_MCU_PARSE_FRAME) {
                    g_usac_last_message_type = frame.message_type;
                    if (usac_firmware_app_handle(
                            &app,
                            &frame,
                            response_buffer,
                            (uint16_t)sizeof(response_buffer),
                            &response_length) != 0u) {
                        g_usac_usb_send_complete = 0u;
                        g_usac_last_send_result = USBCDC_sendData(
                            response_buffer,
                            response_length,
                            CDC0_INTFNUM);
                        if (g_usac_last_send_result == USBCDC_SEND_STARTED) {
                            usac_tx_gate_started(&tx_gate);
                        } else {
                            usac_firmware_app_end_session(&app);
                        }
                    }
                    return;
                }
            }
        }
    } while (count == USAC_CDC_BUFFER_SIZE);
}

int main(void)
{
    static const uint8_t empty_boot_id[16] = {0u};
    tuss4470_config_report_t report = {0u, 0u, 0u};
    uint8_t identity_valid;
    uint8_t previous_session_ready = 0u;

    WDTCTL = WDTPW | WDTHOLD;
    usac_platform_enter_reset_safe();
    usac_mcu_parser_init(&parser);
    usac_tx_gate_reset(&tx_gate);
#ifdef USAC_ENABLE_LOOPBACK
    capture_stream_started = 0u;
#endif

    PMM_setVCore(PMM_CORE_LEVEL_3);
    g_usac_clock_valid = initialize_clocks();
    if (g_usac_clock_valid == 0u) {
        for (;;) {
            usac_platform_enter_reset_safe();
            __bis_SR_register(LPM4_bits | GIE);
        }
    }
    usac_platform_spi_init();
    tuss_bus.context = 0;
    tuss_bus.read = usac_platform_tuss_read;
    tuss_bus.write = usac_platform_tuss_write;
    tuss_bus.delay_1ms = usac_platform_delay_1ms;

    identity_valid = initialize_identity();
    if (identity_valid == 0u) {
        g_usac_tuss_config_result = (uint8_t)TUSS4470_CONFIG_IDENTITY;
        for (;;) {
            usac_platform_enter_reset_safe();
            __bis_SR_register(LPM4_bits | GIE);
        }
    }
    g_usac_tuss_config_result = (uint8_t)initialize_tuss4470(&report);
    g_usac_tuss_device_id = report.device_id;
    g_usac_tuss_revision_id = report.revision_id;
    g_usac_tuss_dev_stat = report.dev_stat;
    usac_firmware_app_init(
        &app,
        device_id,
        empty_boot_id,
        0u,
        (g_usac_tuss_config_result == TUSS4470_CONFIG_OK) ?
            USAC_FIRMWARE_SESSION_WAIT : USAC_FIRMWARE_FAULT);
#ifdef USAC_ENABLE_ACQUISITION
    usac_firmware_app_record_boot_config(
        &app,
        (tuss4470_config_result_t)g_usac_tuss_config_result,
        report.dev_stat);
#endif
    app.apply_profile = apply_profile;
    app.safety_context = &tuss_bus;
    app.force_safe = force_safe;
#ifdef USAC_ENABLE_LOOPBACK
    app.loopback_context = &tuss_bus;
    app.run_io2_loopback = usac_platform_run_io2_loopback;
    app.capture_context = &tuss_bus;
    app.capture_once = usac_platform_capture_once;
#ifdef USAC_ENABLE_ACQUISITION
    app.capture = usac_platform_capture;
#endif
#endif

    USB_setup(FALSE, TRUE);
    /* TI USB_init() temporarily owns TA1 for XT2 frequency detection and
     * leaves it clocked from SMCLK. Reclaim TA1 only after USB_setup(), so
     * parser timeouts and V1 leases advance from the intended 32.768 kHz
     * ACLK on a fresh boot as well as after a CDC reconnect. */
    initialize_frame_timeout_timer();
    usac_identity_usb_serial_descriptor(
        device_id,
        abramSerialStringDescriptor);
    __delay_cycles(USAC_USB_DETACH_CYCLES);
    if ((USB_getConnectionInformation() & USB_VBUS_PRESENT) != 0u) {
        if (USB_enable() == USB_SUCCEED) {
            USB_reset();
            USB_connect();
        }
    }
    __enable_interrupt();

    for (;;) {
#ifdef USAC_ENABLE_ACQUISITION
        uint16_t elapsed_quanta;

        __disable_interrupt();
        elapsed_quanta = g_usac_elapsed_quanta;
        g_usac_elapsed_quanta = 0u;
        __enable_interrupt();
        if (elapsed_quanta != 0u) {
            usac_firmware_app_advance_time(
                &app, (uint32_t)elapsed_quanta * USAC_ACLK_QUANTUM_US);
        }
        usac_firmware_app_update_clock_faults(&app, read_clock_fault_flags());
#endif
        if (g_usac_dtr_session_ready == 0u) {
            if (previous_session_ready != 0u) {
                abort_usb_response();
                usac_platform_enter_reset_safe();
                initialize_frame_timeout_timer();
                cancel_frame_timeout();
                usac_mcu_parser_init(&parser);
                usac_firmware_app_end_session(&app);
            }
            previous_session_ready = 0u;
        } else {
            previous_session_ready = 1u;
        }
        if (g_usac_usb_send_complete != 0u) {
            g_usac_usb_send_complete = 0u;
#ifdef USAC_ENABLE_LOOPBACK
            if ((capture_stream_started != 0u) &&
                (capture_tx.state == USAC_CAPTURE_TX_IN_FLIGHT)) {
                usac_capture_tx_on_send_completed(&capture_tx);
                if (capture_tx.state == USAC_CAPTURE_TX_COMPLETE) {
                    app.capture_pending = 0u;
                    capture_stream_started = 0u;
                }
            }
#endif
            usac_tx_gate_completed(&tx_gate);
            g_usac_usb_data_pending = 1u;
        }
        if (g_usac_frame_timeout_pending != 0u) {
            g_usac_last_parse_result = (uint8_t)usac_mcu_parser_expire(&parser);
            cancel_frame_timeout();
        }
#ifdef USAC_ENABLE_ACQUISITION
        if ((g_usac_dtr_session_ready != 0u) &&
            (usac_firmware_app_periodic_due(&app) != 0u)) {
            (void)usac_firmware_app_run_periodic_capture(&app);
        }
#endif
        if ((USB_getConnectionState() == ST_ENUM_ACTIVE) &&
            (g_usac_dtr_session_ready != 0u) &&
            (usac_tx_gate_can_encode(&tx_gate) != 0u)
#ifdef USAC_ENABLE_LOOPBACK
            && (app.capture_pending != 0u)) {
            send_next_capture_segment();
        } else if ((USB_getConnectionState() == ST_ENUM_ACTIVE) &&
            (g_usac_dtr_session_ready != 0u) &&
            (usac_tx_gate_can_encode(&tx_gate) != 0u)
#endif
            && (g_usac_usb_data_pending != 0u)) {
            process_usb_input();
        }
        __bis_SR_register(LPM0_bits | GIE);
        __no_operation();
    }
}

#ifdef USAC_ENABLE_ACQUISITION
void __attribute__((interrupt(TIMER1_A0_VECTOR))) TIMER1_A0_ISR(void)
#else
void __attribute__((interrupt(TIMER0_A0_VECTOR))) TIMER0_A0_ISR(void)
#endif
{
#ifdef USAC_ENABLE_ACQUISITION
    TA1CCTL0 = 0u;
#else
    TA0CCTL0 = 0u;
#endif
    g_usac_frame_timeout_pending = 1u;
    __bic_SR_register_on_exit(LPM0_bits);
}

#ifdef USAC_ENABLE_ACQUISITION
void __attribute__((interrupt(TIMER1_A1_VECTOR))) TIMER1_A1_ISR(void)
{
    switch (__even_in_range(TA1IV, TA1IV_TAIFG)) {
        case TA1IV_NONE:
            break;
        case TA1IV_TACCR1:
            TA1CCR1 = (uint16_t)(TA1CCR1 + USAC_ACLK_QUANTUM_TICKS);
            if (g_usac_elapsed_quanta != 0xFFFFu) {
                ++g_usac_elapsed_quanta;
            }
            usac_platform_on_aclk_quantum();
            __bic_SR_register_on_exit(LPM0_bits);
            break;
        default:
            break;
    }
}
#endif

void __attribute__((interrupt(UNMI_VECTOR))) UNMI_ISR(void)
{
    switch (__even_in_range(SYSUNIV, SYSUNIV_BUSIFG)) {
        case SYSUNIV_NONE:
        case SYSUNIV_NMIIFG:
            break;
        case SYSUNIV_OFIFG:
            UCS_clearFaultFlag(UCS_XT2OFFG);
            UCS_clearFaultFlag(UCS_DCOFFG);
            SFR_clearInterrupt(SFR_OSCILLATOR_FAULT_INTERRUPT);
            break;
        case SYSUNIV_ACCVIFG:
            break;
        case SYSUNIV_BUSIFG:
            SYSBERRIV = 0u;
            USB_disable();
            usac_platform_enter_reset_safe();
            break;
        default:
            break;
    }
}
