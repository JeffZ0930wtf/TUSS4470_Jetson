#include <stdint.h>
#include <msp430.h>

#include "usac_capture_schedule.h"

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

static int test_periodic_schedule_is_bounded_and_finite(void)
{
    uint8_t schedule_id[16] = {1u};
    usac_capture_schedule_t schedule;

    usac_capture_schedule_init(&schedule);
    CHECK(usac_capture_schedule_start(
              &schedule, schedule_id, 99999ul, 2ul, 3000u) ==
          USAC_CAPTURE_SCHEDULE_INVALID);
    CHECK(usac_capture_schedule_start(
              &schedule, schedule_id, 100000ul, 2ul, 3000u) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_advance(&schedule, 99999ul) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_claim_due(&schedule) == 0u);
    CHECK(usac_capture_schedule_advance(&schedule, 1ul) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_claim_due(&schedule) == 1u);
    CHECK(usac_capture_schedule_advance(&schedule, 200000ul) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(schedule.missed_count == 1ul);
    CHECK(usac_capture_schedule_claim_due(&schedule) == 1u);
    CHECK(schedule.active == 0u);
    return 0;
}

static int test_lease_expires_and_renewal_is_monotonic(void)
{
    uint8_t schedule_id[16] = {2u};
    uint8_t other_id[16] = {3u};
    usac_capture_schedule_t schedule;

    usac_capture_schedule_init(&schedule);
    CHECK(usac_capture_schedule_start(
              &schedule, schedule_id, 100000ul, 0ul, 1000u) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_renew(
              &schedule, other_id, 1ul, 1000u) ==
          USAC_CAPTURE_SCHEDULE_CONFLICT);
    CHECK(usac_capture_schedule_renew(
              &schedule, schedule_id, 1ul, 2000u) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_renew(
              &schedule, schedule_id, 1ul, 2000u) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_lease_remaining_ms(&schedule) == 2000u);
    CHECK(usac_capture_schedule_advance(&schedule, 1999999ul) ==
          USAC_CAPTURE_SCHEDULE_OK);
    CHECK(usac_capture_schedule_advance(&schedule, 1ul) ==
          USAC_CAPTURE_SCHEDULE_EXPIRED);
    CHECK(schedule.active == 0u);
    return 0;
}

static int test_slave_sync_timeout_never_expires_early(void)
{
    /* The wait can start immediately before an ACLK compare interrupt.  One
     * guard quantum therefore follows the ceiling conversion so a requested
     * duration is never shortened by the compare phase. */
    CHECK(usac_sync_timeout_guarded_quanta(0ul) == 0u);
    CHECK(usac_sync_timeout_guarded_quanta(1ul) == 2u);
    CHECK(usac_sync_timeout_guarded_quanta(1000ul) == 104u);
    CHECK(usac_sync_timeout_guarded_quanta(5000ul) == 513u);
    CHECK(usac_sync_timeout_guarded_quanta(60000ul) == 6145u);
    return 0;
}

volatile int g_usac_test_result = -1;

void __attribute__((noinline)) usac_test_complete(void)
{
    __no_operation();
    for (;;) {
    }
}

int main(void)
{
    int result = test_periodic_schedule_is_bounded_and_finite();
    if (result == 0) {
        result = test_lease_expires_and_renewal_is_monotonic();
    }
    if (result == 0) {
        result = test_slave_sync_timeout_never_expires_early();
    }
    g_usac_test_result = result;
    usac_test_complete();
    return 0;
}
