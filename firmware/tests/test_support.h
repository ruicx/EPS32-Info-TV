#pragma once

#include <cstdlib>
#include <cstring>
#include <iostream>

#include "protocol/model.h"

/** Fail native tests in every build mode, including NDEBUG configurations. */
inline void check(bool condition, const char* expression, int line) {
  if (!condition) {
    std::cerr << "Check failed at line " << line << ": " << expression << '\n';
    std::exit(1);
  }
}
#define CHECK(expression) check(static_cast<bool>(expression), #expression, __LINE__)

/** Construct one structurally valid bounded card. */
inline info_tv::Card makeCard(const char* identity = "card", uint64_t revision = 1) {
  info_tv::Card card{};
  std::strcpy(card.card_id, identity);
  card.revision = revision;
  card.has_view = true;
  std::strcpy(card.view.title, "Build");
  card.view.which_content = info_tv_v1_View_status_tag;
  auto& status = card.view.content.status;
  std::strcpy(status.text, "running");
  status.tone = info_tv_v1_Tone_TONE_NEUTRAL;
  status.has_progress_percent = true;
  status.progress_percent = 42;
  return card;
}

/** Construct an ordered host envelope with a stable test session. */
inline info_tv::DisplayCommand makeCommand(const char* identity) {
  info_tv::DisplayCommand command{};
  command.envelope.protocol_version = 1;
  std::strcpy(command.envelope.session_id, "session");
  std::strcpy(command.envelope.message_id, identity);
  return command;
}

/** Construct one overview synchronization command. */
inline info_tv::DisplayCommand makeSnapshot(const char* identity = "snapshot") {
  auto command = makeCommand(identity);
  command.envelope.which_body = info_tv_v1_Envelope_snapshot_tag;
  command.envelope.body.snapshot.cards_count = 1;
  command.envelope.body.snapshot.cards[0] = makeCard();
  return command;
}

/** Construct one notification with independent event and operation identities. */
inline info_tv::DisplayCommand makeNotification(const char* identity, bool important = false) {
  auto command = makeCommand(identity);
  command.envelope.which_body = info_tv_v1_Envelope_notification_tag;
  auto& note = command.envelope.body.notification;
  std::strcpy(note.notification_id, identity);
  note.priority = important ? info_tv_v1_Priority_PRIORITY_IMPORTANT : info_tv_v1_Priority_PRIORITY_ORDINARY;
  note.valid_for_ms = 30000;
  note.has_view = true;
  note.view = makeCard().view;
  return command;
}
