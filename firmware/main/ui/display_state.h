#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "protocol/model.h"
#include "config.h"

namespace info_tv {
/** Retain one current card and its actual presentation correlation. */
struct CardSlot {
  Card card{};
  char messageId[37]{};
  bool presented = false;
};

/** Own a pending notification, original identity, and local validity deadline. */
struct NotificationSlot {
  Notification notification{};
  char messageId[37]{};
  char sessionId[37]{};
  uint64_t expiresAtMs = 0;
  bool presented = false;
  bool weatherAlert = false;
};

/** Own bounded overview and notification state exclusively on the UI task. */
class DisplayState {
 public:
  /** Atomically replace an already-validated overview, resetting a new session. */
  void applySnapshot(const Envelope& envelope);
  /** Return whether a related task card remains in the current overview. */
  bool hasCard(const char* cardId) const;
  /** Apply a newer card; return false for conflicts, stale data, or capacity. */
  bool upsertCard(const Card& card, const char* messageId);
  /** Admit a notification or recognize its original event as already known. */
  bool enqueueNotification(const Envelope& envelope, uint64_t receivedAtMs, uint64_t nowMs);
  /** Select by priority, preferring weather then oldest task notice, consuming it. */
  bool popNotification(uint64_t nowMs, NotificationSlot& output, bool importantOnly = false);
  /** Remove a withdrawn/replaced weather notification without touching task notices. */
  void clearWeatherNotification();
  /** Remove queued attention notifications for the specified card. */
  void clearCardAttentionNotifications(const char* cardId);
  /** Replace the reserved weather notification using an already-validated alert. */
  void notifyWeatherAlert(const Envelope& envelope, uint64_t receivedAtMs);
  /** Return whether an operation already reached UI acceptance. */
  bool accepted(const char* messageId) const;
  /** Retain a bounded accepted operation identity. */
  void remember(const char* messageId);
  /** Return the active service-session identity. */
  const char* sessionId() const { return sessionId_; }
  /** Return the number of current overview cards. */
  size_t cardCount() const { return cardCount_; }
  /** Access a current card by its validated overview index. */
  CardSlot& card(size_t index) { return cards_[index]; }

 private:
  /** Remove expired pending notifications without replaying them. */
  void expire(uint64_t nowMs);
  char sessionId_[37]{};
  std::array<CardSlot, policy::kMaxCards> cards_{};
  size_t cardCount_ = 0;
  std::array<NotificationSlot, 9> notifications_{};
  size_t notificationCount_ = 0;
  std::array<std::array<char, 37>, 64> accepted_{};
  size_t acceptedIndex_ = 0;
  std::array<std::array<char, 37>, 64> events_{};
  size_t eventIndex_ = 0;
};
}  // namespace info_tv
