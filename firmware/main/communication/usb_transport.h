#pragma once

#include <cstddef>
#include <cstdint>

namespace info_tv {
/** Own the protocol-only native USB Serial/JTAG driver. */
class UsbTransport {
 public:
  /** Install bounded transmit and receive buffers. */
  void initialize();
  /** Read a stream chunk with a short timeout. */
  size_t read(uint8_t* data, size_t capacity);
  /** Write a complete frame or report a bounded timeout. */
  bool write(const uint8_t* data, size_t size);
  /** Allow queued feedback to reach USB before the controller is powered down. */
  void flush();
};
}  // namespace info_tv
