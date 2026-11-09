#include "ui/presentation_controller.h"

#include <algorithm>
#include <cstring>

#include "protocol/codec.h"
#include "config.h"

namespace info_tv {
void PresentationController::identify(const Envelope& envelope, Feedback& feedback) const {
  feedback = Feedback{};
  std::strcpy(feedback.sessionId, envelope.session_id);
  std::strcpy(feedback.messageId, envelope.message_id);
}

bool PresentationController::handleCommand(const DisplayCommand& command, uint64_t nowMs, Feedback& feedback) {
  if (command.linkLost) {
    connected_ = false;
    return false;
  }
  const auto& envelope = command.envelope;
  identify(envelope, feedback);
  const char* reason = validateCommand(envelope);
  if (reason) {
    feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_INVALID;
    std::strcpy(feedback.detail, reason);
    return true;
  }
  const bool sameSession = !std::strcmp(state_.sessionId(), envelope.session_id);
  if (!sameSession && envelope.which_body != info_tv_v1_Envelope_snapshot_tag) {
    feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_INVALID;
    std::strcpy(feedback.detail, "Snapshot required for this session");
    return true;
  }
  if (envelope.which_body == info_tv_v1_Envelope_device_settings_tag) {
    // Admission is not application. The UI owner must apply PWM before replying.
    // Absolute settings can safely be reapplied when their response was lost.
    feedback.stage = info_tv_v1_AckStage_ACK_STAGE_ACCEPTED;
    feedback.brightnessPercent = envelope.body.device_settings.brightness_percent;
    return true;
  }
  if (sameSession && state_.accepted(envelope.message_id)) {
    feedback.stage = info_tv_v1_AckStage_ACK_STAGE_ACCEPTED;
    return true;
  }
  bool accepted = true;
  switch (envelope.which_body) {
    case info_tv_v1_Envelope_snapshot_tag:
      if (!sameSession) {
        hasActive_ = false;
        weatherAlert_ = {};
        alertExpiresAtMs_ = 0;
      }
      state_.applySnapshot(envelope);
      if (hasActive_ && !active_.weatherAlert && active_.notification.card_id[0] &&
          !state_.hasCard(active_.notification.card_id)) {
        hasActive_ = false;
      }
      weather_ = envelope.body.snapshot.has_weather ? envelope.body.snapshot.weather : info_tv_v1_Weather{};
      weatherExpiresAtMs_ = command.receivedAtMs + weather_.valid_for_ms;
      connected_ = true;
      pageIndex_ = 0;
      nextRotationMs_ = nowMs + policy::kRotationMs;
      break;
    case info_tv_v1_Envelope_card_upsert_tag: {
      const auto& card = envelope.body.card_upsert.card;
      accepted = state_.upsertCard(card, envelope.message_id);
      if (accepted && card.view.content.status.tone != info_tv_v1_Tone_TONE_ATTENTION) {
        state_.clearCardAttentionNotifications(card.card_id);
        if (hasActive_ && !active_.weatherAlert &&
            !std::strcmp(active_.notification.card_id, card.card_id) &&
            active_.notification.view.content.status.tone == info_tv_v1_Tone_TONE_ATTENTION) {
          hasActive_ = false;
          restoreOverview(nowMs);
        }
      }
      break;
    }
    case info_tv_v1_Envelope_notification_tag:
      accepted = state_.enqueueNotification(envelope, command.receivedAtMs, nowMs);
      break;
    case info_tv_v1_Envelope_weather_tag:
      weather_ = envelope.body.weather;
      weatherExpiresAtMs_ = command.receivedAtMs + weather_.valid_for_ms;
      break;
    case info_tv_v1_Envelope_weather_alert_tag: {
      const auto& alert = envelope.body.weather_alert;
      const bool replaceNotice = alert.notify || !alert.alert_id[0] ||
          std::strcmp(alert.alert_id, weatherAlert_.alert_id) || alert.severity != weatherAlert_.severity;
      if (replaceNotice) {
        state_.clearWeatherNotification();
        if (hasActive_ && active_.weatherAlert) {
          restoreOverview(nowMs);
          hasActive_ = false;
        }
      }
      weatherAlert_ = alert;
      alertExpiresAtMs_ = command.receivedAtMs + alert.valid_for_ms;
      if (alert.notify && nowMs < alertExpiresAtMs_)
        state_.notifyWeatherAlert(envelope, command.receivedAtMs);
      break;
    }
    default:
      accepted = false;
  }
  if (accepted) {
    state_.remember(envelope.message_id);
    feedback.stage = info_tv_v1_AckStage_ACK_STAGE_ACCEPTED;
  } else {
    feedback.error = info_tv_v1_ErrorCode_ERROR_CODE_BUSY;
    std::strcpy(feedback.detail, "Stale/conflicting content, expired notification, or capacity reached");
  }
  return true;
}

void PresentationController::orderCards() {
  for (size_t index = 0; index < state_.cardCount(); ++index) order_[index] = index;
  const auto priority = [this](size_t index) {
    const auto tone = state_.card(index).card.view.content.status.tone;
    if (tone == info_tv_v1_Tone_TONE_ATTENTION || tone == info_tv_v1_Tone_TONE_NEGATIVE) return 0;
    return tone == info_tv_v1_Tone_TONE_POSITIVE ||
        !std::strcmp(state_.card(index).card.view.content.status.text, "interrupted") ? 2 : 1;
  };
  std::sort(order_.begin(), order_.begin() + state_.cardCount(), [&](size_t left, size_t right) {
    const int a = priority(left);
    const int b = priority(right);
    return a == b ? left < right : a < b;
  });
}

void PresentationController::restoreOverview(uint64_t nowMs) {
  for (size_t index = 0; index < state_.cardCount(); ++index) {
    if (!std::strcmp(state_.card(order_[index]).card.card_id, active_.notification.card_id)) {
      pageIndex_ = index / policy::kRowsPerPage;
      break;
    }
  }
  nextRotationMs_ = nowMs + policy::kRotationMs;
}

bool PresentationController::dismissActiveNotification(uint64_t nowMs) {
  if (!hasActive_) return false;
  hasActive_ = false;
  restoreOverview(nowMs);
  return true;
}

const RenderModel& PresentationController::tick(uint64_t nowMs) {
  orderCards();
  const bool alertActive = weatherAlert_.alert_id[0] && nowMs < alertExpiresAtMs_;
  if (!alertActive) {
    state_.clearWeatherNotification();
    if (hasActive_ && active_.weatherAlert) {
      restoreOverview(nowMs);
      hasActive_ = false;
    }
  }
  if (hasActive_ && ((active_.presented && nowMs >= activeUntilMs_) ||
                     (!active_.presented && nowMs >= active_.expiresAtMs))) {
    restoreOverview(nowMs);
    hasActive_ = false;
  }
  NotificationSlot next{};
  if (hasActive_ && active_.notification.priority == info_tv_v1_Priority_PRIORITY_ORDINARY &&
      state_.popNotification(nowMs, next, true)) {
    active_ = next;
    activeUntilMs_ = 0;
  } else if (!hasActive_ && state_.popNotification(nowMs, next)) {
    active_ = next;
    hasActive_ = true;
    activeUntilMs_ = 0;
  }
  RenderModel candidate{};
  candidate.connected = connected_;
  candidate.weather = weather_;
  candidate.weatherFresh = weather_.has_temperature_c && nowMs < weatherExpiresAtMs_;
  candidate.weatherAlert = weatherAlert_;
  candidate.weatherAlertActive = alertActive;
  candidate.cardCount = state_.cardCount();
  candidate.pageCount = (state_.cardCount() + policy::kRowsPerPage - 1) / policy::kRowsPerPage;
  for (size_t index = 0; index < state_.cardCount(); ++index) {
    const auto tone = state_.card(index).card.view.content.status.tone;
    if (tone == info_tv_v1_Tone_TONE_ATTENTION || tone == info_tv_v1_Tone_TONE_NEGATIVE)
      ++candidate.attentionCount;
  }
  std::strcpy(candidate.sessionId, state_.sessionId());
  if (hasActive_) {
    candidate.kind = RenderModel::Kind::kNotification;
    candidate.view = active_.notification.view;
    candidate.weatherNotification = active_.weatherAlert;
    std::strcpy(candidate.cardId, active_.notification.card_id);
    std::strcpy(candidate.messageId, active_.messageId);
    std::strcpy(candidate.sessionId, active_.sessionId);
  } else if (state_.cardCount()) {
    if (nowMs >= nextRotationMs_) {
      pageIndex_ = (pageIndex_ + 1) % candidate.pageCount;
      nextRotationMs_ = nowMs + policy::kRotationMs;
    }
    pageIndex_ %= candidate.pageCount;
    candidate.kind = RenderModel::Kind::kOverview;
    candidate.pageIndex = pageIndex_;
    const size_t first = pageIndex_ * policy::kRowsPerPage;
    candidate.rowCount = std::min(policy::kRowsPerPage, state_.cardCount() - first);
    for (size_t row = 0; row < candidate.rowCount; ++row) {
      const auto& slot = state_.card(order_[first + row]);
      candidate.rows[row].card = slot.card;
      std::strcpy(candidate.rows[row].messageId, slot.messageId);
    }
  }
  bool changed = render_.generation == 0 || candidate.kind != render_.kind ||
      candidate.connected != render_.connected || candidate.pageIndex != render_.pageIndex ||
      candidate.cardCount != render_.cardCount || candidate.attentionCount != render_.attentionCount ||
      candidate.rowCount != render_.rowCount || std::strcmp(candidate.messageId, render_.messageId) ||
      std::strcmp(candidate.sessionId, render_.sessionId) ||
      candidate.weatherFresh != render_.weatherFresh ||
      candidate.weather.has_temperature_c != render_.weather.has_temperature_c ||
      candidate.weather.temperature_c != render_.weather.temperature_c ||
      candidate.weather.condition != render_.weather.condition ||
      candidate.weather.has_daily_low_c != render_.weather.has_daily_low_c ||
      candidate.weather.has_daily_high_c != render_.weather.has_daily_high_c ||
      candidate.weather.daily_low_c != render_.weather.daily_low_c ||
      candidate.weather.daily_high_c != render_.weather.daily_high_c ||
      candidate.weatherAlertActive != render_.weatherAlertActive ||
      candidate.weatherNotification != render_.weatherNotification ||
      candidate.weatherAlert.severity != render_.weatherAlert.severity ||
      std::strcmp(candidate.weatherAlert.title, render_.weatherAlert.title) ||
      std::strcmp(candidate.weather.location, render_.weather.location);
  for (size_t row = 0; row < candidate.rowCount && !changed; ++row) {
    changed = !sameCard(candidate.rows[row].card, render_.rows[row].card) ||
        std::strcmp(candidate.rows[row].messageId, render_.rows[row].messageId);
  }
  candidate.generation = render_.generation + (changed ? 1 : 0);
  render_ = candidate;
  return render_;
}

bool PresentationController::onFramePresented(uint32_t generation, uint64_t nowMs, Feedback& feedback) {
  if (generation != render_.generation) return false;
  feedback = Feedback{};
  std::strcpy(feedback.messageId, render_.messageId);
  std::strcpy(feedback.sessionId, render_.sessionId);
  feedback.stage = info_tv_v1_AckStage_ACK_STAGE_PRESENTED;
  if (render_.kind == RenderModel::Kind::kNotification && hasActive_ && !active_.presented) {
    active_.presented = true;
    activeUntilMs_ = nowMs + (active_.notification.has_display_duration_ms ?
        active_.notification.display_duration_ms :
        (active_.notification.priority == info_tv_v1_Priority_PRIORITY_IMPORTANT ?
            policy::kImportantDurationMs : policy::kOrdinaryDurationMs));
    return true;
  }
  if (render_.kind == RenderModel::Kind::kOverview) {
    for (size_t row = 0; row < render_.rowCount; ++row) {
      const auto& visible = render_.rows[row];
      for (size_t index = 0; index < state_.cardCount(); ++index) {
        auto& slot = state_.card(index);
        if (slot.presented || !sameCard(slot.card, visible.card) ||
            std::strcmp(slot.messageId, visible.messageId)) continue;
        slot.presented = true;
        std::strcpy(feedback.cardId, slot.card.card_id);
        std::strcpy(feedback.messageId, slot.messageId);
        feedback.revision = slot.card.revision;
        return true;
      }
    }
  }
  return false;
}
}  // namespace info_tv
