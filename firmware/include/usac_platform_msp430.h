#ifndef USAC_PLATFORM_MSP430_H
#define USAC_PLATFORM_MSP430_H

#include <stdint.h>

#include "usac_m2_core.h"

void usac_platform_enter_reset_safe(void);
void usac_platform_spi_init(void);
uint8_t usac_platform_stage_timing(
    const usac_m2_timing_stage_t *requested,
    usac_m2_timing_stage_t *readback);
uint8_t usac_platform_tuss_read(void *context, uint8_t address, uint8_t *value);
uint8_t usac_platform_tuss_write(void *context, uint8_t address, uint8_t value);
void usac_platform_delay_1ms(void *context);

#endif
