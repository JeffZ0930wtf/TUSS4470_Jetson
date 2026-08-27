/* Pure state machine requiring an observed DTR low before accepting a rising
 * edge as the start of a host protocol session. */
#ifndef USAC_DTR_GATE_H
#define USAC_DTR_GATE_H

#include <stdint.h>

typedef struct {
    uint8_t current_high;
    uint8_t low_observed;
    uint8_t session_ready;
} usac_dtr_gate_t;

void usac_dtr_gate_reset(usac_dtr_gate_t *gate);
void usac_dtr_gate_update(usac_dtr_gate_t *gate, uint8_t dtr_high);
uint8_t usac_dtr_gate_ready(const usac_dtr_gate_t *gate);

#endif
