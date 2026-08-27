/* Adapts TI's USB event callbacks to the M2 DTR/session state. Callbacks only
 * signal the main loop or end a session; they never configure or trigger the
 * ultrasonic transmitter from interrupt context. */
#include <stdint.h>

#include "driverlib.h"
#include "USB_config/descriptors.h"
#include "USB_API/USB_Common/device.h"
#include "USB_API/USB_Common/defMSP430USB.h"
#include "USB_API/USB_Common/usb.h"
#include "USB_API/USB_CDC_API/UsbCdc.h"

#include "usac_dtr_gate.h"

volatile uint8_t g_usac_usb_data_pending = 0u;
volatile uint8_t g_usac_usb_send_complete = 0u;
volatile uint8_t g_usac_dtr_present = 0u;
volatile uint8_t g_usac_dtr_session_ready = 0u;
static usac_dtr_gate_t dtr_gate;

static void reset_dtr_session(void)
{
    usac_dtr_gate_reset(&dtr_gate);
    g_usac_dtr_present = 0u;
    g_usac_dtr_session_ready = 0u;
    g_usac_usb_send_complete = 0u;
}

uint8_t USB_handleClockEvent(void)
{
    return TRUE;
}

uint8_t USB_handleVbusOnEvent(void)
{
    if (USB_enable() == USB_SUCCEED) {
        USB_reset();
        USB_connect();
    }
    return TRUE;
}

uint8_t USB_handleVbusOffEvent(void)
{
    reset_dtr_session();
    g_usac_usb_data_pending = 0u;
    return TRUE;
}

uint8_t USB_handleResetEvent(void)
{
    reset_dtr_session();
    g_usac_usb_data_pending = 0u;
    return TRUE;
}

uint8_t USB_handleSuspendEvent(void)
{
    return TRUE;
}

uint8_t USB_handleResumeEvent(void)
{
    return TRUE;
}

uint8_t USB_handleEnumerationCompleteEvent(void)
{
    reset_dtr_session();
    return TRUE;
}

uint8_t USBCDC_handleDataReceived(uint8_t intfNum)
{
    (void)intfNum;
    g_usac_usb_data_pending = 1u;
    return TRUE;
}

uint8_t USBCDC_handleSendCompleted(uint8_t intfNum)
{
    (void)intfNum;
    g_usac_usb_send_complete = 1u;
    return TRUE;
}

uint8_t USBCDC_handleReceiveCompleted(uint8_t intfNum)
{
    (void)intfNum;
    g_usac_usb_data_pending = 1u;
    return TRUE;
}

uint8_t USBCDC_handleSetLineCoding(uint8_t intfNum, uint32_t baudrate)
{
    (void)intfNum;
    (void)baudrate;
    return FALSE;
}

uint8_t USBCDC_handleSetControlLineState(uint8_t intfNum, uint8_t lineState)
{
    (void)intfNum;
    g_usac_dtr_present = (uint8_t)((lineState & BIT0) != 0u);
    usac_dtr_gate_update(&dtr_gate, g_usac_dtr_present);
    g_usac_dtr_session_ready = usac_dtr_gate_ready(&dtr_gate);
    return TRUE;
}
