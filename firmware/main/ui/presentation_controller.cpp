#include "ui/presentation_controller.h"

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
  if (sameSession && state_.accepted(envelope.message_id)) {
    feedback.stage = info_tv_v1_AckStage_ACK_STAGE_ACCEPTED;
    return true;
  }
  bool accepted = true;
  switch (envelope.which_body) {
    case info_tv_v1_Envelope_snapshot_tag:
      if (!sameSession) hasActive_ = false;
      state_.applySnapshot(envelope);
      connected_ = true;
      cardIndex_ = 0;
      nextRotationMs_ = nowMs + policy::kRotationMs;
      break;
    case info_tv_v1_Envelope_card_upsert_tag:
      accepted = state_.upsertCard(envelope.body.card_upsert.card, envelope.message_id);
      break;
    case info_tv_v1_Envelope_notification_tag:
      accepted = state_.enqueueNotification(envelope, command.receivedAtMs, nowMs);
      break;
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

const RenderModel& PresentationController::tick(uint64_t nowMs) {
  if (hasActive_ && ((active_.presented && nowMs >= activeUntilMs_) ||
                     (!active_.presented && nowMs >= active_.expiresAtMs))) hasActive_ = false;
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
  candidate.cardCount = state_.cardCount();
  std::strcpy(candidate.sessionId, state_.sessionId());
  if (hasActive_) {
    candidate.kind = RenderModel::Kind::kNotification;
    candidate.view = active_.notification.view;
    std::strcpy(candidate.messageId, active_.messageId);
    std::strcpy(candidate.sessionId, active_.sessionId);
  } else if (state_.cardCount()) {
    if (nowMs >= nextRotationMs_) {
      cardIndex_ = (cardIndex_ + 1) % state_.cardCount();
      nextRotationMs_ = nowMs + policy::kRotationMs;
    }
    cardIndex_ %= state_.cardCount();
    const auto& slot = state_.card(cardIndex_);
    candidate.kind = RenderModel::Kind::kOverview;
    candidate.cardIndex = cardIndex_;
    candidate.view = slot.card.view;
    candidate.revision = slot.card.revision;
    std::strcpy(candidate.cardId, slot.card.card_id);
    std::strcpy(candidate.messageId, slot.messageId);
  }
  const bool changed = render_.generation == 0 || candidate.kind != render_.kind ||
      candidate.connected != render_.connected || candidate.cardIndex != render_.cardIndex ||
      candidate.cardCount != render_.cardCount || candidate.revision != render_.revision ||
      std::strcmp(candidate.cardId, render_.cardId) || std::strcmp(candidate.messageId, render_.messageId) ||
      std::strcmp(candidate.sessionId, render_.sessionId);
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
  if (render_.kind == RenderModel::Kind::kOverview && state_.cardCount()) {
    auto& slot = state_.card(cardIndex_);
    if (slot.presented || slot.card.revision != render_.revision ||
        std::strcmp(slot.messageId, render_.messageId)) return false;
    slot.presented = true;
    std::strcpy(feedback.cardId, slot.card.card_id);
    feedback.revision = slot.card.revision;
    return true;
  }
  return false;
}
}  // namespace info_tv
