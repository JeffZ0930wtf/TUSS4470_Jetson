/* M3 acceptance-only IO2 loopback implementation for MSP430F5529.
 * BOOSTXL pin40/P2.5/TA2.2 is wired through 2.2 kOhm to pin38/P1.5/TA0.4.
 * TUSS4470 is forced to Standby/VDRV Hi-Z before any IO2 edge, so these
 * eight timer periods test the digital timing path without a Burst. */
#include <msp430.h>

#include "tuss4470_configurator.h"
#include "usac_platform_m3_msp430.h"

#define TUSS_IO2_BIT BIT5
#define LOOPBACK_CAPTURE_BIT BIT5
#define LOOPBACK_TIMEOUT_TICKS 2400u
#define TUSS4470_REG_VDRV_CTRL 0x16u
#define TUSS4470_REG_TOF_CONFIG 0x1Bu
#define TUSS4470_REG_DEV_STAT 0x1Cu
#define TUSS4470_SAFE_VDRV_CTRL 0x20u
#define TUSS4470_SAFE_TOF_CONFIG 0x40u
#define CAPTURE_WAIT_LIMIT 6000000ul

static volatile uint8_t capture_complete;
static volatile uint8_t capture_burst_complete;
static volatile uint16_t capture_trigger_sample_index;
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
    TA2CCTL2 = 0u;
    /* Disconnect the peripheral before restoring the already-high latch. */
    P2SEL &= (uint8_t)~TUSS_IO2_BIT;
    P2OUT |= TUSS_IO2_BIT;
    P2DIR |= TUSS_IO2_BIT;
    TA0CCTL4 = 0u;
    TA0CTL = TASSEL_1 | MC_2 | TACLR;
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
    DMA0CTL &= (uint16_t)~(DMAEN | DMAIE);
    DMA1CTL &= (uint16_t)~(DMAEN | DMAIE);
    ADC12CTL0 &= (uint16_t)~ADC12ENC;
    restore_io2_high_and_stop_timers();
}

uint8_t usac_platform_capture_once(
    void *context,
    uint16_t sample_interval_ticks,
    uint16_t burst_period_ticks,
    usac_m3_capture_report_t *report)
{
    const tuss4470_bus_t *bus = (const tuss4470_bus_t *)context;
    unsigned long wait_count = CAPTURE_WAIT_LIMIT;

    if ((bus == 0) || (bus->read == 0) ||
        (report == 0) || (sample_interval_ticks != 120u) ||
        (burst_period_ticks != 50u)) {
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

    P6DIR &= (uint8_t)~BIT0;
    P6SEL |= BIT0;
    ADC12CTL0 &= (uint16_t)~ADC12ENC;
    ADC12CTL0 = ADC12SHT0_0 | ADC12ON;
    ADC12CTL1 = ADC12SHP | ADC12SHS_3 | ADC12SSEL_3 | ADC12DIV_5 |
                ADC12CONSEQ_2;
    ADC12CTL2 = ADC12RES_2;
    ADC12MCTL0 = ADC12SREF_0 | ADC12INCH_0;

    DMA0CTL = 0u;
    DMA1CTL = 0u;
    DMACTL0 = DMA0TSEL_24 | DMA1TSEL_24;
    __data16_write_addr((uintptr_t)&DMA0SA, (uintptr_t)&ADC12MEM0);
    __data16_write_addr(
        (uintptr_t)&DMA0DA, (uintptr_t)g_usac_m3_waveform);
    DMA0SZ = USAC_M3_SAMPLE_COUNT;
    DMA0CTL = DMASRCINCR_0 | DMADSTINCR_3 | DMAIE | DMAEN;
    __data16_write_addr((uintptr_t)&DMA1SA, (uintptr_t)&ADC12MEM0);
    __data16_write_addr(
        (uintptr_t)&DMA1DA, (uintptr_t)&pretrigger_sink);
    DMA1SZ = USAC_M3_PRETRIGGER_COUNT;
    DMA1CTL = DMASRCINCR_0 | DMADSTINCR_0 | DMAIE | DMAEN;

    P2OUT |= TUSS_IO2_BIT;
    P2DIR |= TUSS_IO2_BIT;
    P2SEL &= (uint8_t)~TUSS_IO2_BIT;
    TA2CTL = TACLR;
    TA2CCR0 = (uint16_t)(burst_period_ticks - 1u);
    TA2CCR2 = (uint16_t)(burst_period_ticks / 2u);
    TA2CCTL0 = CCIE;
    TA2CCTL2 = OUTMOD_7 | OUT;

    TB0CTL = TBCLR;
    /* Keep CCR0 solely as the 5 us period boundary. TB0.1 rises at CCR1=1
     * and resets at CCR0, giving ADC12SHS_3 one unambiguous trigger edge per
     * sample without requiring a physical Timer_B output pin. */
    TB0CCR0 = (uint16_t)(sample_interval_ticks - 1u);
    TB0CCR1 = 1u;
    TB0CCTL1 = OUTMOD_3;
    ADC12CTL0 |= ADC12ENC;
    TB0CTL = TBSSEL_2 | MC_1 | TBCLR;
    while ((capture_complete == 0u) && (wait_count != 0ul)) {
        --wait_count;
    }
    if (capture_complete == 0u) {
        report->timed_out = 1u;
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
            capture_trigger_sample_index = USAC_M3_PRETRIGGER_COUNT;
            P2SEL |= TUSS_IO2_BIT;
            TA2CTL = TASSEL_2 | MC_1 | TACLR;
            break;
        default:
            stop_capture_hardware();
            capture_complete = 1u;
            break;
    }
}

void __attribute__((interrupt(TIMER2_A0_VECTOR))) TIMER2_A0_ISR(void)
{
    TA2CTL = TACLR;
    TA2CCTL0 = 0u;
    TA2CCTL2 = 0u;
    P2SEL &= (uint8_t)~TUSS_IO2_BIT;
    P2OUT |= TUSS_IO2_BIT;
    P2DIR |= TUSS_IO2_BIT;
    capture_burst_complete = 1u;
}
