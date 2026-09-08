/* Pure M5 Burst planning.  This module validates a requested finite Burst and
 * describes which TUSS4470 control path the MSP430 platform must drive; it
 * never touches GPIO, SPI, timers, or the transducer. */
#ifndef USAC_M5_BURST_PLAN_H
#define USAC_M5_BURST_PLAN_H

#include <stdint.h>

#define USAC_M5_BURST_USE_CMD_TRIGGER 0x01u
#define USAC_M5_BURST_USE_IO1_ENABLE 0x02u
#define USAC_M5_BURST_USE_IO1_TIMER 0x04u
#define USAC_M5_BURST_USE_IO2_TIMER 0x08u
#define USAC_M5_BURST_NONOVERLAP 0x10u

typedef struct {
    uint8_t io_mode;
    uint8_t pulse_count;
    uint8_t action_flags;
    uint16_t period_ticks;
    uint16_t io1_fall_tick;
    uint16_t io2_rise_tick;
} usac_m5_burst_plan_t;

/* Returns false unless the request is a finite 1..63-pulse Burst whose timer
 * activity fits entirely inside the post-trigger sample window. */
uint8_t usac_m5_burst_plan_build(
    uint8_t io_mode,
    uint8_t pulse_count,
    uint16_t period_ticks,
    uint32_t posttrigger_ticks,
    usac_m5_burst_plan_t *plan);

#endif
