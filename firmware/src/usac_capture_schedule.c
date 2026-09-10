#include "usac_capture_schedule.h"

static uint8_t ids_equal(const uint8_t left[16], const uint8_t right[16])
{
    uint8_t difference = 0u;
    uint8_t index;

    for (index = 0u; index < 16u; ++index) {
        difference |= (uint8_t)(left[index] ^ right[index]);
    }
    return (uint8_t)(difference == 0u);
}

static uint8_t id_is_nonzero(const uint8_t value[16])
{
    uint8_t combined = 0u;
    uint8_t index;

    for (index = 0u; index < 16u; ++index) {
        combined |= value[index];
    }
    return (uint8_t)(combined != 0u);
}

void usac_capture_schedule_init(usac_capture_schedule_t *schedule)
{
    uint8_t index;

    schedule->active = 0u;
    schedule->due = 0u;
    for (index = 0u; index < 16u; ++index) {
        schedule->schedule_id[index] = 0u;
    }
    schedule->period_us = 0ul;
    schedule->until_due_us = 0ul;
    schedule->capture_limit = 0ul;
    schedule->completed_count = 0ul;
    schedule->missed_count = 0ul;
    schedule->lease_sequence = 0ul;
    schedule->last_lease_timeout_ms = 0u;
    schedule->lease_remaining_us = 0ul;
}

usac_capture_schedule_result_t usac_capture_schedule_start(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16],
    uint32_t period_us,
    uint32_t capture_count,
    uint16_t lease_timeout_ms)
{
    uint8_t index;

    if (schedule->active != 0u) {
        return USAC_CAPTURE_SCHEDULE_CONFLICT;
    }
    if ((id_is_nonzero(schedule_id) == 0u) ||
        (period_us < USAC_CAPTURE_MIN_PERIOD_US) ||
        (lease_timeout_ms < USAC_CAPTURE_MIN_LEASE_MS) ||
        (lease_timeout_ms > USAC_CAPTURE_MAX_LEASE_MS)) {
        return USAC_CAPTURE_SCHEDULE_INVALID;
    }
    usac_capture_schedule_init(schedule);
    for (index = 0u; index < 16u; ++index) {
        schedule->schedule_id[index] = schedule_id[index];
    }
    schedule->active = 1u;
    schedule->period_us = period_us;
    schedule->until_due_us = period_us;
    schedule->capture_limit = capture_count;
    schedule->last_lease_timeout_ms = lease_timeout_ms;
    schedule->lease_remaining_us = (uint32_t)lease_timeout_ms * 1000ul;
    return USAC_CAPTURE_SCHEDULE_OK;
}

usac_capture_schedule_result_t usac_capture_schedule_renew(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16],
    uint32_t lease_sequence,
    uint16_t lease_timeout_ms)
{
    if ((schedule->active == 0u) ||
        (ids_equal(schedule->schedule_id, schedule_id) == 0u)) {
        return USAC_CAPTURE_SCHEDULE_CONFLICT;
    }
    if ((lease_sequence == 0ul) ||
        (lease_timeout_ms < USAC_CAPTURE_MIN_LEASE_MS) ||
        (lease_timeout_ms > USAC_CAPTURE_MAX_LEASE_MS)) {
        return USAC_CAPTURE_SCHEDULE_INVALID;
    }
    if (lease_sequence == schedule->lease_sequence) {
        return (lease_timeout_ms == schedule->last_lease_timeout_ms) ?
            USAC_CAPTURE_SCHEDULE_OK : USAC_CAPTURE_SCHEDULE_INVALID;
    }
    if (lease_sequence < schedule->lease_sequence) {
        return USAC_CAPTURE_SCHEDULE_INVALID;
    }
    schedule->lease_sequence = lease_sequence;
    schedule->last_lease_timeout_ms = lease_timeout_ms;
    schedule->lease_remaining_us = (uint32_t)lease_timeout_ms * 1000ul;
    return USAC_CAPTURE_SCHEDULE_OK;
}

usac_capture_schedule_result_t usac_capture_schedule_advance(
    usac_capture_schedule_t *schedule,
    uint32_t elapsed_us)
{
    uint32_t periods;

    if (schedule->active == 0u) {
        return USAC_CAPTURE_SCHEDULE_INVALID;
    }
    if (elapsed_us >= schedule->lease_remaining_us) {
        usac_capture_schedule_init(schedule);
        return USAC_CAPTURE_SCHEDULE_EXPIRED;
    }
    schedule->lease_remaining_us -= elapsed_us;
    if (elapsed_us < schedule->until_due_us) {
        schedule->until_due_us -= elapsed_us;
        return USAC_CAPTURE_SCHEDULE_OK;
    }

    elapsed_us -= schedule->until_due_us;
    periods = 1ul + (elapsed_us / schedule->period_us);
    schedule->until_due_us = schedule->period_us -
        (elapsed_us % schedule->period_us);
    if (schedule->due != 0u) {
        schedule->missed_count += periods;
    } else {
        schedule->due = 1u;
        schedule->missed_count += periods - 1ul;
    }
    return USAC_CAPTURE_SCHEDULE_OK;
}

uint8_t usac_capture_schedule_claim_due(usac_capture_schedule_t *schedule)
{
    if ((schedule->active == 0u) || (schedule->due == 0u)) {
        return 0u;
    }
    schedule->due = 0u;
    ++schedule->completed_count;
    if ((schedule->capture_limit != 0ul) &&
        (schedule->completed_count >= schedule->capture_limit)) {
        schedule->active = 0u;
        schedule->lease_sequence = 0ul;
        schedule->last_lease_timeout_ms = 0u;
        schedule->lease_remaining_us = 0ul;
    }
    return 1u;
}

usac_capture_schedule_result_t usac_capture_schedule_stop(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16])
{
    if ((schedule->active != 0u) &&
        (ids_equal(schedule->schedule_id, schedule_id) == 0u)) {
        return USAC_CAPTURE_SCHEDULE_CONFLICT;
    }
    usac_capture_schedule_init(schedule);
    return USAC_CAPTURE_SCHEDULE_OK;
}

uint16_t usac_capture_schedule_lease_remaining_ms(
    const usac_capture_schedule_t *schedule)
{
    if (schedule->active == 0u) {
        return 0u;
    }
    return (uint16_t)(schedule->lease_remaining_us / 1000ul);
}

uint16_t usac_sync_timeout_guarded_quanta(uint32_t timeout_ms)
{
    uint32_t quanta;

    if (timeout_ms == 0ul) {
        return 0u;
    }
    quanta = (timeout_ms * USAC_ACLK_HZ +
              (1000ul * USAC_ACLK_QUANTUM_TICKS) - 1ul) /
             (1000ul * USAC_ACLK_QUANTUM_TICKS);
    return (uint16_t)(quanta + 1ul);
}
