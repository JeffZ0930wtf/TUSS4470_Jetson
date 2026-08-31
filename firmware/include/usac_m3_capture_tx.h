/* Transport-neutral ownership for one CAPTURE_DATA frame. The adapter reports
 * whether a stable segment was accepted, busy, completed, or failed; this
 * module never invokes USB, captures samples, or owns waveform memory. */
#ifndef USAC_M3_CAPTURE_TX_H
#define USAC_M3_CAPTURE_TX_H

#include <stdint.h>

#include "usac_m3_capture_stream.h"

typedef enum {
    USAC_M3_TX_IDLE = 0,
    USAC_M3_TX_READY = 1,
    USAC_M3_TX_IN_FLIGHT = 2,
    USAC_M3_TX_COMPLETE = 3,
    USAC_M3_TX_FAILED = 4
} usac_m3_capture_tx_state_t;

typedef enum {
    USAC_M3_TX_START_STARTED = 0,
    USAC_M3_TX_START_BUSY = 1,
    USAC_M3_TX_START_FATAL = 2
} usac_m3_capture_tx_start_result_t;

typedef struct {
    usac_m3_capture_stream_t *stream;
    usac_m3_capture_tx_state_t state;
} usac_m3_capture_tx_t;

void usac_m3_capture_tx_init(
    usac_m3_capture_tx_t *tx,
    usac_m3_capture_stream_t *stream);
uint8_t usac_m3_capture_tx_peek(
    const usac_m3_capture_tx_t *tx,
    const uint8_t **data,
    uint16_t *length);
void usac_m3_capture_tx_on_start_result(
    usac_m3_capture_tx_t *tx,
    usac_m3_capture_tx_start_result_t result);
void usac_m3_capture_tx_on_send_completed(usac_m3_capture_tx_t *tx);
void usac_m3_capture_tx_abort(usac_m3_capture_tx_t *tx);

#endif
