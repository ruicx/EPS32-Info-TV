#pragma once

#include <cstddef>
#include <cstdint>

#include "protocol/model.h"

namespace info_tv {
/** Decode one bounded Protobuf envelope into owned static storage. */
bool decodeEnvelope(const uint8_t* data, size_t size, Envelope& output);
/** Encode a complete envelope, returning zero on buffer exhaustion. */
size_t encodeEnvelope(const Envelope& envelope, uint8_t* data, size_t capacity);
/** Return nullptr for valid display commands, otherwise a rejection reason. */
const char* validateCommand(const Envelope& envelope);
/** Compare supported card content semantically, independent of wire encoding. */
bool sameCard(const Card& left, const Card& right);
}  // namespace info_tv
