/* Pure one-in-flight bookkeeping; it does not control an IO pin or timer. */
#ifndef USAC_TX_GATE_H
#define USAC_TX_GATE_H

#include <stdint.h>

typedef struct {
    uint8_t in_flight;
} usac_tx_gate_t;

void usac_tx_gate_reset(usac_tx_gate_t *gate);
uint8_t usac_tx_gate_can_encode(const usac_tx_gate_t *gate);
void usac_tx_gate_started(usac_tx_gate_t *gate);
void usac_tx_gate_completed(usac_tx_gate_t *gate);

#endif
