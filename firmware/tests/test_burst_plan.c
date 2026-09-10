#include <stdint.h>
#include <msp430.h>

#include "usac_burst_plan.h"

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

static int test_all_io_modes_are_finite_and_explicit(void)
{
    usac_burst_plan_t plan;

    CHECK(usac_burst_plan_build(0u, 1u, 50u, 1000ul, &plan) == 1u);
    CHECK(plan.action_flags ==
        (USAC_BURST_USE_CMD_TRIGGER | USAC_BURST_USE_IO2_TIMER));
    CHECK(usac_burst_plan_build(1u, 2u, 50u, 1000ul, &plan) == 1u);
    CHECK(plan.action_flags ==
        (USAC_BURST_USE_IO1_ENABLE | USAC_BURST_USE_IO2_TIMER));
    CHECK(usac_burst_plan_build(2u, 63u, 24u, 2000ul, &plan) == 1u);
    CHECK((plan.action_flags & USAC_BURST_NONOVERLAP) != 0u);
    CHECK(plan.io1_fall_tick == 11u && plan.io2_rise_tick == 13u);
    CHECK(usac_burst_plan_build(3u, 1u, 800u, 1000ul, &plan) == 1u);
    CHECK(plan.action_flags == USAC_BURST_USE_IO2_TIMER);
    return 0;
}

static int test_unsafe_or_nonfinite_requests_are_rejected(void)
{
    usac_burst_plan_t plan;

    CHECK(usac_burst_plan_build(4u, 1u, 50u, 1000ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 0u, 50u, 1000ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 64u, 50u, 10000ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 1u, 23u, 1000ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 1u, 801u, 1000ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 2u, 50u, 100ul, &plan) == 0u);
    CHECK(usac_burst_plan_build(3u, 2u, 50u, 101ul, &plan) == 1u);
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
    int result = test_all_io_modes_are_finite_and_explicit();
    if (result == 0) {
        result = test_unsafe_or_nonfinite_requests_are_rejected();
    }
    g_usac_test_result = result;
    usac_test_complete();
    return 0;
}
