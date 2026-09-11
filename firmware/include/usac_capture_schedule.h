/* V1 periodic scheduler and lease fail-safe. The module is independent from
 * timers and USB so the exact state transitions can be verified in the MSP430
 * simulator before the hardware-specific clock source is accepted. */
#ifndef USAC_CAPTURE_SCHEDULE_H
#define USAC_CAPTURE_SCHEDULE_H

#include <stdint.h>

#define USAC_CAPTURE_MIN_PERIOD_US 100000ul
#define USAC_CAPTURE_MIN_LEASE_MS 1000u
#define USAC_CAPTURE_MAX_LEASE_MS 10000u
#define USAC_ACLK_HZ 32768ul
#define USAC_ACLK_QUANTUM_TICKS 320u
#define USAC_ACLK_QUANTUM_US 9766ul

typedef enum {
    USAC_CAPTURE_SCHEDULE_OK = 0,
    USAC_CAPTURE_SCHEDULE_INVALID = 1,
    USAC_CAPTURE_SCHEDULE_CONFLICT = 2,
    USAC_CAPTURE_SCHEDULE_EXPIRED = 3
} usac_capture_schedule_result_t;

typedef struct {
    uint8_t active;
    uint8_t due;
    uint8_t schedule_id[16];
    uint32_t period_us;
    uint32_t until_due_us;
    uint32_t capture_limit;
    uint32_t completed_count;
    uint32_t missed_count;
    uint32_t lease_sequence;
    uint16_t last_lease_timeout_ms;
    uint32_t lease_remaining_us;
} usac_capture_schedule_t;

void usac_capture_schedule_init(usac_capture_schedule_t *schedule);
usac_capture_schedule_result_t usac_capture_schedule_start(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16],
    uint32_t period_us,
    uint32_t capture_count,
    uint16_t lease_timeout_ms);
usac_capture_schedule_result_t usac_capture_schedule_renew(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16],
    uint32_t lease_sequence,
    uint16_t lease_timeout_ms);
usac_capture_schedule_result_t usac_capture_schedule_advance(
    usac_capture_schedule_t *schedule,
    uint32_t elapsed_us);
uint8_t usac_capture_schedule_claim_due(usac_capture_schedule_t *schedule);
usac_capture_schedule_result_t usac_capture_schedule_stop(
    usac_capture_schedule_t *schedule,
    const uint8_t schedule_id[16]);
uint16_t usac_capture_schedule_lease_remaining_ms(
    const usac_capture_schedule_t *schedule);

/* Convert a slave-sync timeout to the existing ACLK compare cadence.  The
 * extra quantum covers the unknown phase of the first compare interrupt, so
 * the physical wait cannot finish before the requested millisecond value. */
uint16_t usac_sync_timeout_guarded_quanta(uint32_t timeout_ms);

#endif
