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
  CHECK(!state.card(3).presented);

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
  auto weather = makeCommand("weather-during-page");
  weather.envelope.which_body = info_tv_v1_Envelope_weather_tag;
  weather.receivedAtMs = 6100;
  weather.envelope.body.weather.has_temperature_c = true;
  weather.envelope.body.weather.temperature_c = 23;
  std::strcpy(weather.envelope.body.weather.location, "Shanghai");
  weather.envelope.body.weather.valid_for_ms = 60000;
  CHECK(controller.handleCommand(weather, 6100, feedback));
  CHECK(controller.tick(6100).weatherFresh);
  CHECK(controller.tick(11999).pageIndex == 1);
  CHECK(controller.tick(12000).pageIndex == 2);
  CHECK(controller.tick(12000).rowCount == 2);
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

/** Keep weather independent of cards and expire it without renewing on retries. */
void testWeather() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.envelope.body.snapshot.cards_count = 0;
  snapshot.envelope.body.snapshot.has_weather = true;
  auto& weather = snapshot.envelope.body.snapshot.weather;
  weather.has_temperature_c = true;
  weather.temperature_c = 0;
  weather.condition = info_tv_v1_WeatherCondition_WEATHER_CONDITION_SNOW;
  std::strcpy(weather.location, "Harbin");
  weather.valid_for_ms = 1000;
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  auto model = controller.tick(0);
  CHECK(model.kind == info_tv::RenderModel::Kind::kEmpty);
  CHECK(model.weatherFresh && model.weather.temperature_c == 0);
  CHECK(!controller.onFramePresented(model.generation, 0, feedback));
  snapshot.receivedAtMs = 500;
  CHECK(controller.handleCommand(snapshot, 500, feedback));
  CHECK(controller.tick(999).weatherFresh);
  CHECK(!controller.tick(1000).weatherFresh);
  auto update = makeCommand("weather-update");
  update.envelope.which_body = info_tv_v1_Envelope_weather_tag;
  update.envelope.body.weather = weather;
  update.envelope.body.weather.temperature_c = -10;
  update.receivedAtMs = 1000;
  CHECK(controller.handleCommand(update, 1000, feedback));
  CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
  CHECK(controller.tick(1000).weather.temperature_c == -10);
  CHECK(controller.tick(1000).weatherFresh && state.cardCount() == 0);
  info_tv::DisplayCommand offline{};
  offline.linkLost = true;
  controller.handleCommand(offline, 1500, feedback);
  CHECK(controller.tick(1500).weatherFresh && !controller.tick(1500).connected);
  CHECK(!controller.tick(2000).weatherFresh);
  std::strcpy(update.envelope.message_id, "clear-weather");
  update.envelope.body.weather = info_tv_v1_Weather{};
  CHECK(controller.handleCommand(update, 2001, feedback));
  CHECK(!controller.tick(2001).weather.has_temperature_c);
  std::strcpy(update.envelope.session_id, "old-session");
  CHECK(controller.handleCommand(update, 2002, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_INVALID);
}

/** Keep warning markers independent, and cancel obsolete notifications promptly. */
void testWeatherAlerts() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  auto ordinary = makeNotification("ordinary-weather-test");
  CHECK(controller.handleCommand(ordinary, 0, feedback));
  auto model = controller.tick(0);
  CHECK(!model.weatherNotification);
  auto alert = makeWeatherAlert();
  CHECK(controller.handleCommand(alert, 1, feedback));
  model = controller.tick(1);
  CHECK(model.weatherNotification && model.weatherAlertActive);
  CHECK(model.cardCount == 1 && model.attentionCount == 0);
  CHECK(controller.onFramePresented(model.generation, 1, feedback));
  CHECK(!std::strcmp(feedback.messageId, "weather-alert"));
  CHECK(controller.tick(10001).kind == info_tv::RenderModel::Kind::kOverview);
  CHECK(controller.tick(10001).weatherAlertActive);
  alert.receivedAtMs = 50000;
  CHECK(controller.handleCommand(alert, 50000, feedback));
  CHECK(!controller.tick(60000).weatherAlertActive);  // Retry did not renew TTL.

  alert = makeWeatherAlert("new-alert");
  alert.receivedAtMs = 60001;
  alert.envelope.body.weather_alert.valid_for_ms = 1000;
  CHECK(controller.handleCommand(alert, 60001, feedback));
  model = controller.tick(60001);
  CHECK(model.weatherNotification);
  CHECK(controller.onFramePresented(model.generation, 60001, feedback));
  model = controller.tick(61001);
  CHECK(!model.weatherAlertActive && !model.weatherNotification);

  alert = makeWeatherAlert("withdraw-me");
  alert.receivedAtMs = 61002;
  CHECK(controller.handleCommand(alert, 61002, feedback));
  CHECK(controller.tick(61002).weatherNotification);
  auto clear = makeCommand("clear-alert");
  clear.envelope.which_body = info_tv_v1_Envelope_weather_alert_tag;
  CHECK(controller.handleCommand(clear, 61003, feedback));
  CHECK(!controller.tick(61003).weatherNotification);
  CHECK(!controller.tick(61003).weatherAlertActive);
  CHECK(!controller.onFramePresented(model.generation, 61003, feedback));

  // A full task notification queue cannot prevent a warning marker or notice.
  for (int index = 0; index < 8; ++index) {
    char identity[20];
    std::snprintf(identity, sizeof(identity), "queued-%d", index);
    auto note = makeNotification(identity, true);
    note.receivedAtMs = 62000;
    CHECK(controller.handleCommand(note, 62000, feedback));
    CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
  }
  alert = makeWeatherAlert("reserved-alert");
  alert.receivedAtMs = 62000;
  CHECK(controller.handleCommand(alert, 62000, feedback));
  CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
  auto overflow = makeNotification("overflow", true);
  overflow.receivedAtMs = 62000;
  CHECK(controller.handleCommand(overflow, 62000, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_BUSY);
  info_tv::NotificationSlot selected;
  CHECK(state.popNotification(62000, selected));
  CHECK(selected.weatherAlert);  // Warnings precede queued task notices at equal priority.
  std::strcpy(clear.envelope.message_id, "cancel-queued-warning");
  CHECK(controller.handleCommand(clear, 62001, feedback));
  info_tv::NotificationSlot slot;
  size_t count = 0;
  while (state.popNotification(62001, slot)) {
    CHECK(!slot.weatherAlert);
    ++count;
  }
  CHECK(count == 8);

  // Expired queued alert input cannot start a notification or revive the marker.
  alert = makeWeatherAlert("already-expired");
  alert.envelope.body.weather_alert.valid_for_ms = 1;
  CHECK(controller.handleCommand(alert, 63000, feedback));
  CHECK(!controller.tick(63000).weatherAlertActive);
  CHECK(!controller.tick(63000).weatherNotification);
}

/** Admit settings independently without acknowledging hardware application. */
void testDeviceSettings() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto setting = makeCommand("brightness");
  setting.envelope.which_body = info_tv_v1_Envelope_device_settings_tag;
  auto& settings = setting.envelope.body.device_settings;
  settings.has_brightness_percent = true;
  settings.brightness_percent = 30;
  CHECK(controller.handleCommand(setting, 0, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_INVALID);
  CHECK(controller.handleCommand(makeSnapshot(), 1, feedback));
  const auto generation = controller.tick(1).generation;
  for (uint32_t percent : {0, 30, 100}) {
    settings.brightness_percent = percent;
    CHECK(controller.handleCommand(setting, 2, feedback));
    CHECK(feedback.stage == info_tv_v1_AckStage_ACK_STAGE_ACCEPTED);
    CHECK(feedback.brightnessPercent == percent);
    CHECK(controller.tick(2).generation == generation);
    CHECK(state.cardCount() == 1);
  }
  settings.brightness_percent = 101;
  CHECK(controller.handleCommand(setting, 3, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_INVALID);
  settings.has_brightness_percent = false;
  CHECK(controller.handleCommand(setting, 4, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_INVALID);
  std::strcpy(setting.envelope.session_id, "old-session");
  settings.has_brightness_percent = true;
  settings.brightness_percent = 30;
  CHECK(controller.handleCommand(setting, 5, feedback));
  CHECK(feedback.error == info_tv_v1_ErrorCode_ERROR_CODE_INVALID);
}

/** Remove orphaned task notices while preserving unrelated task notifications. */
void testSnapshotRemovesTaskNotifications() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.envelope.body.snapshot.cards_count = 2;
  snapshot.envelope.body.snapshot.cards[1] = makeCard("keep");
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  auto active = makeNotification("active");
  std::strcpy(active.envelope.body.notification.card_id, "card");
  CHECK(controller.handleCommand(active, 1, feedback));
  CHECK(controller.tick(1).kind == info_tv::RenderModel::Kind::kNotification);
  auto queued = makeNotification("queued");
  std::strcpy(queued.envelope.body.notification.card_id, "card");
  CHECK(controller.handleCommand(queued, 2, feedback));
  auto keep = makeNotification("keep-note");
  std::strcpy(keep.envelope.body.notification.card_id, "keep");
  CHECK(controller.handleCommand(keep, 2, feedback));
  auto removal = makeSnapshot("removal");
  removal.envelope.body.snapshot.cards[0] = makeCard("keep");
  CHECK(controller.handleCommand(removal, 3, feedback));
  CHECK(state.cardCount() == 1 && !state.hasCard("card"));
  auto model = controller.tick(3);
  CHECK(!std::strcmp(model.messageId, "keep-note"));
  CHECK(controller.onFramePresented(model.generation, 3, feedback));
  model = controller.tick(5003);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);
  CHECK(!std::strcmp(model.rows[0].card.card_id, "keep"));
  CHECK(controller.handleCommand(removal, 5004, feedback));
  CHECK(controller.tick(5004).kind == info_tv::RenderModel::Kind::kOverview);
}

/** Keep interrupted cards neutral and sort them after actively running cards. */
void testInterruptedOverview() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.envelope.body.snapshot.cards_count = 3;
  const char* identities[] = {"stopped", "done", "active"};
  const char* statuses[] = {"interrupted", "completed", "running"};
  for (size_t index = 0; index < 3; ++index) {
    auto& card = snapshot.envelope.body.snapshot.cards[index];
    card = makeCard(identities[index]);
    std::strcpy(card.view.content.status.text, statuses[index]);
    card.view.content.status.tone = index == 1 ?
        info_tv_v1_Tone_TONE_POSITIVE : info_tv_v1_Tone_TONE_NEUTRAL;
  }
  CHECK(controller.handleCommand(snapshot, 0, feedback));
  const auto& model = controller.tick(0);
  CHECK(model.attentionCount == 0 && model.rowCount == 3);
  CHECK(!std::strcmp(model.rows[0].card.card_id, "active"));
  CHECK(!std::strcmp(model.rows[1].card.card_id, "stopped"));
  CHECK(!std::strcmp(model.rows[2].card.card_id, "done"));
  CHECK(model.rows[1].card.view.content.status.tone == info_tv_v1_Tone_TONE_NEUTRAL);
}

/** Verify auto-dismissal of approval popups when card transitions out of attention. */
void testApprovalAutoDismiss() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.envelope.body.snapshot.cards[0] = makeCard("task-1");
  snapshot.envelope.body.snapshot.cards[0].view.content.status.tone = info_tv_v1_Tone_TONE_ATTENTION;
  CHECK(controller.handleCommand(snapshot, 0, feedback));

  auto approvalNote = makeNotification("approval-prompt", true);
  std::strcpy(approvalNote.envelope.body.notification.card_id, "task-1");
  approvalNote.envelope.body.notification.view.content.status.tone = info_tv_v1_Tone_TONE_ATTENTION;
  CHECK(controller.handleCommand(approvalNote, 10, feedback));

  auto model = controller.tick(10);
  CHECK(model.kind == info_tv::RenderModel::Kind::kNotification);
  CHECK(!std::strcmp(model.messageId, "approval-prompt"));
  CHECK(controller.onFramePresented(model.generation, 10, feedback));

  // User approves in CLI -> card upsert arrives with TONE_NEUTRAL (running)
  auto runningUpsert = makeCommand("approved-running");
  runningUpsert.envelope.which_body = info_tv_v1_Envelope_card_upsert_tag;
  runningUpsert.envelope.body.card_upsert.has_card = true;
  runningUpsert.envelope.body.card_upsert.card = makeCard("task-1", 2);
  runningUpsert.envelope.body.card_upsert.card.view.content.status.tone = info_tv_v1_Tone_TONE_NEUTRAL;
  CHECK(controller.handleCommand(runningUpsert, 50, feedback));

  // The popup must be dismissed immediately on next tick
  model = controller.tick(51);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);
  CHECK(!std::strcmp(model.rows[0].card.card_id, "task-1"));
  CHECK(model.rows[0].card.revision == 2);

  // Completed notification with TONE_POSITIVE should NOT be dismissed by a neutral upsert
  auto doneNote = makeNotification("done-note", false);
  std::strcpy(doneNote.envelope.body.notification.card_id, "task-1");
  doneNote.envelope.body.notification.view.content.status.tone = info_tv_v1_Tone_TONE_POSITIVE;
  CHECK(controller.handleCommand(doneNote, 60, feedback));
  model = controller.tick(60);
  CHECK(model.kind == info_tv::RenderModel::Kind::kNotification);
  CHECK(!std::strcmp(model.messageId, "done-note"));

  auto anotherUpsert = runningUpsert;
  std::strcpy(anotherUpsert.envelope.message_id, "keep-done");
  anotherUpsert.envelope.body.card_upsert.card.revision = 3;
  CHECK(controller.handleCommand(anotherUpsert, 70, feedback));
  // Notification remains active because it was not an attention prompt
  CHECK(controller.tick(70).kind == info_tv::RenderModel::Kind::kNotification);
}

/** Verify manual double-click dismissal of active notifications and weather alerts. */
void testManualDismissal() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  CHECK(controller.handleCommand(snapshot, 0, feedback));

  // No active notification to dismiss initially
  CHECK(!controller.dismissActiveNotification(10));

  // Show a task notification
  auto note = makeNotification("task-done");
  CHECK(controller.handleCommand(note, 20, feedback));
  auto model = controller.tick(20);
  CHECK(model.kind == info_tv::RenderModel::Kind::kNotification);

  // Dismiss via touch button
  CHECK(controller.dismissActiveNotification(30));
  model = controller.tick(31);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);

  // Weather alert dismissal
  auto alert = makeWeatherAlert("storm");
  CHECK(controller.handleCommand(alert, 40, feedback));
  model = controller.tick(40);
  CHECK(model.kind == info_tv::RenderModel::Kind::kNotification);
  CHECK(model.weatherNotification);

  CHECK(controller.dismissActiveNotification(50));
  model = controller.tick(51);
  CHECK(model.kind == info_tv::RenderModel::Kind::kOverview);
}

/** Expire question hints locally; retries do not restart them and new questions do. */
void testRecentQuestionHint() {
  info_tv::DisplayState state;
  info_tv::PresentationController controller(state);
  info_tv::Feedback feedback{};
  auto snapshot = makeSnapshot();
  snapshot.receivedAtMs = 100;
  snapshot.envelope.body.snapshot.cards[0].view.content.status.recent_question_seconds = 30;
  CHECK(controller.handleCommand(snapshot, 100, feedback));
  auto model = controller.tick(100);
  CHECK(model.rows[0].recentQuestion);
  CHECK(!std::strcmp(model.rows[0].card.view.content.status.text, "running"));
  CHECK(controller.handleCommand(snapshot, 10000, feedback));
  auto update = makeCommand("ordinary-activity");
  update.receivedAtMs = 10100;
  update.envelope.which_body = info_tv_v1_Envelope_card_upsert_tag;
  update.envelope.body.card_upsert.has_card = true;
  update.envelope.body.card_upsert.card = makeCard("card", 2);
  update.envelope.body.card_upsert.card.view.content.status.recent_question_seconds = 20;
  CHECK(controller.handleCommand(update, 10100, feedback));
  CHECK(controller.tick(30099).rows[0].recentQuestion);
  const auto generation = controller.tick(30099).generation;
  CHECK(!controller.tick(30100).rows[0].recentQuestion);
  CHECK(controller.tick(30100).generation > generation);
  CHECK(controller.onFramePresented(controller.tick(30100).generation, 30100, feedback));
  CHECK(controller.handleCommand(update, 30101, feedback));
  CHECK(!controller.tick(30101).rows[0].recentQuestion);
  std::strcpy(update.envelope.message_id, "new-question");
  update.receivedAtMs = 31000;
  update.envelope.body.card_upsert.card.revision = 3;
  update.envelope.body.card_upsert.card.view.content.status.recent_question_seconds = 30;
  CHECK(controller.handleCommand(update, 31000, feedback));
  CHECK(controller.tick(31000).rows[0].recentQuestion);
  std::strcpy(update.envelope.message_id, "end-task");
  update.receivedAtMs = 32000;
  update.envelope.body.card_upsert.card.revision = 4;
  auto& status = update.envelope.body.card_upsert.card.view.content.status;
  std::strcpy(status.text, "completed");
  status.tone = info_tv_v1_Tone_TONE_POSITIVE;
  status.recent_question_seconds = 0;
  CHECK(controller.handleCommand(update, 32000, feedback));
  CHECK(!controller.tick(32000).rows[0].recentQuestion);
}

/** Verify UI admission, actual visibility, interruption, restoration, and expiry. */
int main() {
  testRecentQuestionHint();
  testApprovalAutoDismiss();
  testManualDismissal();
  testInterruptedOverview();
  testSnapshotRemovesTaskNotifications();
  testPagedOverview();
  testDeviceSettings();
  testWeather();
  testWeatherAlerts();
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
