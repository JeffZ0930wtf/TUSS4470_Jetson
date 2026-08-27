#include <msp430.h>

#include "usac_m2_core.h"
#include "usac_platform_msp430.h"

#define TUSS_NCS_BIT BIT7
#define TUSS_IO1_BIT BIT4
#define TUSS_IO2_BIT BIT5
#define TUSS_SPI_TIMEOUT 65535u

void usac_platform_enter_reset_safe(void)
{
    /* Set output latches before direction to avoid a low-going IO2 glitch. */
    P2OUT |= (TUSS_IO2_BIT | TUSS_NCS_BIT);
    P2SEL &= (uint8_t)~(TUSS_IO1_BIT | TUSS_IO2_BIT | TUSS_NCS_BIT);
    P2DIR &= (uint8_t)~TUSS_IO1_BIT;
    P2DIR |= (TUSS_IO2_BIT | TUSS_NCS_BIT);

    TA2CCTL1 = 0u;
    TA2CCTL2 = 0u;
    TA2CTL = TACLR;
    TA0CCTL0 = 0u;
    TA0CTL = TACLR;
    TB0CTL = TBCLR;
    DMA0CTL = 0u;
    DMA1CTL = 0u;
    DMA2CTL = 0u;
    ADC12CTL0 &= (uint16_t)~ADC12ENC;
    ADC12CTL0 = 0u;
}

void usac_platform_spi_init(void)
{
    P2OUT |= TUSS_NCS_BIT;
    P2DIR |= TUSS_NCS_BIT;
    P2SEL &= (uint8_t)~TUSS_NCS_BIT;

    UCB0CTL1 = UCSWRST;
    P3SEL |= (BIT0 | BIT1 | BIT2);
    /* TUSS4470 SPI mode 1 maps to UCCKPH=0/UCCKPL=0 on MSP430 USCI.
     * Use 1 MHz during hardware bring-up: 24 MHz SMCLK / 24.
     */
    UCB0CTL0 = UCMSB | UCMST | UCSYNC;
    UCB0CTL1 = UCSWRST | UCSSEL_2;
    UCB0BR0 = 24u;
    UCB0BR1 = 0u;
    UCB0CTL1 &= (uint8_t)~UCSWRST;
}

uint8_t usac_platform_stage_timing(
    const usac_m2_timing_stage_t *requested,
    usac_m2_timing_stage_t *readback)
{
    if ((requested == 0) || (readback == 0)) {
        return 0u;
    }

    /* M2 only preloads divisors. Both timers remain stopped and IO2 stays GPIO-high. */
    P2OUT |= TUSS_IO2_BIT;
    P2SEL &= (uint8_t)~TUSS_IO2_BIT;
    P2DIR |= TUSS_IO2_BIT;
    TB0CTL = TBCLR;
    TA2CTL = TACLR;
    TB0CCTL0 = 0u;
    TA2CCTL1 = 0u;
    TA2CCTL2 = 0u;
    TB0CCR0 = requested->tb0_ccr0;
    TA2CCR0 = requested->ta2_ccr0;

    readback->sample_interval_ticks = (uint16_t)(TB0CCR0 + 1u);
    readback->burst_period_ticks = (uint16_t)(TA2CCR0 + 1u);
    readback->tb0_ccr0 = TB0CCR0;
    readback->ta2_ccr0 = TA2CCR0;
    readback->timer_control_bits = (uint16_t)(
        (TB0CTL & MC_3) | (TA2CTL & MC_3));
    return (uint8_t)(
        (readback->sample_interval_ticks == requested->sample_interval_ticks) &&
        (readback->burst_period_ticks == requested->burst_period_ticks) &&
        (readback->timer_control_bits == 0u));
}

static uint8_t spi_transfer_word(uint16_t transmit, uint16_t *receive)
{
    uint16_t timeout;
    uint8_t receive_high;
    uint8_t receive_low;

    P2OUT &= (uint8_t)~TUSS_NCS_BIT;

    timeout = TUSS_SPI_TIMEOUT;
    while (((UCB0IFG & UCTXIFG) == 0u) && (--timeout != 0u)) {
    }
    if (timeout == 0u) {
        P2OUT |= TUSS_NCS_BIT;
        return 0u;
    }
    UCB0TXBUF = (uint8_t)(transmit >> 8);
    timeout = TUSS_SPI_TIMEOUT;
    while (((UCB0IFG & UCRXIFG) == 0u) && (--timeout != 0u)) {
    }
    if (timeout == 0u) {
        P2OUT |= TUSS_NCS_BIT;
        return 0u;
    }
    receive_high = UCB0RXBUF;

    timeout = TUSS_SPI_TIMEOUT;
    while (((UCB0IFG & UCTXIFG) == 0u) && (--timeout != 0u)) {
    }
    if (timeout == 0u) {
        P2OUT |= TUSS_NCS_BIT;
        return 0u;
    }
    UCB0TXBUF = (uint8_t)transmit;
    timeout = TUSS_SPI_TIMEOUT;
    while (((UCB0IFG & UCRXIFG) == 0u) && (--timeout != 0u)) {
    }
    if (timeout == 0u) {
        P2OUT |= TUSS_NCS_BIT;
        return 0u;
    }
    receive_low = UCB0RXBUF;

    P2OUT |= TUSS_NCS_BIT;
    *receive = (uint16_t)(((uint16_t)receive_high << 8) | receive_low);
    return 1u;
}

uint8_t usac_platform_tuss_read(void *context, uint8_t address, uint8_t *value)
{
    uint16_t receive;

    (void)context;
    if ((value == 0) ||
        (spi_transfer_word(tuss4470_spi_read_word(address), &receive) == 0u)) {
        return 0u;
    }
    *value = (uint8_t)receive;
    return 1u;
}

uint8_t usac_platform_tuss_write(void *context, uint8_t address, uint8_t value)
{
    uint16_t receive;

    (void)context;
    return spi_transfer_word(tuss4470_spi_write_word(address, value), &receive);
}

void usac_platform_delay_1ms(void *context)
{
    (void)context;
    __delay_cycles(24000ul);
}
