#include "communication/usb_transport.h"

#include "driver/usb_serial_jtag.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"

namespace info_tv {
void UsbTransport::initialize() {
  usb_serial_jtag_driver_config_t config{};
  config.rx_buffer_size = 8192;
  config.tx_buffer_size = 8192;
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
}

size_t UsbTransport::read(uint8_t* data, size_t capacity) {
  const int count = usb_serial_jtag_read_bytes(data, capacity, pdMS_TO_TICKS(10));
  return count > 0 ? static_cast<size_t>(count) : 0;
}

bool UsbTransport::write(const uint8_t* data, size_t size) {
  size_t offset = 0;
  while (offset < size) {
    const int count = usb_serial_jtag_write_bytes(data + offset, size - offset, pdMS_TO_TICKS(100));
    if (count <= 0) return false;
    offset += count;
  }
  return true;
}
}  // namespace info_tv
