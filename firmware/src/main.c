#include <msp430.h>

int main(void)
{
    WDTCTL = WDTPW | WDTHOLD;

    /* M0 safety: keep the future IO2 output high and never configure a timer. */
    P2OUT |= BIT5;
    P2DIR |= BIT5;
    P2SEL &= (unsigned char)~BIT5;

    for (;;) {
        __bis_SR_register(LPM4_bits | GIE);
        __no_operation();
    }
}
