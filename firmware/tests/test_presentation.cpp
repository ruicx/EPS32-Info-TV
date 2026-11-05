#include "ui/presentation_controller.h"

#include <cstdio>
#include <cstring>

#include "test_support.h"

/** Verify multi-page priority, fairness, stable timing, and per-row visibility. */
void testPagedOverview() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.envelope.body.snapshot.cards_count = 8;
  for (size_t index = 0; index < 8; ++index) {
    char identity[16];
    std::snprintf(identity, sizeof(identity), "card-%u", static_cast<unsigned>(index));
    snapshot.envelope.body.snapshot.cards[index] = makeCard(identity);
  }
  snapshot.envelope.body.snapshot.cards[6].view.content.status.tone = info_tv_v1_Tone_TONE_ATTENTION;
  snapshot.envelope.body.snapshot.cards[7].view.content.status.tone = info_tv_v1_Tone_TONE_NEGATIVE;
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  auto model = controller.tick(0);
  CHECK(model.pageCount == 3 && model.pageIndex == 0 && model.rowCount == 3);
  CHECK(model.attentionCount == 2 && model.cardCount == 8);
  CHECK(!std::strcmp(model.rows[0].card.card_id, "card-6"));
  CHECK(!std::strcmp(model.rows[1].card.card_id, "card-7"));
  for (size_t row = 0; row < model.rowCount; ++row) {
    CHECK(controller.onFramePresented(model.generation, 0, feedback));
    CHECK(!std::strcmp(feedback.cardId, model.rows[row].card.card_id));
  }
  CHECK(!controller.onFramePresented(model.generation, 0, feedback));
  CHECK(!state.card(1).presented);

  auto upsert = makeCommand("hidden-update");
  upsert.envelope.which_body = info_tv_v1_Envelope_card_upsert_tag;
  upsert.envelope.body.card_upsert.has_card = true;
  upsert.envelope.body.card_upsert.card = makeCard("card-1", 2);
  CHECK(controller.handleCommand(upsert, 5999, feedback));
  CHECK(controller.tick(5999).generation == model.generation);
  model = controller.tick(6000);
  CHECK(model.pageIndex == 1);
  CHECK(model.rows[0].card.revision == 2);
  CHECK(!controller.onFramePresented(model.generation - 1, 6000, feedback));
  CHECK(controller.onFramePresented(model.generation, 6000, feedback));
  CHECK(!std::strcmp(feedback.messageId, "hidden-update"));
  CHECK(controller.tick(12000).pageIndex == 2);
  CHECK(controller.tick(18000).pageIndex == 0);

  auto note = makeNotification("related", true);
  std::strcpy(note.envelope.body.notification.card_id, "card-5");
  CHECK(controller.handleCommand(note, 18001, feedback));
  model = controller.tick(18001);
  CHECK(controller.onFramePresented(model.generation, 18001, feedback));
  CHECK(controller.tick(28000).kind == info_tv::RenderModel::Kind::kNotification);
  model = controller.tick(28001);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview && model.pageIndex == 2);
  CHECK(controller.tick(34000).pageIndex == 2);
  CHECK(controller.tick(34001).pageIndex == 0);
}

/** Verify UI admission, actual visibility, interruption, restoration, and expiry. */
int main() {
  testPagedOverview();
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
  auto model = controller.tick(0);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);
  CHECK(controller.onFramePresented(model.generation, 0, feedback));
  CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_PRESENTED);
  CHECK(!std::strcmp(feedback.cardId, "card"));
  CHECK(!controller.onFramePresented(model.generation, 0, feedback));

  auto ordinary = makeNotification("ordinary");
  CHECK(controller.handleCommand(ordinary, 1, feedback));
  model = controller.tick(1);
  CHECK(model.kind == info_tv::RenderModel::Kind::kNotification);
  CHECK(controller.onFramePresented(model.generation, 1, feedback));
  // Updating a hidden overview must not produce Presented for that update.
  auto upsert = makeCommand("update");
  upsert.envelope.which_body = info_tv_v1_Envelope_card_upsert_tag;
  upsert.envelope.body.card_upsert.has_card = true;
  upsert.envelope.body.card_upsert.card = makeCard("card", 2);
  CHECK(controller.handleCommand(upsert, 2, feedback));
  CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
  model = controller.tick(2);
  CHECK(!controller.onFramePresented(model.generation, 2, feedback));
  auto important = makeNotification("important", true);
  CHECK(controller.handleCommand(important, 3, feedback));
  model = controller.tick(3);
  CHECK(!std::strcmp(model.messageId, "important"));
  CHECK(controller.onFramePresented(model.generation, 3, feedback));
  CHECK(controller.handleCommand(important, 500, feedback));
  CHECK(controller.tick(10002).kind == info_tv::RenderModel::Kind::kNotification);
  model = controller.tick(10003);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);
  CHECK(model.rows[0].card.revision == 2);
  CHECK(controller.onFramePresented(model.generation, 10003, feedback));
  CHECK(!std::strcmp(feedback.messageId, "update"));
  CHECK(controller.tick(15000).kind == info_tv::RenderModel::Kind::kOverview);

  // A malformed snapshot cannot partially replace the current overview.
  auto invalid = makeSnapshot("invalid");
  invalid.envelope.body.snapshot.cards[0].revision = 0;
  CHECK(controller.handleCommand(invalid, 15001, feedback));
  CHECK(feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED);
  CHECK(state.card(0).card.revision == 2);
  CHECK(controller.handleCommand(snapshot, 15002, feedback));
  CHECK(state.card(0).card.revision == 2);  // Retried snapshot is idempotent.

  // Expired commands and old-session updates cannot mutate current content.
  auto expired = makeNotification("expired");
  expired.envelope.body.notification.valid_for_ms = 10;
  CHECK(controller.handleCommand(expired, 15003, feedback));
  CHECK(feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED);
  auto stale = upsert;
  std::strcpy(stale.envelope.message_id, "stale");
  stale.envelope.body.card_upsert.card.revision = 1;
  CHECK(controller.handleCommand(stale, 15004, feedback));
  CHECK(feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED);
  auto newSession = makeSnapshot("new-session");
  std::strcpy(newSession.envelope.session_id, "other-session");
  CHECK(controller.handleCommand(newSession, 15005, feedback));
  CHECK(state.card(0).card.revision == 1);
  CHECK(controller.handleCommand(upsert, 15006, feedback));
  CHECK(feedback.error != info_tv_v1_ErrorCode_ERROR_CODE_UNSPECIFIED);
  info_tv::DisplayCommand offline{};
  offline.linkLost = true;
  CHECK(!controller.handleCommand(offline, 15007, feedback));
  CHECK(!controller.tick(15007).connected);
  CHECK(state.cardCount() == 1);
}
