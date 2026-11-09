#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>

#include "lvgl.h"
#include "src/misc/lv_text_private.h"

#include "test_support.h"
#include "ui/screen_view.h"

extern "C" {
LV_FONT_DECLARE(font_maple_mono_16);
}

namespace {
/** Verify the full pinned Han coverage and an icon outside the Unicode BMP. */
void checkFontCoverage() {
  size_t hanCount = 0;
  lv_font_glyph_dsc_t glyph{};
  for (uint32_t code = 0x4e00; code <= 0x9fff; ++code) {
    if (lv_font_get_glyph_dsc(&font_maple_mono_16, &glyph, code, 0)) {
      CHECK(!glyph.is_placeholder && glyph.box_w > 0 && glyph.box_h > 0);
      ++hanCount;
    }
  }
  CHECK(hanCount == 20976);
  for (uint32_t code : {0x6df1, 0x5733, 0x9e66, 0x9e49, 0x9f98, 0xf0001}) {
    CHECK(lv_font_get_glyph_dsc(&font_maple_mono_16, &glyph, code, 0));
    CHECK(!glyph.is_placeholder && glyph.box_w > 0 && glyph.box_h > 0);
  }
}

/** Capture one full CPU-rendered image without simulating physical LCD timing. */
struct Capture {
  std::array<uint8_t, 240 * 240 * 3> pixels{};
  bool flushed = false;
  size_t pixelsFlushed = 0;
};

/** Copy full or partial RGB888 areas and complete the desktop flush immediately. */
void flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels) {
  auto& capture = *static_cast<Capture*>(lv_display_get_user_data(display));
  CHECK(area->x1 >= 0 && area->y1 >= 0 && area->x2 < 240 && area->y2 < 240);
  const size_t width = lv_area_get_width(area);
  for (int32_t y = area->y1; y <= area->y2; ++y) {
    std::memcpy(capture.pixels.data() + (y * 240 + area->x1) * 3,
                pixels + (y - area->y1) * width * 3, width * 3);
  }
  capture.pixelsFlushed += width * lv_area_get_height(area);
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
    if (lv_obj_check_type(child, &lv_label_class)) {
      const auto* font = lv_obj_get_style_text_font(child, LV_PART_MAIN);
      const auto* text = lv_label_get_text(child);
      CHECK(lv_obj_get_content_height(child) >= font->line_height);
      uint32_t offset = 0;
      while (text[offset]) {
        const uint32_t code = lv_text_encoded_next(text, &offset);
        lv_font_glyph_dsc_t glyph{};
        CHECK(lv_font_get_glyph_dsc(font, &glyph, code, 0));
        if (!glyph.box_h) continue;
        const int top = font->line_height - font->base_line - glyph.box_h - glyph.ofs_y;
        if (top < 0 || top + glyph.box_h > lv_obj_get_content_height(child)) {
          std::cerr << "Clipped U+" << std::hex << code << std::dec << " in " << text
                    << ": top=" << top << ", height=" << glyph.box_h << '\n';
        }
        CHECK(top >= 0);
        CHECK(top + glyph.box_h <= lv_obj_get_content_height(child));
      }
    }
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

/** Check blink boundaries, frame skipping, and independent widget updates. */
void checkAnimationTiming(info_tv::ScreenView& screen, const info_tv::RenderModel& model) {
  CHECK(!screen.animate(0));
  CHECK(!screen.animate(5029));
  CHECK(screen.animate(5030));
  CHECK(!screen.animate(5169));
  screen.render(model);  // Message refreshes must not reopen or restart the pose.
  CHECK(!screen.animate(5040));
  CHECK(screen.animate(5170));
  CHECK(!screen.animate(7000));  // A skipped blink is not queued for playback.
  CHECK(screen.animate(15000));
  CHECK(!screen.animate(15074));
  CHECK(screen.animate(15075));
  CHECK(screen.animate(15615));
  CHECK(!screen.animate(24000));
}

/** Export actual LVGL motion with its timing and check unchanged surrounding pixels. */
void captureAnimation(info_tv::ScreenView& screen, lv_display_t* display, Capture& capture,
                      const std::string& prefix) {
  const auto baseline = capture.pixels;
  auto previous = baseline;
  std::ofstream timeline(prefix + "-animation.csv");
  timeline << "frame,duration_ms\n";
  size_t frame = 0;
  uint64_t previousAt = 0;
  std::string filename = prefix + "-animation-0.ppm";
  save(capture, filename);
  for (uint64_t nowMs = 5; nowMs < 24000; nowMs += 5) {
    if (!screen.animate(nowMs)) continue;
    timeline << filename << ',' << nowMs - previousAt << '\n';
    previousAt = nowMs;
    checkBounds();
    lv_refr_now(display);
    CHECK(capture.pixels != previous);
    for (size_t y = 0; y < 240; ++y) {
      for (size_t x = 0; x < 240; ++x) {
        if (x >= 14 && x < 94 && y >= 152 && y < 236) continue;
        const size_t pixel = (y * 240 + x) * 3;
        for (size_t channel = 0; channel < 3; ++channel)
          CHECK(capture.pixels[pixel + channel] == baseline[pixel + channel]);
      }
    }
    previous = capture.pixels;
    filename = prefix + "-animation-" + std::to_string(++frame) + ".ppm";
    save(capture, filename);
  }
  timeline << filename << ',' << 24000 - previousAt << '\n';
  CHECK(timeline.good());
  CHECK(frame >= 10 && capture.pixels == baseline);
}

/** Verify manual partial refresh cannot be bypassed by the LVGL timer handler. */
void checkPartialAnimation() {
  Capture capture;
  std::array<uint8_t, 240 * 24 * 3> buffer{};
  auto* display = lv_display_create(240, 240);
  lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB888);
  lv_display_set_buffers(display, buffer.data(), nullptr, buffer.size(), LV_DISPLAY_RENDER_MODE_PARTIAL);
  lv_display_set_user_data(display, &capture);
  lv_display_set_flush_cb(display, flush);
  lv_display_delete_refr_timer(display);
  info_tv::ScreenView screen;
  screen.initialize();
  screen.render(info_tv::RenderModel{});
  lv_tick_inc(100);
  lv_timer_handler();
  CHECK(capture.pixelsFlushed == 0);
  lv_display_refr_timer(nullptr);
  CHECK(capture.pixelsFlushed == 240 * 240);
  const auto baseline = capture.pixels;
  capture.pixelsFlushed = 0;
  CHECK(screen.animate(5030));
  lv_tick_inc(100);
  lv_timer_handler();
  CHECK(capture.pixelsFlushed == 0);
  lv_display_refr_timer(nullptr);
  CHECK(capture.pixelsFlushed == 80 * 84);
  CHECK(capture.pixels != baseline);
  for (size_t y = 0; y < 240; ++y) {
    for (size_t x = 0; x < 240; ++x) {
      if (x >= 14 && x < 94 && y >= 152 && y < 236) continue;
      const size_t pixel = (y * 240 + x) * 3;
      for (size_t channel = 0; channel < 3; ++channel)
        CHECK(capture.pixels[pixel + channel] == baseline[pixel + channel]);
    }
  }
  capture.pixelsFlushed = 0;
  CHECK(!screen.animate(5040));
  lv_display_refr_timer(nullptr);
  CHECK(capture.pixelsFlushed == 0);
  CHECK(screen.animate(5170));
  lv_display_refr_timer(nullptr);
  CHECK(capture.pixelsFlushed == 80 * 84 && capture.pixels == baseline);
  lv_display_delete(display);
}

/** Capture the production font directly, including supplementary Nerd glyphs. */
void captureFontSpecimen(lv_display_t* display, Capture& capture, const std::string& prefix) {
  auto* root = lv_screen_active();
  lv_obj_clean(root);
  const char* samples[] = {"Maple Mono / 16 px", "简体：深圳鹦鹉", "繁體：龍龘臺灣",
      "Aa0O1l -> != {}", "中文，。！？（）", "かな カナ 123", "Nerd: \U000f0001 \U000f0004 \U000f012c"};
  for (size_t row = 0; row < 7; ++row) {
    auto* label = lv_label_create(root);
    lv_obj_set_pos(label, 8, 8 + row * 32);
    lv_obj_set_size(label, 224, 30);
    lv_obj_set_style_text_font(label, &font_maple_mono_16, 0);
    lv_label_set_text(label, samples[row]);
  }
  checkBounds();
  lv_refr_now(display);
  save(capture, prefix + "-font-specimen.ppm");
}
}  // namespace

/** Verify and capture overview, notification, offline, and empty widget states. */
int main(int argc, char** argv) {
  CHECK(argc == 2);
  lv_init();
  checkFontCoverage();
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
  model.weather.has_temperature_c = true;
  model.weather.temperature_c = 23;
  model.weather.condition = info_tv_v1_WeatherCondition_WEATHER_CONDITION_CLEAR;
  std::strcpy(model.weather.location, "Shanghai");
  model.weatherFresh = true;
  const char* titles[] = {"消息接口", "Login", "Unit tests", "UI review", "Deploy"};
  const char* states[] = {"waiting input", "failed", "running", "running", "completed"};
  const info_tv_v1_TaskIcon icons[] = {info_tv_v1_TaskIcon_TASK_ICON_CODE,
      info_tv_v1_TaskIcon_TASK_ICON_BUILD, info_tv_v1_TaskIcon_TASK_ICON_TEST,
      info_tv_v1_TaskIcon_TASK_ICON_REVIEW, info_tv_v1_TaskIcon_TASK_ICON_DEPLOY};
  for (size_t row = 0; row < model.rowCount; ++row) {
    model.rows[row].card = makeCard();
    auto& card = model.rows[row].card;
    std::snprintf(card.card_id, sizeof(card.card_id), "a%03u", static_cast<unsigned>(row));
    std::strcpy(card.view.source, "demo");
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
  const auto overviewModel = model;
  CHECK(hasLabel("8") && hasLabel("tasks") && hasLabel("#edf2f7 1#/3"));
  CHECK(hasLabel("2 " LV_SYMBOL_BELL));
  CHECK(hasLabel("消息接口"));
  CHECK(hasLabel("RUN") && hasLabel("WAIT") && hasLabel("FAIL"));
  CHECK(hasLabel(LV_SYMBOL_OK));
  CHECK(hasLabel("23\xc2\xb0" "C") && !hasLabel("Clear"));
  CHECK(hasLabel(LV_SYMBOL_USB) && !hasLabel("USB online"));
  CHECK(visibleBars() == 1 && visibleBars(42) == 1);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-overview.ppm");
  auto agents = model;
  const char* sources[] = {"codex", "zcode", "agy"};
  for (size_t row = 0; row < agents.rowCount; ++row) {
    std::strcpy(agents.rows[row].card.view.source, sources[row]);
    agents.rows[row].card.view.icon = info_tv_v1_TaskIcon_TASK_ICON_CODE;
  }
  screen.render(agents);
  checkBounds();
  CHECK(hasLabel("C") && hasLabel("Z") && hasLabel("A"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-agents.ppm");
  auto question = agents;
  std::strcpy(question.rows[0].card.view.content.status.text, "running");
  question.rows[0].card.view.content.status.tone = info_tv_v1_Tone_TONE_NEUTRAL;
  question.rows[0].recentQuestion = true;
  screen.render(question);
  checkBounds();
  CHECK(hasLabel("? RUN"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-recent-question.ppm");
  question.rows[0].recentQuestion = false;
  screen.render(question);
  CHECK(!hasLabel("? RUN") && hasLabel("RUN"));
  auto agentNotification = agents;
  agentNotification.kind = info_tv::RenderModel::Kind::kNotification;
  for (const auto& row : agents.rows) {
    agentNotification.view = row.card.view;
    screen.render(agentNotification);
    checkBounds();
    const char* badge = !std::strcmp(row.card.view.source, "codex") ? "C" :
        !std::strcmp(row.card.view.source, "zcode") ? "Z" : "A";
    CHECK(hasLabel(badge));
  }
  screen.render(model);
  lv_refr_now(display);
  const auto overviewPixels = capture.pixels;
  checkAnimationTiming(screen, model);
  lv_refr_now(display);
  CHECK(capture.pixels == overviewPixels);
  captureAnimation(screen, display, capture, argv[1]);
  auto sparse = model;
  sparse.rowCount = 2;
  sparse.pageIndex = 2;
  sparse.rows[0] = model.rows[2];
  std::strcpy(sparse.rows[0].card.view.title, "Docs update");
  sparse.rows[0].card.view.icon = info_tv_v1_TaskIcon_TASK_ICON_REVIEW;
  sparse.rows[0].card.view.content.status.has_progress_percent = false;
  sparse.rows[1] = model.rows[2];
  std::strcpy(sparse.rows[1].card.view.title, "Deploy");
  sparse.rows[1].card.view.icon = info_tv_v1_TaskIcon_TASK_ICON_DEPLOY;
  std::strcpy(sparse.rows[1].card.view.content.status.text, "completed");
  sparse.rows[1].card.view.content.status.tone = info_tv_v1_Tone_TONE_POSITIVE;
  sparse.rows[1].card.view.content.status.progress_percent = 100;
  screen.render(sparse);
  checkBounds();
  CHECK(!hasLabel("Unit tests") && hasLabel("#edf2f7 3#/3"));
  CHECK(hasLabel("Shanghai") && visibleBars(100) == 1);
  lv_refr_now(display);
  CHECK(std::equal(capture.pixels.begin() + 148 * 240 * 3, capture.pixels.end(),
                   overviewPixels.begin() + 148 * 240 * 3));
  save(capture, std::string(argv[1]) + "-two.ppm");
  sparse.rowCount = sparse.cardCount = 1;
  sparse.pageCount = 1;
  sparse.pageIndex = sparse.attentionCount = 0;
  screen.render(sparse);
  checkBounds();
  CHECK(!hasLabel("Login") && !hasLabel("#edf2f7 1#/1") && !hasLabel("2 " LV_SYMBOL_BELL));
  CHECK(hasLabel("1") && hasLabel("task"));
  lv_refr_now(display);
  CHECK(std::equal(capture.pixels.begin() + 148 * 240 * 3, capture.pixels.end(),
                   overviewPixels.begin() + 148 * 240 * 3));
  save(capture, std::string(argv[1]) + "-one.ppm");
  auto longModel = model;
  longModel.rowCount = 1;
  std::memset(longModel.rows[0].card.view.source, 's', 64);
  std::memset(longModel.rows[0].card.view.title, 't', 64);
  screen.render(longModel);
  checkBounds();
  CHECK(!hasLabel("Unit tests"));
  CHECK(visibleBars() == 0);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-long.ppm");
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("消息接口"));
  model.connected = false;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("RUN"));
  CHECK(visibleBars() == 0);
  CHECK(hasLabel(LV_SYMBOL_CLOSE) && !hasLabel(LV_SYMBOL_USB));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-offline.ppm");
  model.kind = info_tv::RenderModel::Kind::kNotification;
  model.connected = true;
  model.view = model.rows[0].card.view;
  std::strcpy(model.cardId, model.rows[0].card.card_id);
  std::strcpy(model.view.content.status.detail, "Return to computer.");
  screen.render(model);
  checkBounds();
  CHECK(!hasLabel("Unit tests"));
  CHECK(hasLabel("Return to computer."));
  CHECK(visibleBars() == 0);
  lv_refr_now(display);
  CHECK(std::equal(capture.pixels.begin() + 148 * 240 * 3, capture.pixels.end(),
                   overviewPixels.begin() + 148 * 240 * 3));
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
  model.cardCount = model.rowCount = model.pageCount = model.attentionCount = 0;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("No tasks yet") && !hasLabel("#edf2f7 1#/3"));
  CHECK(!hasLabel("Clear"));
  CHECK(!hasLabel("last: running"));
  CHECK(visibleBars() == 0);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-empty.ppm");
  model.weatherFresh = false;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("Stale"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-stale.ppm");
  model.weather = {};
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("Not set") && !hasLabel("23\xc2\xb0" "C"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-unavailable.ppm");
  model.kind = info_tv::RenderModel::Kind::kOverview;
  model.rowCount = model.cardCount = 3;
  model.pageCount = 1;
  model.attentionCount = 0;
  model.rows[0].card.view.icon = info_tv_v1_TaskIcon_TASK_ICON_REVIEW;
  model.rows[1].card.view.icon = info_tv_v1_TaskIcon_TASK_ICON_DEPLOY;
  model.rows[0].card.view.content.status.has_progress_percent = true;
  model.rows[0].card.view.content.status.progress_percent = 0;
  model.rows[1].card.view.content.status.has_progress_percent = true;
  model.rows[1].card.view.content.status.progress_percent = 100;
  std::strcpy(model.rows[1].card.view.content.status.text, "completed");
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("Unit tests"));
  CHECK(visibleBars() == 3);
  CHECK(visibleBars(0) == 1 && visibleBars(100) == 1);
  CHECK(hasLabel("DONE") && hasLabel(LV_SYMBOL_UPLOAD) && hasLabel(LV_SYMBOL_EYE_OPEN));
  CHECK(!hasLabel("No tasks yet") && !hasLabel("2 " LV_SYMBOL_BELL) && !hasLabel("#edf2f7 1#/1"));
  model.rows[1].card.view.content.status.tone = info_tv_v1_Tone_TONE_POSITIVE;
  std::strcpy(model.rows[2].card.view.content.status.text, "interrupted");
  model.rows[2].card.view.content.status.tone = info_tv_v1_Tone_TONE_NEUTRAL;
  model.rows[2].card.view.content.status.has_progress_percent = false;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("STOP") && hasLabel("DONE"));
  CHECK(visibleBars() == 2);
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-interrupted.ppm");
  model = overviewModel;
  model.weather.has_daily_low_c = model.weather.has_daily_high_c = true;
  model.weather.daily_low_c = 18;
  model.weather.daily_high_c = 26;
  for (int condition = 0; condition <= 6; ++condition) {
    model.weather.condition = static_cast<info_tv_v1_WeatherCondition>(condition);
    screen.render(model);
    checkBounds();
    CHECK(hasLabel("18\xc2\xb0 / 26\xc2\xb0"));
    lv_refr_now(display);
    save(capture, std::string(argv[1]) + "-weather-" + std::to_string(condition) + ".ppm");
  }
  model.weather.condition = info_tv_v1_WeatherCondition_WEATHER_CONDITION_RAIN;
  model.weatherAlert = makeWeatherAlert().envelope.body.weather_alert;
  model.weatherAlertActive = true;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("ORG Rain") && hasLabel(LV_SYMBOL_WARNING));
  CHECK(hasLabel("18\xc2\xb0 / 26\xc2\xb0"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-weather-alert.ppm");
  model.kind = info_tv::RenderModel::Kind::kNotification;
  model.weatherNotification = true;
  std::strcpy(model.view.source, "Demo");
  std::strcpy(model.view.context, "Shanghai");
  std::strcpy(model.view.title, "Rain warning");
  model.view.which_content = info_tv_v1_View_status_tag;
  model.view.content.status.tone = info_tv_v1_Tone_TONE_ATTENTION;
  std::strcpy(model.view.content.status.text, "Orange warning");
  std::strcpy(model.view.content.status.detail, "Synthetic preview only.");
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("Demo | Shanghai"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-weather-notification.ppm");
  model.kind = info_tv::RenderModel::Kind::kOverview;
  model.weatherNotification = false;
  model.weatherFresh = false;
  screen.render(model);
  CHECK(hasLabel("ORG Rain") && hasLabel("Stale"));
  model.weatherAlertActive = false;
  screen.render(model);
  CHECK(hasLabel("Stale"));
  model.weatherFresh = true;
  model.weather.daily_low_c = -100;
  model.weather.daily_high_c = 100;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("-100\xc2\xb0 / 100\xc2\xb0"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-weather-extreme.ppm");
  model = overviewModel;
  const char* chineseTitles[] = {"深圳构建", "鹦鹉接口", "龘龍测试"};
  const char* chineseStates[] = {"等待", "失败", "运行"};
  for (size_t row = 0; row < model.rowCount; ++row) {
    std::strcpy(model.rows[row].card.view.title, chineseTitles[row]);
    std::strcpy(model.rows[row].card.view.content.status.text, chineseStates[row]);
  }
  std::strcpy(model.weather.location, "深圳南山");
  model.weather.has_daily_low_c = model.weather.has_daily_high_c = true;
  model.weather.daily_low_c = 18;
  model.weather.daily_high_c = 26;
  model.weatherAlert = makeWeatherAlert().envelope.body.weather_alert;
  std::strcpy(model.weatherAlert.title, "暴雨");
  model.weatherAlertActive = true;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("深圳构建") && hasLabel("深圳南山"));
  CHECK(hasLabel("等待") && hasLabel("ORG 暴雨"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-chinese-overview.ppm");
  model.kind = info_tv::RenderModel::Kind::kNotification;
  model.view = model.rows[2].card.view;
  std::strcpy(model.cardId, "c003");
  std::strcpy(model.view.source, "助手");
  std::strcpy(model.view.context, "字库");
  std::strcpy(model.view.content.status.text, "正在编译");
  std::strcpy(model.view.content.status.detail, "鹦鹉：兼容繁體龍龘");
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("助手 #c003 | 字库") && hasLabel("正在编译 42%"));
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-chinese-notification.ppm");
  std::strcpy(model.view.title, "检查中文省略号和裁切的长标题");
  std::strcpy(model.view.content.status.detail, "长文本应保持在气泡内部");
  screen.render(model);
  checkBounds();
  lv_refr_now(display);
  save(capture, std::string(argv[1]) + "-chinese-long.ppm");
  model.view = model.rows[0].card.view;
  screen.render(model);
  checkBounds();
  CHECK(hasLabel("深圳构建"));
  captureFontSpecimen(display, capture, argv[1]);
  lv_display_delete(display);
  checkPartialAnimation();
  lv_deinit();
}
