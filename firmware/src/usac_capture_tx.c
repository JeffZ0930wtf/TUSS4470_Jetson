/* Commit-after-completion state machine for a CAPTURE_DATA frame. Separating
 * this policy from TI CDC keeps BUSY/retry and future delivery semantics from
 * leaking into the frame encoder or acquisition path. */
#include "usac_capture_tx.h"

void usac_capture_tx_init(
    usac_capture_tx_t *tx,
    usac_capture_stream_t *stream)
{
    if (tx == 0) {
        return;
    }
    tx->stream = stream;
    tx->state = ((stream != 0) && (stream->active != 0u)) ?
        USAC_CAPTURE_TX_READY : USAC_CAPTURE_TX_IDLE;
}

uint8_t usac_capture_tx_peek(
    const usac_capture_tx_t *tx,
    const uint8_t **data,
    uint16_t *length)
{
    if ((tx == 0) || (tx->state != USAC_CAPTURE_TX_READY)) {
        return 0u;
    }
    return usac_capture_stream_peek(tx->stream, data, length);
}

void usac_capture_tx_on_start_result(
    usac_capture_tx_t *tx,
    usac_capture_tx_start_result_t result)
{
    if ((tx == 0) || (tx->state != USAC_CAPTURE_TX_READY)) {
        return;
    }
    if (result == USAC_CAPTURE_TX_START_STARTED) {
        tx->state = USAC_CAPTURE_TX_IN_FLIGHT;
    } else if (result == USAC_CAPTURE_TX_START_BUSY) {
        tx->state = USAC_CAPTURE_TX_READY;
    } else {
        tx->state = USAC_CAPTURE_TX_FAILED;
    }
}

void usac_capture_tx_on_send_completed(usac_capture_tx_t *tx)
{
    if ((tx == 0) || (tx->state != USAC_CAPTURE_TX_IN_FLIGHT)) {
        return;
    }
    if (usac_capture_stream_commit(tx->stream) == 0u) {
        tx->state = USAC_CAPTURE_TX_FAILED;
    } else if (tx->stream->active != 0u) {
        tx->state = USAC_CAPTURE_TX_READY;
    } else {
        tx->state = USAC_CAPTURE_TX_COMPLETE;
    }
}

void usac_capture_tx_abort(usac_capture_tx_t *tx)
{
    if (tx != 0) {
        tx->state = USAC_CAPTURE_TX_FAILED;
    }
}
