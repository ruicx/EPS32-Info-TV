#include "protocol/framing.h"

#include <array>
#include <cstring>

#include "test_support.h"

/** Verify an independent CRC vector, byte values, corruption, and recovery. */
int main() {
  const char* vector = "123456789";
  CHECK(info_tv::crc32(reinterpret_cast<const uint8_t*>(vector), 9) == 0xcbf43926U);
  std::array<uint8_t, 4096> payload{};
  for (size_t index = 0; index < payload.size(); ++index) payload[index] = index % 256;
  std::array<uint8_t, 4128> frame{};
  const auto size = info_tv::encodeFrame(payload.data(), payload.size(), frame.data(), frame.size());
  CHECK(size > payload.size());
  info_tv::FrameDecoder decoder;
  int frames = 0;
  for (size_t index = 0; index < size; ++index) if (decoder.feed(frame[index])) ++frames;
  CHECK(frames == 1 && decoder.size() == payload.size());
  CHECK(!std::memcmp(decoder.data(), payload.data(), payload.size()));
  frame[3] ^= 0x20;
  for (size_t index = 0; index < size; ++index) CHECK(!decoder.feed(frame[index]));
  for (int index = 0; index < 5000; ++index) CHECK(!decoder.feed(1));
  CHECK(!decoder.feed(0));
  frame[3] ^= 0x20;
  frames = 0;
  for (size_t index = 0; index < size; ++index) if (decoder.feed(frame[index])) ++frames;
  CHECK(frames == 1);
  CHECK(info_tv::encodeFrame(payload.data(), 4097, frame.data(), frame.size()) == 0);
}
