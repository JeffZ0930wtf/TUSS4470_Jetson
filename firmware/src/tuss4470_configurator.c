/* Applies a validated TUSS4470 profile through an injected SPI bus and closes
 * every error path by attempting Standby/Hi-Z. Register ordering is a safety
 * property: transient trigger fields are cleared before operational values. */
#include "tuss4470_configurator.h"

#define TUSS4470_REG_DEV_CTRL_3 0x14u
#define TUSS4470_REG_VDRV_CTRL 0x16u
#define TUSS4470_REG_BURST_PULSE 0x1Au
#define TUSS4470_REG_TOF_CONFIG 0x1Bu
#define TUSS4470_REG_DEV_STAT 0x1Cu
#define TUSS4470_REG_DEVICE_ID 0x1Du
#define TUSS4470_REG_REV_ID 0x1Eu

static tuss4470_config_result_t read_register(
    const tuss4470_bus_t *bus,
    uint8_t address,
    uint8_t *value)
{
    if ((bus == 0) || (bus->read == 0) ||
        (bus->read(bus->context, address, value) == 0u)) {
        return TUSS4470_CONFIG_BUS;
    }
    return TUSS4470_CONFIG_OK;
}

static tuss4470_config_result_t write_verify(
    const tuss4470_bus_t *bus,
    uint8_t address,
    uint8_t value)
{
    uint8_t readback;

    if ((bus == 0) || (bus->write == 0) ||
        (bus->write(bus->context, address, value) == 0u)) {
        return TUSS4470_CONFIG_BUS;
    }
    if (read_register(bus, address, &readback) != TUSS4470_CONFIG_OK) {
        return TUSS4470_CONFIG_BUS;
    }
    if (readback != value) {
        return TUSS4470_CONFIG_READBACK;
    }
    return TUSS4470_CONFIG_OK;
}

static tuss4470_config_result_t apply_safe_start(
    const tuss4470_bus_t *bus)
{
    static const tuss4470_register_pair_t safe_start[] = {
        {TUSS4470_REG_BURST_PULSE, 0x01u},
        {TUSS4470_REG_VDRV_CTRL, 0x20u},
        {TUSS4470_REG_TOF_CONFIG, 0x00u},
        {TUSS4470_REG_DEV_CTRL_3, 0x03u}
    };
    uint8_t index;
    tuss4470_config_result_t result;

    for (index = 0u;
         index < (uint8_t)(sizeof(safe_start) / sizeof(safe_start[0]));
         ++index) {
        result = write_verify(
            bus,
            safe_start[index].address,
            safe_start[index].value);
        if (result != TUSS4470_CONFIG_OK) {
            return result;
        }
    }
    return TUSS4470_CONFIG_OK;
}

tuss4470_config_result_t tuss4470_force_safe(const tuss4470_bus_t *bus)
{
    tuss4470_config_result_t tof_result;
    tuss4470_config_result_t vdrv_result;
    tuss4470_config_result_t standby_result;

    /* Attempt every safe transition even if an earlier bus operation fails.
     * Standby prevents an IO2 edge during an MCU reset from arming IO_MODE 3.
     */
    tof_result = write_verify(bus, TUSS4470_REG_TOF_CONFIG, 0x00u);
    vdrv_result = write_verify(bus, TUSS4470_REG_VDRV_CTRL, 0x20u);
    standby_result = write_verify(bus, TUSS4470_REG_TOF_CONFIG, 0x40u);
    if (tof_result != TUSS4470_CONFIG_OK) {
        return tof_result;
    }
    if (vdrv_result != TUSS4470_CONFIG_OK) {
        return vdrv_result;
    }
    return standby_result;
}

tuss4470_config_result_t tuss4470_enter_low_power(
    const tuss4470_bus_t *bus,
    tuss4470_low_power_state_t state)
{
    tuss4470_config_result_t result;
    uint8_t tof_value;

    if ((state != TUSS4470_LOW_POWER_STANDBY) &&
        (state != TUSS4470_LOW_POWER_SLEEP)) {
        return TUSS4470_CONFIG_INVALID_PROFILE;
    }
    result = tuss4470_force_safe(bus);
    if (result != TUSS4470_CONFIG_OK) {
        return result;
    }
    tof_value = (state == TUSS4470_LOW_POWER_STANDBY) ? 0x40u : 0x80u;
    return write_verify(bus, TUSS4470_REG_TOF_CONFIG, tof_value);
}

static tuss4470_config_result_t fail_safe_result(
    const tuss4470_bus_t *bus,
    tuss4470_config_result_t result)
{
    (void)tuss4470_force_safe(bus);
    return result;
}

tuss4470_config_result_t tuss4470_configure_firmware(
    const tuss4470_bus_t *bus,
    const tuss4470_profile_t *profile,
    uint16_t vdrv_ready_poll_limit,
    tuss4470_config_report_t *report)
{
    uint8_t index;
    uint8_t target_vdrv;
    uint8_t target_tof;
    uint8_t requires_vdrv_ready;
    uint16_t poll;
    tuss4470_config_result_t result;

    if ((profile == 0) || (report == 0) ||
        (tuss4470_profile_validate(profile) != TUSS4470_PROFILE_OK)) {
        return TUSS4470_CONFIG_INVALID_PROFILE;
    }
    target_vdrv = profile->registers[5].value;
    target_tof = profile->registers[9].value;
    requires_vdrv_ready = (uint8_t)(
        ((target_vdrv & 0x20u) == 0u) && ((target_tof & 0x02u) != 0u));
    result = read_register(bus, TUSS4470_REG_DEVICE_ID, &report->device_id);
    if (result != TUSS4470_CONFIG_OK) {
        return result;
    }
    result = read_register(bus, TUSS4470_REG_REV_ID, &report->revision_id);
    if (result != TUSS4470_CONFIG_OK) {
        return result;
    }
    if ((report->device_id != TUSS4470_DEVICE_ID_VALUE) ||
        (report->revision_id != TUSS4470_REVISION_ID_VALUE)) {
        return TUSS4470_CONFIG_IDENTITY;
    }

    result = apply_safe_start(bus);
    if (result != TUSS4470_CONFIG_OK) {
        return fail_safe_result(bus, result);
    }

    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        if ((profile->registers[index].address == TUSS4470_REG_VDRV_CTRL) ||
            (profile->registers[index].address == TUSS4470_REG_TOF_CONFIG)) {
            continue;
        }
        result = write_verify(
            bus,
            profile->registers[index].address,
            profile->registers[index].value);
        if (result != TUSS4470_CONFIG_OK) {
            return fail_safe_result(bus, result);
        }
    }

    result = write_verify(bus, TUSS4470_REG_VDRV_CTRL, target_vdrv);
    if (result != TUSS4470_CONFIG_OK) {
        return fail_safe_result(bus, result);
    }
    result = write_verify(bus, TUSS4470_REG_TOF_CONFIG, target_tof);
    if (result != TUSS4470_CONFIG_OK) {
        return fail_safe_result(bus, result);
    }
    if ((requires_vdrv_ready != 0u) &&
        ((bus == 0) || (bus->delay_1ms == 0))) {
        return fail_safe_result(bus, TUSS4470_CONFIG_BUS);
    }

    for (poll = 0u;
         poll < (requires_vdrv_ready ? vdrv_ready_poll_limit : 1u);
         ++poll) {
        if (requires_vdrv_ready != 0u) {
            bus->delay_1ms(bus->context);
        }
        result = read_register(bus, TUSS4470_REG_DEV_STAT, &report->dev_stat);
        if (result != TUSS4470_CONFIG_OK) {
            return fail_safe_result(bus, result);
        }
        if ((report->dev_stat & TUSS4470_DEV_STAT_FAULT_MASK) != 0u) {
            return fail_safe_result(bus, TUSS4470_CONFIG_DRIVER_FAULT);
        }
        if (requires_vdrv_ready == 0u) {
            return TUSS4470_CONFIG_OK;
        }
        if ((report->dev_stat & TUSS4470_DEV_STAT_VDRV_READY) != 0u) {
            return TUSS4470_CONFIG_OK;
        }
    }
    return fail_safe_result(bus, TUSS4470_CONFIG_VDRV_TIMEOUT);
}
