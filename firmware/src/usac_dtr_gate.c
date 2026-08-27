/* Tracks a real USB DTR low-to-high transition. Enumeration or an already-high
 * line is insufficient because a new host session must be explicitly opened. */
#include "usac_dtr_gate.h"

void usac_dtr_gate_reset(usac_dtr_gate_t *gate)
{
    gate->current_high = 0u;
    gate->low_observed = 0u;
    gate->session_ready = 0u;
}

void usac_dtr_gate_update(usac_dtr_gate_t *gate, uint8_t dtr_high)
{
    dtr_high = (uint8_t)(dtr_high != 0u);
    if (dtr_high == 0u) {
        gate->current_high = 0u;
        gate->low_observed = 1u;
        gate->session_ready = 0u;
        return;
    }
    if ((gate->current_high == 0u) && (gate->low_observed != 0u)) {
        gate->session_ready = 1u;
    }
    gate->current_high = 1u;
}

uint8_t usac_dtr_gate_ready(const usac_dtr_gate_t *gate)
{
    return gate->session_ready;
}
