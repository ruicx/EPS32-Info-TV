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
void checkBounds() {
  auto* screen = lv_screen_active();
  lv_obj_update_layout(screen);
  for (uint32_t index = 0; index < lv_obj_get_child_count(screen); ++index) {
    auto* child = lv_obj_get_child(screen, index);
    if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
    CHECK(lv_obj_get_x(child) >= 0 && lv_obj_get_y(child) >= 0);
    CHECK(lv_obj_get_x(child) + lv_obj_get_width(child) <= 240);
    CHECK(lv_obj_get_y(child) + lv_obj_get_height(child) <= 240);
  }
}

/** Locate a visible label by content to detect text corruption across updates. */
bool hasLabel(const char* text) {
  auto* screen = lv_screen_active();
  for (uint32_t index = 0; index < lv_obj_get_child_count(screen); ++index) {
    auto* child = lv_obj_get_child(screen, index);
    if (!lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN) && lv_obj_check_type(child, &lv_label_class) &&
        !std::strcmp(lv_label_get_text(child), text)) return true;
  }
  return false;
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
  model.rowCount = 3;
  model.pageCount = 3;
  model.attentionCount = 2;
  for (size_t row = 0; row < model.rowCount; ++row) {
    model.rows[row].card = makeCard();
    auto& card = model.rows[row].card;
    std::snprintf(card.card_id, sizeof(card.card_id), "a%03u", static_cast<unsigned>(row));
    std::strcpy(card.view.source, row == 1 ? "agy" : "codex");
    std::strcpy(card.view.context, "info_tv");
    std::strcpy(card.view.title, row == 0 ? "消息接口" : row == 1 ? "Login" : "Tests");
    auto& status = card.view.content.status;
    status.tone = row == 0 ? info_tv_v1_Tone_TONE_ATTENTION : row == 1 ?
        info_tv_v1_Tone_TONE_NEGATIVE : info_tv_v1_Tone_TONE_NEUTRAL;
    std::strcpy(status.text, row == 0 ? "waiting input" : row == 1 ? "failed" : "running");
    status.has_progress_percent = row == 2;
  }
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("8 sessions | 2 need you"));
  CHECK(hasLabel("codex #a000 | 消息接口"));
  CHECK(hasLabel("info_tv | running 42%"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-overview.ppm");
  auto longModel = model;
  longModel.rowCount = 1;
  std::memset(longModel.rows[0].card.view.source, 's', 64);
  std::memset(longModel.rows[0].card.view.title, 't', 64);
  screen.render(longModel);
  checkBounds();
  CHECK(!hasLabel("codex #a002 | Tests"));
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("codex #a000 | 消息接口"));
  model.connected = false;
  screen.render(model);
  checkBounds();
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-offline.ppm");
  model.kind = info_tv::RenderModel::Kind::kNotification;
  model.connected = true;
  model.view = model.rows[0].card.view;
  std::strcpy(model.cardId, model.rows[0].card.card_id);
  std::strcpy(model.view.content.status.detail, "Please return to your computer.");
  screen.render(model);
  checkBounds();
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-notification.ppm");
  model.kind = info_tv::RenderModel::Kind::kEmpty;
  screen.render(model);
  checkBounds();
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-empty.ppm");
  lv_deinit();
}
