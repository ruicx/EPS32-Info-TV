#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>

#include "lvgl.h"

#include "test_support.h"
#include "ui/screen_view.h"

namespace {
/** Capture one full CPU-rendered image without simulating physical LCD timing. */
struct Capture {
  std::array<uint8_t, 240 * 240 * 3> pixels{};
  bool flushed = false;
};

/** Copy the full RGB888 draw buffer and complete the desktop flush immediately. */
void flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels) {
  auto& capture = *static_cast<Capture*>(lv_display_get_user_data(display));
  CHECK(area->x1 == 0 && area->y1 == 0 && area->x2 == 239 && area->y2 == 239);
  std::memcpy(capture.pixels.data(), pixels, capture.pixels.size());
  capture.flushed = true;
  lv_display_flush_ready(display);
}

/** Save the actual LVGL pixels as a portable image for visual review. */
void save(const Capture& capture, const std::string& filename) {
  CHECK(capture.flushed);
  std::ofstream output(filename, std::ios::binary);
  output << "P6\n240 240\n255\n";
  for (size_t pixel = 0; pixel < capture.pixels.size(); pixel += 3) {
    const char rgb[] = {static_cast<char>(capture.pixels[pixel + 2]),
                        static_cast<char>(capture.pixels[pixel + 1]),
                        static_cast<char>(capture.pixels[pixel])};
    output.write(rgb, sizeof(rgb));
  }
  CHECK(output.good());
}

/** Check every visible widget remains within the physical screen bounds. */
void checkBounds(lv_obj_t* parent = lv_screen_active()) {
  lv_obj_update_layout(parent);
  for (uint32_t index = 0; index < lv_obj_get_child_count(parent); ++index) {
    auto* child = lv_obj_get_child(parent, index);
    if (!lv_obj_is_visible(child)) continue;
    CHECK(lv_obj_get_x(child) >= 0 && lv_obj_get_y(child) >= 0);
    CHECK(lv_obj_get_x(child) + lv_obj_get_width(child) <= lv_obj_get_width(parent));
    CHECK(lv_obj_get_y(child) + lv_obj_get_height(child) <= lv_obj_get_height(parent));
    checkBounds(child);
  }
}

/** Locate a visible label by content to detect text corruption across updates. */
bool hasLabel(const char* text, lv_obj_t* parent = lv_screen_active()) {
  for (uint32_t index = 0; index < lv_obj_get_child_count(parent); ++index) {
    auto* child = lv_obj_get_child(parent, index);
    if (!lv_obj_is_visible(child)) continue;
    if (lv_obj_check_type(child, &lv_label_class) &&
        !std::strcmp(lv_label_get_text(child), text)) return true;
    if (hasLabel(text, child)) return true;
  }
  return false;
}

/** Count visible progress tracks, optionally requiring one reported value. */
size_t visibleBars(int value = -1, lv_obj_t* parent = lv_screen_active()) {
  size_t count = 0;
  for (uint32_t index = 0; index < lv_obj_get_child_count(parent); ++index) {
    auto* child = lv_obj_get_child(parent, index);
    if (!lv_obj_is_visible(child)) continue;
    if (lv_obj_check_type(child, &lv_bar_class) &&
        (value < 0 || lv_bar_get_value(child) == value)) ++count;
    count += visibleBars(value, child);
  }
  return count;
}
}  // namespace

/** Verify and capture overview, notification, offline, and empty widget states. */
int main(int argc, char** argv) {
  CHECK(argc == 2);
  lv_init();
  Capture capture;
  std::array<uint8_t, 240 * 240 * 3> buffer{};
  auto* display = lv_display_create(240, 240);
  lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB888);
  lv_display_set_buffers(display, buffer.data(), nullptr, buffer.size(), LV_DISPLAY_RENDER_MODE_FULL);
  lv_display_set_user_data(display, &capture);
  lv_display_set_flush_cb(display, flush);
  info_tv::ScreenView screen;
  screen.initialize();
  info_tv::RenderModel model{};
  model.kind = info_tv::RenderModel::Kind::kOverview;
  model.connected = true;
  model.cardCount = 8;
  model.rowCount = 5;
  model.pageCount = 2;
  model.attentionCount = 2;
  const char* titles[] = {"消息接口", "Login", "Unit tests", "UI review", "Deploy"};
  const char* states[] = {"waiting input", "failed", "running", "running", "completed"};
  const info_tv_v1_TaskIcon icons[] = {info_tv_v1_TaskIcon_TASK_ICON_CODE,
      info_tv_v1_TaskIcon_TASK_ICON_BUILD, info_tv_v1_TaskIcon_TASK_ICON_TEST,
      info_tv_v1_TaskIcon_TASK_ICON_REVIEW, info_tv_v1_TaskIcon_TASK_ICON_DEPLOY};
  for (size_t row = 0; row < model.rowCount; ++row) {
    model.rows[row].card = makeCard();
    auto& card = model.rows[row].card;
    std::snprintf(card.card_id, sizeof(card.card_id), "a%03u", static_cast<unsigned>(row));
    std::strcpy(card.view.source, row == 1 ? "agy" : "codex");
    std::strcpy(card.view.context, "info_tv");
    std::strcpy(card.view.title, titles[row]);
    card.view.icon = icons[row];
    auto& status = card.view.content.status;
    status.tone = row == 0 ? info_tv_v1_Tone_TONE_ATTENTION : row == 1 ?
        info_tv_v1_Tone_TONE_NEGATIVE : row == 4 ? info_tv_v1_Tone_TONE_POSITIVE :
        info_tv_v1_Tone_TONE_NEUTRAL;
    std::strcpy(status.text, states[row]);
    status.has_progress_percent = row >= 2;
    status.progress_percent = row == 3 ? 0 : row == 4 ? 100 : 42;
  }
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("8 sessions"));
  CHECK(hasLabel("2 need you"));
  CHECK(hasLabel("消息接口"));
  CHECK(hasLabel("RUN") && hasLabel("WAIT") && hasLabel("FAIL") && hasLabel("DONE"));
  CHECK(hasLabel(LV_SYMBOL_OK) && hasLabel(LV_SYMBOL_UPLOAD));
  CHECK(visibleBars() == 3 && visibleBars(0) == 1 && visibleBars(100) == 1);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-overview.ppm");
  auto longModel = model;
  longModel.rowCount = 1;
  std::memset(longModel.rows[0].card.view.source, 's', 64);
  std::memset(longModel.rows[0].card.view.title, 't', 64);
  screen.render(longModel);
  checkBounds();
  CHECK(!hasLabel("Unit tests"));
  CHECK(visibleBars() == 0);
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("消息接口"));
  model.connected = false;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("RUN"));
  CHECK(visibleBars() == 0);
  CHECK(hasLabel("Offline | last state"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-offline.ppm");
  model.kind = info_tv::RenderModel::Kind::kNotification;
  model.connected = true;
  model.view = model.rows[0].card.view;
  std::strcpy(model.cardId, model.rows[0].card.card_id);
  std::strcpy(model.view.content.status.detail, "Please return to your computer.");
  screen.render(model);
  checkBounds();
  CHECK(!hasLabel("Unit tests"));
  CHECK(hasLabel("Please return to your computer."));
  CHECK(visibleBars() == 0);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-notification.ppm");
  model.view = model.rows[2].card.view;
  std::strcpy(model.cardId, model.rows[2].card.card_id);
  std::strcpy(model.view.content.status.detail, "Checking protocol compatibility.");
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("running 42%"));
  CHECK(visibleBars(42) == 1);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-progress.ppm");
  model.connected = false;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("last: running"));
  CHECK(!hasLabel("running 42%"));
  CHECK(visibleBars() == 0);
  model.kind = info_tv::RenderModel::Kind::kEmpty;
  model.connected = true;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("No messages yet"));
  CHECK(!hasLabel("last: running"));
  CHECK(visibleBars() == 0);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-empty.ppm");
  model.kind = info_tv::RenderModel::Kind::kOverview;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("Unit tests"));
  CHECK(visibleBars() == 3);
  CHECK(!hasLabel("Ready for tasks"));
  lv_deinit();
}
