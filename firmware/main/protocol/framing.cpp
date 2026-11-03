#include "protocol/framing.h"

#include <cstring>

namespace info_tv {
uint32_t crc32(const uint8_t* data, size_t size) {
  uint32_t value = 0xffffffffU;
  for (size_t index = 0; index < size; ++index) {
    value ^= data[index];
    for (unsigned bit = 0; bit < 8; ++bit)
      value = (value >> 1) ^ (0xedb88320U & (0U - (value & 1U)));
  }
  return ~value;
}

size_t encodeFrame(const uint8_t* payload, size_t size, uint8_t* output, size_t capacity) {
  if (!size || size > kMaxPayload || capacity < size + size / 254 + 8) return 0;
  const uint32_t checksum = crc32(payload, size);
  size_t used = 2;
  size_t codeIndex = 1;
  uint8_t code = 1;
  output[0] = 0;
  for (size_t index = 0; index < size + 4; ++index) {
    const uint8_t value = index < size ? payload[index] : static_cast<uint8_t>(checksum >> (8 * (index - size)));
    if (!value) {
      output[codeIndex] = code;
      codeIndex = used++;
      code = 1;
    } else {
      output[used++] = value;
      if (++code == 255) {
        output[codeIndex] = code;
        codeIndex = used++;
        code = 1;
      }
    }
  }
  output[codeIndex] = code;
  output[used++] = 0;
  return used;
}

void FrameDecoder::reset() {
  used_ = 0;
  discard_ = false;
}

bool FrameDecoder::feed(uint8_t value) {
  if (!value) {
    const bool valid = used_ && !discard_ && finish();
    reset();
    return valid;
  }
  if (!discard_) {
    if (used_ == encoded_.size()) {
      discard_ = true;
      used_ = 0;
    } else {
      encoded_[used_++] = value;
    }
  }
  return false;
}

bool FrameDecoder::finish() {
  size_t input = 0;
  size_t output = 0;
  while (input < used_) {
    const uint8_t code = encoded_[input++];
    if (!code || input + code - 1 > used_ || output + code - 1 > decoded_.size()) return false;
    std::memcpy(decoded_.data() + output, encoded_.data() + input, code - 1);
    input += code - 1;
    output += code - 1;
    if (code != 255 && input < used_) {
      if (output == decoded_.size()) return false;
      decoded_[output++] = 0;
    }
  }
  if (output <= 4) return false;
  decodedSize_ = output - 4;
  uint32_t expected = 0;
  for (unsigned index = 0; index < 4; ++index)
    expected |= static_cast<uint32_t>(decoded_[decodedSize_ + index]) << (8 * index);
  return crc32(decoded_.data(), decodedSize_) == expected;
}
}  // namespace info_tv
