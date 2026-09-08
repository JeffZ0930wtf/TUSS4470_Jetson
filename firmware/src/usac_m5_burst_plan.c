#include "usac_m5_burst_plan.h"

uint8_t usac_m5_burst_plan_build(
    uint8_t io_mode,
    uint8_t pulse_count,
    uint16_t period_ticks,
    uint32_t posttrigger_ticks,
    usac_m5_burst_plan_t *plan)
{
    uint32_t duration_ticks;
    uint16_t half_period;

    if ((plan == 0) || (io_mode > 3u) || (pulse_count == 0u) ||
        (pulse_count > 63u) || (period_ticks < 24u) ||
        (period_ticks > 800u)) {
        return 0u;
    }
    duration_ticks = (uint32_t)pulse_count * period_ticks;
    if (duration_ticks >= posttrigger_ticks) {
        return 0u;
    }

    plan->io_mode = io_mode;
    plan->pulse_count = pulse_count;
    plan->period_ticks = period_ticks;
    plan->io1_fall_tick = 0u;
    plan->io2_rise_tick = 0u;
    plan->action_flags = USAC_M5_BURST_USE_IO2_TIMER;
    if (io_mode == 0u) {
        plan->action_flags |= USAC_M5_BURST_USE_CMD_TRIGGER;
    } else if (io_mode == 1u) {
        plan->action_flags |= USAC_M5_BURST_USE_IO1_ENABLE;
    } else if (io_mode == 2u) {
        /* TA2.1 falls before TA2.2 rises.  The two-tick both-low interval
         * prevents a both-high overlap at the mid-period commutation. */
        half_period = (uint16_t)(period_ticks / 2u);
        plan->io1_fall_tick = (uint16_t)(half_period - 1u);
        plan->io2_rise_tick = (uint16_t)(half_period + 1u);
        plan->action_flags |= USAC_M5_BURST_USE_IO1_TIMER |
            USAC_M5_BURST_NONOVERLAP;
    }
    return 1u;
}
