/* Commit-after-completion state machine for a CAPTURE_DATA frame. Separating
 * this policy from TI CDC keeps BUSY/retry and future delivery semantics from
 * leaking into the frame encoder or acquisition path. */
#include "usac_m3_capture_tx.h"

void usac_m3_capture_tx_init(
    usac_m3_capture_tx_t *tx,
    usac_m3_capture_stream_t *stream)
{
    if (tx == 0) {
        return;
    }
    tx->stream = stream;
    tx->state = ((stream != 0) && (stream->active != 0u)) ?
        USAC_M3_TX_READY : USAC_M3_TX_IDLE;
}

uint8_t usac_m3_capture_tx_peek(
    const usac_m3_capture_tx_t *tx,
    const uint8_t **data,
    uint16_t *length)
{
    if ((tx == 0) || (tx->state != USAC_M3_TX_READY)) {
        return 0u;
    }
    return usac_m3_capture_stream_peek(tx->stream, data, length);
}

void usac_m3_capture_tx_on_start_result(
    usac_m3_capture_tx_t *tx,
    usac_m3_capture_tx_start_result_t result)
{
    if ((tx == 0) || (tx->state != USAC_M3_TX_READY)) {
        return;
    }
    if (result == USAC_M3_TX_START_STARTED) {
        tx->state = USAC_M3_TX_IN_FLIGHT;
    } else if (result == USAC_M3_TX_START_BUSY) {
        tx->state = USAC_M3_TX_READY;
    } else {
        tx->state = USAC_M3_TX_FAILED;
    }
}

void usac_m3_capture_tx_on_send_completed(usac_m3_capture_tx_t *tx)
{
    if ((tx == 0) || (tx->state != USAC_M3_TX_IN_FLIGHT)) {
        return;
    }
    if (usac_m3_capture_stream_commit(tx->stream) == 0u) {
        tx->state = USAC_M3_TX_FAILED;
    } else if (tx->stream->active != 0u) {
        tx->state = USAC_M3_TX_READY;
    } else {
        tx->state = USAC_M3_TX_COMPLETE;
    }
}

void usac_m3_capture_tx_abort(usac_m3_capture_tx_t *tx)
{
    if (tx != 0) {
        tx->state = USAC_M3_TX_FAILED;
    }
}
