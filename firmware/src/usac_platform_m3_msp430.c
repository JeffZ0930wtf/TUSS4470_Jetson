/* M3 acceptance-only IO2 loopback implementation for MSP430F5529.
 * BOOSTXL pin40/P2.5/TA2.2 is wired through 2.2 kOhm to pin38/P1.5/TA0.4.
 * TUSS4470 is forced to Standby/VDRV Hi-Z before any IO2 edge, so these
 * eight timer periods test the digital timing path without a Burst. */
#include <msp430.h>

#include "tuss4470_configurator.h"
#include "usac_m5_burst_plan.h"
#include "usac_m5_schedule.h"
#include "usac_platform_m3_msp430.h"

#define TUSS_IO1_BIT BIT4
#define TUSS_IO2_BIT BIT5
#define LOOPBACK_CAPTURE_BIT BIT5
#define LOOPBACK_TIMEOUT_TICKS 2400u
#define TUSS4470_REG_VDRV_CTRL 0x16u
#define TUSS4470_REG_TOF_CONFIG 0x1Bu
#define TUSS4470_REG_DEV_STAT 0x1Cu
#define TUSS4470_SAFE_VDRV_CTRL 0x20u
#define TUSS4470_SAFE_TOF_CONFIG 0x40u
#define CAPTURE_WAIT_LIMIT 6000000ul
#define OUT3_CAPTURE_BIT BIT3
#define OUT4_CAPTURE_BIT BIT2
#define SYNC_SLAVE_INPUT_BIT BIT1
#define SYNC_MASTER_OUTPUT_BIT BIT6
#define USAC_M5_QUALITY_EVENT_OVERFLOW 0x00000040ul
#define USAC_M5_QUALITY_EVENT_TIME_AMBIGUOUS 0x00000080ul

static volatile uint8_t capture_complete;
static volatile uint8_t capture_burst_complete;
static volatile uint16_t capture_trigger_sample_index;
#ifdef USAC_ENABLE_M5
static volatile uint16_t capture_pretrigger_target;
static volatile uint8_t capture_burst_periods_remaining;
static uint8_t capture_m5_active;
static uint8_t capture_m5_aux_flags;
static uint8_t capture_m5_trigger_source;
static uint32_t capture_m5_sync_timeout_ms;
static usac_m5_burst_plan_t capture_m5_burst_plan;
static volatile uint32_t capture_ta0_epoch;
static volatile uint16_t capture_event_sample_interval;
static volatile uint8_t capture_event_flags;
static volatile uint8_t capture_out4_count;
static volatile uint8_t capture_out4_last_level;
static volatile uint8_t capture_sync_waiting;
static volatile uint16_t capture_sync_wait_quanta;
static usac_m3_capture_report_t *capture_event_report;
#endif

#ifdef USAC_ENABLE_M5
static void capture_event_append(
    uint8_t channel,
    uint8_t level_after,
    uint16_t captured_tick,
    uint16_t cctl)
{
    uint32_t epoch = capture_ta0_epoch;
    uint32_t frame_offset;
    usac_m5_capture_event_t *event;

    if (capture_event_report == 0) {
        return;
    }
    if ((cctl & COV) != 0u) {
        capture_event_report->quality_flags |=
            USAC_M5_QUALITY_EVENT_TIME_AMBIGUOUS;
    }
    if (((TA0CTL & TAIFG) != 0u) && (captured_tick < 0x8000u)) {
        ++epoch;
    }
    frame_offset = (epoch << 16) | captured_tick;
    if (capture_event_report->event_count >= USAC_M5_MAX_CAPTURE_EVENTS) {
        capture_event_report->quality_flags |= USAC_M5_QUALITY_EVENT_OVERFLOW;
        return;
    }
    event = &capture_event_report->events[capture_event_report->event_count++];
    event->channel = channel;
    event->edge = (level_after != 0u) ? 1u : 2u;
    event->capture_method = 2u;
    event->level_after = level_after;
    event->sample_index = (int32_t)(
        frame_offset / capture_event_sample_interval);
    event->subsample_tick = (uint16_t)(
        frame_offset % capture_event_sample_interval);
    event->uncertainty_ticks = 1u;
    event->frame_offset_ticks = frame_offset;
}

static void capture_events_arm(
    uint8_t aux_flags,
    uint16_t sample_interval_ticks,
    usac_m3_capture_report_t *report)
{
    capture_event_report = report;
    capture_event_sample_interval = sample_interval_ticks;
    capture_ta0_epoch = 0ul;
    capture_event_flags = (uint8_t)(aux_flags & 0x03u);
    capture_out4_count = 0u;
    capture_out4_last_level = 0u;
    report->event_count = 0u;
    report->out3_start_level = 0xFFu;
    report->out4_start_level = 0xFFu;

    TA0CTL = TACLR;
    TA0CCTL1 = 0u;
    TA0CCTL2 = 0u;
    if ((aux_flags & 0x01u) != 0u) {
        P1DIR &= (uint8_t)~OUT3_CAPTURE_BIT;
        P1REN &= (uint8_t)~OUT3_CAPTURE_BIT;
        P1SEL |= OUT3_CAPTURE_BIT;
        TA0CCTL2 = CM_1 | CCIS_0 | SCS | CAP;
    }
    if ((aux_flags & 0x02u) != 0u) {
        P1DIR &= (uint8_t)~OUT4_CAPTURE_BIT;
        P1REN &= (uint8_t)~OUT4_CAPTURE_BIT;
        P1SEL |= OUT4_CAPTURE_BIT;
        TA0CCTL1 = CM_3 | CCIS_0 | SCS | CAP;
    }
}

static void capture_events_start(void)
{
    if ((capture_event_flags & 0x01u) != 0u) {
        capture_event_report->out3_start_level =
            (uint8_t)((P1IN & OUT3_CAPTURE_BIT) != 0u);
        TA0CCTL2 &= (uint16_t)~(CCIFG | COV);
        TA0CCTL2 |= CCIE;
    }
    if ((capture_event_flags & 0x02u) != 0u) {
        capture_event_report->out4_start_level =
            (uint8_t)((P1IN & OUT4_CAPTURE_BIT) != 0u);
        capture_out4_last_level = capture_event_report->out4_start_level;
        TA0CCTL1 &= (uint16_t)~(CCIFG | COV);
        TA0CCTL1 |= CCIE;
    }
    if (capture_event_flags != 0u) {
        TA0CTL = TASSEL_2 | MC_2 | TACLR | TAIE;
    }
}

static void capture_events_stop(void)
{
    TA0CCTL1 = 0u;
    TA0CCTL2 = 0u;
    TA0CTL = TACLR;
    capture_event_flags = 0u;
    capture_event_report = 0;
}

static void prepare_sync_pin(uint8_t trigger_source)
{
    if (trigger_source == 1u) {
        /* BOOSTXL pin-11 maps to LaunchPad P8.1.  It has no timer-capture
         * function, so the official low-to-high handshake is bounded-poll. */
        P8SEL &= (uint8_t)~SYNC_SLAVE_INPUT_BIT;
        P8DIR &= (uint8_t)~SYNC_SLAVE_INPUT_BIT;
        P8REN &= (uint8_t)~SYNC_SLAVE_INPUT_BIT;
    } else if (trigger_source == 2u) {
        /* BOOSTXL pin-13 maps to LaunchPad P2.6.  Hold it low until every
         * acquisition resource is armed, then publish one rising edge. */
        P2SEL &= (uint8_t)~SYNC_MASTER_OUTPUT_BIT;
        P2OUT &= (uint8_t)~SYNC_MASTER_OUTPUT_BIT;
        P2DIR |= SYNC_MASTER_OUTPUT_BIT;
    }
}

static uint8_t wait_for_slave_sync(uint32_t timeout_ms)
{
    uint8_t saw_low = (uint8_t)((P8IN & SYNC_SLAVE_INPUT_BIT) == 0u);
    uint16_t timeout_quanta =
        usac_m5_sync_timeout_guarded_quanta(timeout_ms);

    if (timeout_quanta == 0u) {
        return 0u;
    }
    capture_sync_wait_quanta = 0u;
    capture_sync_waiting = 1u;
    while (capture_sync_wait_quanta < timeout_quanta) {
        if ((P8IN & SYNC_SLAVE_INPUT_BIT) == 0u) {
            saw_low = 1u;
        } else if (saw_low != 0u) {
            capture_sync_waiting = 0u;
            return 1u;
        }
    }
    capture_sync_waiting = 0u;
    return 0u;
}

void usac_platform_m5_on_aclk_quantum(void)
{
    if ((capture_sync_waiting != 0u) &&
        (capture_sync_wait_quanta != 0xFFFFu)) {
        ++capture_sync_wait_quanta;
    }
}

static void finish_sync_pin(uint8_t trigger_source)
{
    if (trigger_source == 2u) {
        /* Returning low guarantees that the next master capture can emit a
         * new low-to-high transition instead of inheriting a stale high. */
        P2OUT &= (uint8_t)~SYNC_MASTER_OUTPUT_BIT;
    }
}

static void configure_m5_burst_outputs(const usac_m5_burst_plan_t *plan)
{
    P2OUT |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    P2DIR |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    P2SEL &= (uint8_t)~(TUSS_IO1_BIT | TUSS_IO2_BIT);
    TA2CTL = TACLR;
    TA2CCR0 = (uint16_t)(plan->period_ticks - 1u);
    TA2CCTL0 = CCIE;
    TA2CCTL1 = 0u;
    TA2CCTL2 = 0u;
    if ((plan->action_flags & USAC_M5_BURST_USE_IO1_TIMER) != 0u) {
        TA2CCR1 = plan->io1_fall_tick;
        TA2CCR2 = plan->io2_rise_tick;
        TA2CCTL1 = OUTMOD_7 | OUT;
        TA2CCTL2 = OUTMOD_3;
    } else {
        TA2CCR2 = (uint16_t)(plan->period_ticks / 2u);
        TA2CCTL2 = OUTMOD_7 | OUT;
    }
}

static void start_m5_burst_outputs(void)
{
    if ((capture_m5_burst_plan.action_flags &
         USAC_M5_BURST_USE_IO1_ENABLE) != 0u) {
        P2OUT &= (uint8_t)~TUSS_IO1_BIT;
    }
    if ((capture_m5_burst_plan.action_flags &
         USAC_M5_BURST_USE_IO1_TIMER) != 0u) {
        P2SEL |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    } else {
        P2SEL |= TUSS_IO2_BIT;
    }
    TA2CTL = TASSEL_2 | MC_1 | TACLR;
}
#endif
#ifndef USAC_M3_ADC_DMA_DIAGNOSTIC
/* DMA0SZ reloads its programmed block size after a completed block transfer.
 * Preserve completion explicitly so reporting does not mistake that reload for
 * an untouched DMA transfer. */
static volatile uint8_t capture_dma0_completed;
static uint16_t pretrigger_sink;
#endif

static uint8_t read_safety_snapshot(
    const tuss4470_bus_t *bus,
    uint8_t *spi_status,
    uint8_t *dev_stat,
    uint8_t *tof_config,
    uint8_t *vdrv_ctrl)
{
    *spi_status = 0u;
    if ((bus == 0) || (bus->read == 0) ||
        (bus->read(bus->context, TUSS4470_REG_DEV_STAT, dev_stat) == 0u) ||
        (bus->read(bus->context, TUSS4470_REG_TOF_CONFIG, tof_config) == 0u) ||
        (bus->read(bus->context, TUSS4470_REG_VDRV_CTRL, vdrv_ctrl) == 0u)) {
        *spi_status = 1u;
        return 0u;
    }
    return 1u;
}

static uint8_t snapshot_is_safe(
    uint8_t spi_status,
    uint8_t dev_stat,
    uint8_t tof_config,
    uint8_t vdrv_ctrl)
{
    return (uint8_t)(
        (spi_status == 0u) &&
        ((dev_stat & TUSS4470_DEV_STAT_FAULT_MASK) == 0u) &&
        (tof_config == TUSS4470_SAFE_TOF_CONFIG) &&
        (vdrv_ctrl == TUSS4470_SAFE_VDRV_CTRL));
}

static void restore_io2_high_and_stop_timers(void)
{
    TA2CTL = TACLR;
    TA2CCTL0 = 0u;
    TA2CCTL1 = 0u;
    TA2CCTL2 = 0u;
    /* Disconnect both possible timer outputs before restoring safe-high.
     * This also terminates IO_MODE 2 with both pins high as required. */
    P2SEL &= (uint8_t)~(TUSS_IO1_BIT | TUSS_IO2_BIT);
    P2OUT |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    P2DIR |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    TA0CCTL4 = 0u;
#ifdef USAC_ENABLE_M5
    if (capture_m5_active != 0u) {
        TA0CTL = TACLR;
    } else {
        TA0CTL = TASSEL_1 | MC_2 | TACLR;
    }
#else
    TA0CTL = TASSEL_1 | MC_2 | TACLR;
#endif
}

uint8_t usac_platform_run_io2_loopback(
    void *context,
    uint16_t burst_period_ticks,
    usac_m3_loopback_report_t *report)
{
    const tuss4470_bus_t *bus = (const tuss4470_bus_t *)context;
    uint16_t saved_status;
    uint16_t start_tick;
    uint8_t index;
    uint8_t started = 0u;

    if ((report == 0) || (burst_period_ticks != 50u) ||
        (tuss4470_force_safe(bus) != TUSS4470_CONFIG_OK)) {
        return 0u;
    }
    if (read_safety_snapshot(
            bus,
            &report->pre_spi_status,
            &report->pre_dev_stat,
            &report->pre_tof_config,
            &report->pre_vdrv_ctrl) == 0u) {
        return 0u;
    }
    if (snapshot_is_safe(
            report->pre_spi_status,
            report->pre_dev_stat,
            report->pre_tof_config,
            report->pre_vdrv_ctrl) == 0u) {
        return 0u;
    }

    /* Establish the idle-high source before arming capture. This prevents the
     * input mux transition from being accepted as loopback evidence. */
    P2OUT |= TUSS_IO2_BIT;
    P2DIR |= TUSS_IO2_BIT;
    P2SEL &= (uint8_t)~TUSS_IO2_BIT;

    /* P1.5 is always an input. TA0.4 captures the physical pin38 signal. */
    P1DIR &= (uint8_t)~LOOPBACK_CAPTURE_BIT;
    P1REN &= (uint8_t)~LOOPBACK_CAPTURE_BIT;
    P1SEL |= LOOPBACK_CAPTURE_BIT;
    TA0CTL = TACLR;
    TA0CCTL4 = CM_2 | CCIS_0 | SCS | CAP;

    TA2CTL = TACLR;
    TA2CCR0 = (uint16_t)(burst_period_ticks - 1u);
    TA2CCR2 = (uint16_t)(burst_period_ticks / 2u);
    TA2CCTL2 = OUTMOD_7 | OUT;

    saved_status = __get_SR_register();
    __disable_interrupt();
    /* Capture mux setup may leave CCIFG/COV set. Discard that stale state
     * before starting the shared evidence timebase and finite waveform. */
    TA0CCTL4 &= (uint16_t)~(CCIFG | COV);
    TA0CTL = TASSEL_2 | MC_2 | TACLR;
    start_tick = TA0R;
    P2SEL |= TUSS_IO2_BIT;
    TA2CTL = TASSEL_2 | MC_1 | TACLR;
    started = 1u;
    /* Switching a pin from GPIO to OUTMOD_7 may create one transition before
     * the compare output reaches its periodic state. Wait for and discard one
     * such settling edge; only the following eight edges are evidence. */
    while ((TA0CCTL4 & CCIFG) == 0u) {
        if ((uint16_t)(TA0R - start_tick) > LOOPBACK_TIMEOUT_TICKS) {
            report->result_flags |= USAC_M3_LOOPBACK_TIMEOUT;
            break;
        }
    }
    /* Timer_A only considers a captured value consumed after CCR is read.
     * Read the discarded startup value before clearing its flags so the first
     * evidence edge cannot be reported as a capture overflow. */
    (void)TA0CCR4;
    TA0CCTL4 &= (uint16_t)~(CCIFG | COV);
    start_tick = TA0R;
    for (index = 0u; index < USAC_M3_LOOPBACK_EDGE_COUNT; ++index) {
        while ((TA0CCTL4 & CCIFG) == 0u) {
            if ((uint16_t)(TA0R - start_tick) > LOOPBACK_TIMEOUT_TICKS) {
                report->result_flags |= USAC_M3_LOOPBACK_TIMEOUT;
                break;
            }
        }
        if ((report->result_flags & USAC_M3_LOOPBACK_TIMEOUT) != 0u) {
            break;
        }
        if ((TA0CCTL4 & COV) != 0u) {
            report->result_flags |= USAC_M3_LOOPBACK_COV_SEEN;
        }
        report->capture_ticks[index] = TA0CCR4;
        ++report->captured_edges;
        TA0CCTL4 &= (uint16_t)~(CCIFG | COV);
    }
    restore_io2_high_and_stop_timers();
    if ((saved_status & GIE) != 0u) {
        __enable_interrupt();
    }
    report->final_io2_level = (uint8_t)((P2IN & TUSS_IO2_BIT) != 0u);

    if ((tuss4470_force_safe(bus) != TUSS4470_CONFIG_OK) ||
        (read_safety_snapshot(
             bus,
             &report->post_spi_status,
             &report->post_dev_stat,
             &report->post_tof_config,
             &report->post_vdrv_ctrl) == 0u) ||
        (snapshot_is_safe(
             report->post_spi_status,
             report->post_dev_stat,
             report->post_tof_config,
             report->post_vdrv_ctrl) == 0u)) {
        report->result_flags |= USAC_M3_LOOPBACK_PREPOST_SAFETY_FAILED;
    }
    usac_m3_loopback_evaluate(report, burst_period_ticks);
    return started;
}

static void stop_capture_hardware(void)
{
    TB0CTL = TBCLR;
    TB0CCTL0 = 0u;
    TB0CCTL1 = 0u;
    TB0CCTL2 = 0u;
    TB0CCR2 = 0u;
    DMA0CTL &= (uint16_t)~(DMAEN | DMAIE);
    DMA1CTL &= (uint16_t)~(DMAEN | DMAIE);
    ADC12CTL0 &= (uint16_t)~ADC12ENC;
#ifdef USAC_ENABLE_M5
    if (capture_m5_active != 0u) {
        capture_events_stop();
    }
#endif
    restore_io2_high_and_stop_timers();
}

#ifndef USAC_M3_ADC_DMA_DIAGNOSTIC
static uint8_t prepare_adc_dma_capture_path(void)
{
    unsigned long idle_wait = CAPTURE_WAIT_LIMIT;

    /* Every capture starts from the same hardware state.  In particular,
     * stop both DMA channels before changing DMAxTSEL or the 20-bit address
     * registers, and power-cycle ADC12_A so a completed prior conversion
     * cannot leave the edge-sensitive ADC12IFG trigger asserted. */
    TB0CTL = TBCLR;
    DMA0CTL = 0u;
    DMA1CTL = 0u;
    DMACTL0 = 0u;
    ADC12CTL0 = 0u;
    while ((ADC12CTL1 & ADC12BUSY) != 0u) {
        if (idle_wait == 0ul) {
            return 0u;
        }
        --idle_wait;
    }
    ADC12IE = 0u;
    ADC12IFG = 0u;

    P6DIR &= (uint8_t)~BIT0;
    P6SEL |= BIT0;
    ADC12CTL1 = ADC12SHP | ADC12SHS_3 | ADC12SSEL_3 | ADC12DIV_5 |
                ADC12CONSEQ_2;
    ADC12CTL2 = ADC12RES_2;
    ADC12MCTL0 = ADC12SREF_0 | ADC12INCH_0;
    ADC12CTL0 = ADC12SHT0_0 | ADC12ON;

    /* DMARMWDIS is TI's DMA4 erratum workaround for the 20-bit source and
     * destination writes below.  TB0CCR2 provides a fresh trigger every
     * sample period instead of depending on the ADC12IFG edge state. */
    DMACTL4 = DMARMWDIS;
    DMACTL0 = DMA0TSEL_8 | DMA1TSEL_8;
    __data16_write_addr((uintptr_t)&DMA0SA, (uintptr_t)&ADC12MEM0);
    __data16_write_addr(
        (uintptr_t)&DMA0DA, (uintptr_t)g_usac_m3_waveform);
    DMA0SZ = USAC_M3_SAMPLE_COUNT;
    DMA0CTL = DMASRCINCR_0 | DMADSTINCR_3 | DMAIE | DMAEN;
    __data16_write_addr((uintptr_t)&DMA1SA, (uintptr_t)&ADC12MEM0);
    __data16_write_addr(
        (uintptr_t)&DMA1DA, (uintptr_t)&pretrigger_sink);
#ifdef USAC_ENABLE_M5
    DMA1SZ = capture_pretrigger_target;
    DMA1CTL = (capture_pretrigger_target == 0u) ? 0u :
        (DMASRCINCR_0 | DMADSTINCR_0 | DMAIE | DMAEN);
#else
    DMA1SZ = USAC_M3_PRETRIGGER_COUNT;
    DMA1CTL = DMASRCINCR_0 | DMADSTINCR_0 | DMAIE | DMAEN;
#endif
    return 1u;
}
#endif

uint8_t usac_platform_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report)
{
    const tuss4470_bus_t *bus = (const tuss4470_bus_t *)context;
    unsigned long wait_count = CAPTURE_WAIT_LIMIT;

    if ((bus == 0) || (bus->read == 0) || (report == 0) ||
#ifdef USAC_ENABLE_M5
        ((capture_m5_active != 0u) &&
         ((sample_interval_ticks < 120u) || (sample_interval_ticks > 960u) ||
          (burst_period_ticks < 24u) || (burst_period_ticks > 800u))) ||
        ((capture_m5_active == 0u) &&
         ((sample_interval_ticks != 120u) || (burst_period_ticks != 50u)))) {
#else
        (sample_interval_ticks != 120u) ||
        (burst_period_ticks != 50u)) {
#endif
        return 0u;
    }
#ifdef USAC_M3_ADC_DMA_DIAGNOSTIC
    uint16_t adc_sample = 0u;
    uint16_t adc_completed = 0u;
    uint16_t dma_completed = 0u;

    /* This compile-time-only diagnostic polls one software-triggered ADC12
     * conversion. It deliberately returns an incomplete capture report so
     * the host cannot store the baseline value as an ultrasonic waveform. */
    capture_burst_complete = 0u;
    capture_trigger_sample_index = 0u;
#ifdef USAC_ENABLE_M5
    if (capture_m5_active == 0u) {
        capture_pretrigger_target = USAC_M3_PRETRIGGER_COUNT;
        capture_burst_periods_remaining = 1u;
    }
#endif

    P6DIR &= (uint8_t)~BIT0;
    P6SEL |= BIT0;
    ADC12CTL0 &= (uint16_t)~ADC12ENC;
    ADC12CTL0 = ADC12SHT0_0 | ADC12ON;
    ADC12CTL1 = ADC12SHP | ADC12SHS_0 | ADC12SSEL_3 | ADC12DIV_5 |
                ADC12CONSEQ_0;
    ADC12CTL2 = ADC12RES_2;
    ADC12MCTL0 = ADC12SREF_0 | ADC12INCH_0;

    ADC12CTL0 |= ADC12ENC | ADC12SC;
    while (((ADC12IFG & ADC12IFG0) == 0u) && (wait_count != 0ul)) {
        --wait_count;
    }
    if ((ADC12IFG & ADC12IFG0) != 0u) {
        adc_completed = 1u;
        adc_sample = ADC12MEM0;
    } else {
        report->timed_out = 1u;
    }

    if (adc_completed != 0u) {
        g_usac_m3_waveform[0] = 0xFFFFu;
        DMA0CTL = 0u;
        DMACTL0 = DMA0TSEL_0;
        __data16_write_addr((uintptr_t)&DMA0SA, (uintptr_t)&adc_sample);
        __data16_write_addr(
            (uintptr_t)&DMA0DA, (uintptr_t)&g_usac_m3_waveform[0]);
        DMA0SZ = 1u;
        DMA0CTL = DMASRCINCR_0 | DMADSTINCR_0 | DMAEN;
        wait_count = CAPTURE_WAIT_LIMIT;
        DMA0CTL |= DMAREQ;
        while (((DMA0CTL & DMAIFG) == 0u) && (wait_count != 0ul)) {
            --wait_count;
        }
        if (((DMA0CTL & DMAIFG) != 0u) &&
            (g_usac_m3_waveform[0] == adc_sample)) {
            dma_completed = 1u;
        } else {
            report->timed_out = 1u;
        }
    }
    stop_capture_hardware();
    report->captured_samples = dma_completed;
    report->dma_remaining = g_usac_m3_waveform[0];
    report->trigger_sample_index = 0u;
    report->burst_completed = 0u;
    if ((bus->read(
             bus->context, TUSS4470_REG_DEV_STAT, &report->tuss_dev_stat) == 0u) ||
        ((report->tuss_dev_stat & TUSS4470_DEV_STAT_FAULT_MASK) != 0u)) {
        report->hardware_fault = 1u;
    }
    return 0u;
#else
    capture_complete = 0u;
    capture_dma0_completed = 0u;
    capture_burst_complete = 0u;
    capture_trigger_sample_index = 0u;
    pretrigger_sink = 0u;
#ifdef USAC_ENABLE_M5
    report->diagnostic_flags =
        ((__get_SR_register() & GIE) != 0u) ?
            USAC_M5_CAPTURE_DIAG_GIE_AT_ENTRY : 0u;
    report->diagnostic_timer_tick = 0u;
#endif
#ifdef USAC_ENABLE_M5
    if (capture_m5_active != 0u) {
        capture_events_arm(
            capture_m5_aux_flags, sample_interval_ticks, report);
    } else {
        report->out3_start_level = 0xFFu;
        report->out4_start_level = 0xFFu;
    }
#else
    report->out3_start_level = 0xFFu;
    report->out4_start_level = 0xFFu;
#endif

    if (prepare_adc_dma_capture_path() == 0u) {
        report->timed_out = 1u;
        stop_capture_hardware();
        return 0u;
    }

#ifdef USAC_ENABLE_M5
    if (capture_m5_active != 0u) {
        configure_m5_burst_outputs(&capture_m5_burst_plan);
    } else
#endif
    {
        P2OUT |= TUSS_IO2_BIT;
        P2DIR |= TUSS_IO2_BIT;
        P2SEL &= (uint8_t)~TUSS_IO2_BIT;
        TA2CTL = TACLR;
        TA2CCR0 = (uint16_t)(burst_period_ticks - 1u);
        TA2CCR2 = (uint16_t)(burst_period_ticks / 2u);
        TA2CCTL0 = CCIE;
        TA2CCTL2 = OUTMOD_7 | OUT;
    }

    TB0CTL = TBCLR;
    /* Keep CCR0 solely as the 5 us period boundary. TB0.1 rises at CCR1=1
     * and resets at CCR0, giving ADC12SHS_3 one unambiguous trigger edge per
     * sample without requiring a physical Timer_B output pin. */
    TB0CCR0 = (uint16_t)(sample_interval_ticks - 1u);
    TB0CCR1 = 1u;
    TB0CCTL1 = OUTMOD_3;
    /* ADC12_A needs 102 SMCLK ticks from the tick-1 sample trigger through
     * its four-clock hold and 13-clock conversion.  Tick 111 preserves the
     * approved eight-tick guard; CCIE must stay clear so CCIFG drives DMA. */
    TB0CCR2 = 111u;
    TB0CCTL2 = 0u;
    ADC12CTL0 |= ADC12ENC;
#ifdef USAC_ENABLE_M5
    if ((capture_m5_active != 0u) &&
        (capture_m5_trigger_source == 1u) &&
        (wait_for_slave_sync(capture_m5_sync_timeout_ms) == 0u)) {
        report->sync_timed_out = 1u;
        stop_capture_hardware();
        return 0u;
    }
    if (capture_m5_active != 0u) {
        capture_events_start();
        if (capture_m5_trigger_source == 2u) {
            P2OUT |= SYNC_MASTER_OUTPUT_BIT;
        }
    }
    if (capture_pretrigger_target == 0u) {
        capture_trigger_sample_index = 0u;
        start_m5_burst_outputs();
    }
#endif
    TB0CTL = TBSSEL_2 | MC_1 | TBCLR;
    while ((capture_complete == 0u) && (wait_count != 0ul)) {
        --wait_count;
    }
    if (capture_complete == 0u) {
        report->timed_out = 1u;
#ifdef USAC_ENABLE_M5
        /* Snapshot before stop_capture_hardware() clears the evidence. The
         * values are diagnostic only and never authorize a retry or success. */
        report->diagnostic_timer_tick = TB0R;
        if ((TB0CTL & MC_3) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_TB0_RUNNING;
        }
        if ((ADC12CTL0 & ADC12ENC) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_ADC_ENABLED;
        }
        if ((ADC12IFG & ADC12IFG0) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_ADC_IFG0;
        }
        if ((DMA0CTL & DMAEN) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_DMA0_ENABLED;
        }
        if ((DMA0CTL & DMAIFG) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_DMA0_IFG;
        }
        if ((DMA1CTL & DMAIFG) != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_DMA1_IFG;
        }
        if (capture_burst_complete != 0u) {
            report->diagnostic_flags |= USAC_M5_CAPTURE_DIAG_BURST_COMPLETE;
        }
#endif
    }
    stop_capture_hardware();
    if (capture_dma0_completed != 0u) {
        report->dma_remaining = 0u;
        report->captured_samples = USAC_M3_SAMPLE_COUNT;
    } else {
        report->dma_remaining = DMA0SZ;
        report->captured_samples =
            (uint16_t)(USAC_M3_SAMPLE_COUNT - DMA0SZ);
    }
    report->trigger_sample_index = capture_trigger_sample_index;
    report->burst_completed = capture_burst_complete;
    if ((bus->read(
             bus->context, TUSS4470_REG_DEV_STAT, &report->tuss_dev_stat) == 0u) ||
        ((report->tuss_dev_stat & TUSS4470_DEV_STAT_FAULT_MASK) != 0u)) {
        report->hardware_fault = 1u;
    }
#ifdef USAC_ENABLE_M5
    if (capture_m5_active != 0u) {
        return usac_m5_capture_report_is_complete(
            report, capture_pretrigger_target);
    }
#endif
    return usac_m3_capture_report_is_complete(report);
#endif
}

void __attribute__((interrupt(DMA_VECTOR))) DMA_ISR(void)
{
    switch (__even_in_range(DMAIV, DMAIV_DMA2IFG)) {
        case DMAIV_NONE:
            break;
        case DMAIV_DMA0IFG:
            TB0CTL = TBCLR;
            ADC12CTL0 &= (uint16_t)~ADC12ENC;
#ifndef USAC_M3_ADC_DMA_DIAGNOSTIC
            capture_dma0_completed = 1u;
#endif
            capture_complete = 1u;
            break;
        case DMAIV_DMA1IFG:
#ifdef USAC_ENABLE_M5
            capture_trigger_sample_index = capture_pretrigger_target;
            if (capture_m5_active != 0u) {
                start_m5_burst_outputs();
            } else {
                P2SEL |= TUSS_IO2_BIT;
                TA2CTL = TASSEL_2 | MC_1 | TACLR;
            }
#else
            capture_trigger_sample_index = USAC_M3_PRETRIGGER_COUNT;
            P2SEL |= TUSS_IO2_BIT;
            TA2CTL = TASSEL_2 | MC_1 | TACLR;
#endif
            break;
        default:
            stop_capture_hardware();
            capture_complete = 1u;
            break;
    }
}

#ifdef USAC_ENABLE_M5
void __attribute__((interrupt(TIMER0_A1_VECTOR))) TIMER0_A1_ISR(void)
{
    uint16_t captured_tick;
    uint16_t cctl;

    switch (__even_in_range(TA0IV, TA0IV_TAIFG)) {
        case TA0IV_NONE:
            break;
        case TA0IV_TACCR1:
            captured_tick = TA0CCR1;
            cctl = TA0CCTL1;
            if ((capture_event_flags & 0x02u) != 0u) {
                uint8_t level_after = (uint8_t)((cctl & CCI) != 0u);
                if (((cctl & COV) != 0u) ||
                    (level_after == capture_out4_last_level)) {
                    if (capture_event_report != 0) {
                        capture_event_report->quality_flags |=
                            USAC_M5_QUALITY_EVENT_TIME_AMBIGUOUS;
                    }
                    TA0CCTL1 = 0u;
                } else if (capture_out4_count < 16u) {
                    capture_event_append(
                        4u, level_after, captured_tick, cctl);
                    capture_out4_last_level = level_after;
                    ++capture_out4_count;
                } else if (capture_event_report != 0) {
                    capture_event_report->quality_flags |=
                        USAC_M5_QUALITY_EVENT_OVERFLOW;
                    TA0CCTL1 = 0u;
                }
            }
            break;
        case TA0IV_TACCR2:
            captured_tick = TA0CCR2;
            cctl = TA0CCTL2;
            if ((capture_event_flags & 0x01u) != 0u) {
                if ((cctl & COV) != 0u) {
                    if (capture_event_report != 0) {
                        capture_event_report->quality_flags |=
                            USAC_M5_QUALITY_EVENT_TIME_AMBIGUOUS;
                    }
                } else {
                    capture_event_append(3u, 1u, captured_tick, cctl);
                }
                capture_event_flags &= (uint8_t)~0x01u;
                TA0CCTL2 = 0u;
            }
            break;
        case TA0IV_TAIFG:
            ++capture_ta0_epoch;
            break;
        default:
            if (capture_event_report != 0) {
                capture_event_report->quality_flags |=
                    USAC_M5_QUALITY_EVENT_TIME_AMBIGUOUS;
            }
            break;
    }
}
#endif

void __attribute__((interrupt(TIMER2_A0_VECTOR))) TIMER2_A0_ISR(void)
{
#ifdef USAC_ENABLE_M5
    if ((capture_m5_active != 0u) &&
        (capture_burst_periods_remaining > 1u)) {
        --capture_burst_periods_remaining;
        return;
    }
#endif
    TA2CTL = TACLR;
    TA2CCTL0 = 0u;
    TA2CCTL1 = 0u;
    TA2CCTL2 = 0u;
    P2SEL &= (uint8_t)~(TUSS_IO1_BIT | TUSS_IO2_BIT);
    P2OUT |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    P2DIR |= TUSS_IO1_BIT | TUSS_IO2_BIT;
    capture_burst_complete = 1u;
}

#ifdef USAC_ENABLE_M5
uint8_t usac_platform_capture_m5(
    void *context,
    const usac_config_v2_t *config,
    uint8_t trigger_source,
    uint32_t sync_timeout_ms,
    usac_m3_capture_report_t *report)
{
    const tuss4470_bus_t *bus = (const tuss4470_bus_t *)context;
    uint8_t io_mode;
    uint8_t pulse_count;
    uint8_t tof_base;
    uint8_t tof_readback = 0u;
    uint8_t cmd_trigger_armed = 0u;
    uint32_t posttrigger_ticks;
    uint8_t result;

    if ((bus == 0) || (bus->read == 0) || (bus->write == 0) ||
        (config == 0) || (report == 0) || (trigger_source > 2u) ||
        ((trigger_source == 1u) &&
         ((sync_timeout_ms == 0ul) || (sync_timeout_ms > 60000ul))) ||
        ((trigger_source != 1u) && (sync_timeout_ms != 0ul)) ||
        (config->sample_count != USAC_M3_SAMPLE_COUNT) ||
        (config->pretrigger_count >= USAC_M3_SAMPLE_COUNT)) {
        return 0u;
    }
    io_mode = (uint8_t)(config->profile.registers[4].value & 0x03u);
    pulse_count = (uint8_t)(config->profile.registers[8].value & 0x3Fu);
    posttrigger_ticks =
        (uint32_t)(USAC_M3_SAMPLE_COUNT - config->pretrigger_count) *
        config->profile.sample_interval_ticks;
    if (usac_m5_burst_plan_build(
            io_mode,
            pulse_count,
            config->profile.burst_period_ticks,
            posttrigger_ticks,
            &capture_m5_burst_plan) == 0u) {
        return 0u;
    }
    prepare_sync_pin(trigger_source);
    capture_pretrigger_target = config->pretrigger_count;
    capture_burst_periods_remaining = pulse_count;
    capture_m5_aux_flags = config->aux_flags;
    capture_m5_trigger_source = trigger_source;
    capture_m5_sync_timeout_ms = sync_timeout_ms;
    capture_m5_active = 1u;

    /* IO_MODE 0 uses the stateful SPI enable while IO2 is still safe-high.
     * It is always cleared after the attempt, including sync/ADC timeouts. */
    tof_base = config->profile.registers[9].value;
    if ((capture_m5_burst_plan.action_flags &
         USAC_M5_BURST_USE_CMD_TRIGGER) != 0u) {
        if (bus->write(bus->context, TUSS4470_REG_TOF_CONFIG,
                       (uint8_t)(tof_base | 0x01u)) == 0u) {
            report->hardware_fault = 1u;
            result = 0u;
        } else {
            cmd_trigger_armed = 1u;
            if ((bus->read(bus->context, TUSS4470_REG_TOF_CONFIG,
                           &tof_readback) == 0u) ||
                ((tof_readback & 0x01u) == 0u)) {
                report->hardware_fault = 1u;
                result = 0u;
            } else {
                result = usac_platform_capture_once(
                    context,
                    config->profile.sample_interval_ticks,
                    config->profile.burst_period_ticks,
                    report);
            }
        }
    } else {
        result = usac_platform_capture_once(
            context,
            config->profile.sample_interval_ticks,
            config->profile.burst_period_ticks,
            report);
    }
    finish_sync_pin(trigger_source);
    if ((cmd_trigger_armed != 0u) &&
        ((bus->write(bus->context, TUSS4470_REG_TOF_CONFIG, tof_base) == 0u) ||
         (bus->read(bus->context, TUSS4470_REG_TOF_CONFIG,
                    &tof_readback) == 0u) ||
         (tof_readback != tof_base))) {
        report->hardware_fault = 1u;
        result = 0u;
    }
    capture_m5_active = 0u;
    capture_m5_aux_flags = 0u;
    capture_m5_trigger_source = 0u;
    capture_m5_sync_timeout_ms = 0ul;
    capture_burst_periods_remaining = 0u;
    return result;
}
#endif
