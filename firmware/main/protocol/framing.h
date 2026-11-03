#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace info_tv {
constexpr size_t kMaxPayload = 4096;
constexpr size_t kMaxEncoded = 4120;

/** Compute CRC32-IEEE compatible with Python zlib.crc32. */
uint32_t crc32(const uint8_t* data, size_t size);
/** Encode zero-delimited COBS payload plus little-endian CRC; zero on failure. */
size_t encodeFrame(const uint8_t* payload, size_t size, uint8_t* output, size_t capacity);

/** Decode an arbitrary byte stream into bounded frames with delimiter recovery. */
class FrameDecoder {
 public:
  /** Feed one byte; return true when one verified payload is ready. */
  bool feed(uint8_t value);
  /** Clear partial bytes at a connection boundary. */
  void reset();
  /** Return the last verified payload until another complete frame arrives. */
  const uint8_t* data() const { return decoded_.data(); }
  /** Return the verified payload length. */
  size_t size() const { return decodedSize_; }

 private:
  /** Decode and validate the accumulated delimiter-free COBS body. */
  bool finish();
  std::array<uint8_t, kMaxEncoded> encoded_{};
  std::array<uint8_t, kMaxPayload + 4> decoded_{};
  size_t used_ = 0;
  size_t decodedSize_ = 0;
  bool discard_ = false;
};
}  // namespace info_tv
