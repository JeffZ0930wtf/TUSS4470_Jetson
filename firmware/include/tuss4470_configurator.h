/* Public contract for safe, bus-injected TUSS4470 configuration. Callers
 * receive explicit identity/readback/fault results; failure paths may perform
 * additional writes to return the device to Standby/Hi-Z. */
#ifndef TUSS4470_CONFIGURATOR_H
#define TUSS4470_CONFIGURATOR_H

#include <stdint.h>

#include "tuss4470_profile.h"

#define TUSS4470_DEVICE_ID_VALUE 0xB9u
#define TUSS4470_REVISION_ID_VALUE 0x02u
#define TUSS4470_DEV_STAT_VDRV_READY 0x08u
#define TUSS4470_DEV_STAT_FAULT_MASK 0x07u

typedef uint8_t (*tuss4470_read_fn)(
    void *context,
    uint8_t address,
    uint8_t *value);
typedef uint8_t (*tuss4470_write_fn)(
    void *context,
    uint8_t address,
    uint8_t value);
typedef void (*tuss4470_delay_1ms_fn)(void *context);

typedef struct {
    void *context;
    tuss4470_read_fn read;
    tuss4470_write_fn write;
    tuss4470_delay_1ms_fn delay_1ms;
} tuss4470_bus_t;

typedef struct {
    uint8_t device_id;
    uint8_t revision_id;
    uint8_t dev_stat;
} tuss4470_config_report_t;

typedef enum {
    TUSS4470_CONFIG_OK = 0,
    TUSS4470_CONFIG_INVALID_PROFILE = 1,
    TUSS4470_CONFIG_BUS = 2,
    TUSS4470_CONFIG_IDENTITY = 3,
    TUSS4470_CONFIG_READBACK = 4,
    TUSS4470_CONFIG_DRIVER_FAULT = 5,
    TUSS4470_CONFIG_VDRV_TIMEOUT = 6
} tuss4470_config_result_t;

typedef enum {
    TUSS4470_LOW_POWER_STANDBY = 1,
    TUSS4470_LOW_POWER_SLEEP = 2
} tuss4470_low_power_state_t;

tuss4470_config_result_t tuss4470_configure_m2(
    const tuss4470_bus_t *bus,
    const tuss4470_profile_t *profile,
    uint16_t vdrv_ready_poll_limit,
    tuss4470_config_report_t *report);
/* Best-effort safety transition used during boot, session end, and failures. */
tuss4470_config_result_t tuss4470_force_safe(const tuss4470_bus_t *bus);
tuss4470_config_result_t tuss4470_enter_low_power(
    const tuss4470_bus_t *bus,
    tuss4470_low_power_state_t state);

#endif
