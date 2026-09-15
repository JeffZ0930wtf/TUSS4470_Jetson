/* Tracks ownership of the command-response buffer during USB transmission.
 * Encoding must wait until completion or reset releases the buffer. This
 * bookkeeping module does not control the ultrasonic transmitter. */
#include "usac_tx_gate.h"

void usac_tx_gate_reset(usac_tx_gate_t *gate)
{
    gate->in_flight = 0u;
}

uint8_t usac_tx_gate_can_encode(const usac_tx_gate_t *gate)
{
    return (uint8_t)(gate->in_flight == 0u);
}

void usac_tx_gate_started(usac_tx_gate_t *gate)
{
    gate->in_flight = 1u;
}

void usac_tx_gate_completed(usac_tx_gate_t *gate)
{
    gate->in_flight = 0u;
}
