#include "ui/screen_view.h"

#include <cstdio>
#include <cstring>

extern "C" {
LV_FONT_DECLARE(font_maple_mono_16);
LV_IMAGE_DECLARE(whale_idle);
LV_IMAGE_DECLARE(whale_closed);
LV_IMAGE_DECLARE(whale_shift_0);
LV_IMAGE_DECLARE(whale_shift_1);
LV_IMAGE_DECLARE(whale_shift_2);
LV_IMAGE_DECLARE(whale_shift_3);
}

namespace info_tv {
namespace {
/** Map a reported state to a readable foreground accent. */
uint32_t toneColor(info_tv_v1_Tone tone) {
  switch (tone) {
    case info_tv_v1_Tone_TONE_ATTENTION: return 0xffcf7a;
    case info_tv_v1_Tone_TONE_POSITIVE: return 0x82dcb4;
    case info_tv_v1_Tone_TONE_NEGATIVE: return 0xff9b9b;
    default: return 0x8bc5ff;
  }
}

/** Keep status color confined to compact labels, icons, and progress. */
uint32_t badgeColor(info_tv_v1_Tone tone) {
  switch (tone) {
    case info_tv_v1_Tone_TONE_ATTENTION: return 0x302718;
    case info_tv_v1_Tone_TONE_POSITIVE: return 0x183029;
    case info_tv_v1_Tone_TONE_NEGATIVE: return 0x342128;
    default: return 0x1c2e43;
  }
}

/** Resolve the fixed icon catalog using bundled LVGL symbol glyphs. */
const char* iconSymbol(info_tv_v1_TaskIcon icon) {
  switch (icon) {
    case info_tv_v1_TaskIcon_TASK_ICON_CODE: return LV_SYMBOL_EDIT;
    case info_tv_v1_TaskIcon_TASK_ICON_TEST: return LV_SYMBOL_OK;
    case info_tv_v1_TaskIcon_TASK_ICON_BUILD: return LV_SYMBOL_SETTINGS;
    case info_tv_v1_TaskIcon_TASK_ICON_REVIEW: return LV_SYMBOL_EYE_OPEN;
    case info_tv_v1_TaskIcon_TASK_ICON_DEPLOY: return LV_SYMBOL_UPLOAD;
    default: return LV_SYMBOL_LIST;
  }
}

/** Shorten known task states while preserving other valid status text. */
const char* compactState(const char* text) {
  if (!std::strcmp(text, "running")) return "RUN";
  if (!std::strcmp(text, "waiting input")) return "WAIT";
  if (!std::strcmp(text, "completed")) return "DONE";
  if (!std::strcmp(text, "failed")) return "FAIL";
  if (!std::strcmp(text, "interrupted")) return "STOP";
  return text;
}

/** Sample upstream idle poses by elapsed time, skipping missed frames. */
const lv_image_dsc_t* companionFrame(uint64_t nowMs) {
  const lv_image_dsc_t* shifts[] = {&whale_shift_0, &whale_shift_1, &whale_shift_2,
      &whale_shift_3, &whale_shift_2, &whale_shift_1, &whale_shift_0};
  const uint32_t durations[] = {75, 80, 90, 100, 90, 80, 100};
  const uint32_t phase = nowMs % 24000;
  if (phase >= 15000) {
    uint32_t elapsed = phase - 15000;
    for (size_t index = 0; index < 7; ++index) {
      if (elapsed < durations[index]) return shifts[index];
      elapsed -= durations[index];
    }
  }
  // Upstream's irregular blink intervals; the discrete closed pose lasts 140 ms.
  const uint32_t intervals[] = {5200, 7100, 4300, 8600, 6100};
  uint32_t elapsed = nowMs % 31300;
  for (const auto interval : intervals) {
    if (elapsed < interval)
      return elapsed >= interval - 170 && elapsed < interval - 30 ? &whale_closed : &whale_idle;
    elapsed -= interval;
  }
  return &whale_idle;
}
}  // namespace

lv_obj_t* ScreenView::label(lv_obj_t* parent, int x, int y, int width, int height) {
  auto* object = lv_label_create(parent);
  lv_obj_set_pos(object, x, y);
  lv_obj_set_size(object, width, height);
  lv_label_set_long_mode(object, LV_LABEL_LONG_DOT);
  return object;
}

lv_obj_t* ScreenView::bubble(int y, int height) {
  auto* object = lv_obj_create(lv_screen_active());
  lv_obj_remove_style_all(object);
  lv_obj_set_pos(object, 12, y);
  lv_obj_set_size(object, 218, height);
  lv_obj_set_style_radius(object, 12, 0);
  lv_obj_set_style_bg_color(object, lv_color_hex(0x131c28), 0);
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(object, 1, 0);
  lv_obj_set_style_border_color(object, lv_color_hex(0x273446), 0);
  lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
  return object;
}

lv_obj_t* ScreenView::progressBar(lv_obj_t* parent, int x, int y, int width) {
  auto* object = lv_bar_create(parent);
  lv_obj_remove_style_all(object);
  lv_obj_set_pos(object, x, y);
  lv_obj_set_size(object, width, 2);
  lv_obj_set_style_bg_color(object, lv_color_hex(0x0a1018), 0);
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(object, 2, 0);
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, LV_PART_INDICATOR);
  lv_obj_set_style_radius(object, 2, LV_PART_INDICATOR);
  lv_bar_set_range(object, 0, 100);
  return object;
}

void ScreenView::drawWeatherIcon(lv_event_t* event) {
  const auto& view = *static_cast<ScreenView*>(lv_event_get_user_data(event));
  auto* layer = lv_event_get_layer(event);
  lv_area_t origin;
  lv_obj_get_coords(view.weatherIcon_, &origin);
  /** Paint one rounded shape relative to the icon's bounds. */
  const auto shape = [&](int x, int y, int width, int height, int radius, uint32_t color) {
    lv_draw_rect_dsc_t descriptor;
    lv_draw_rect_dsc_init(&descriptor);
    descriptor.bg_color = lv_color_hex(view.weatherIconFresh_ ? color : 0x718093);
    descriptor.radius = radius;
    lv_area_t area = {origin.x1 + x, origin.y1 + y, origin.x1 + x + width - 1, origin.y1 + y + height - 1};
    lv_draw_rect(layer, &descriptor, &area);
  };
  /** Paint a rounded stroke inside the icon. */
  const auto stroke = [&](int x1, int y1, int x2, int y2, uint32_t color) {
    lv_draw_line_dsc_t descriptor;
    lv_draw_line_dsc_init(&descriptor);
    descriptor.p1 = {origin.x1 + x1, origin.y1 + y1};
    descriptor.p2 = {origin.x1 + x2, origin.y1 + y2};
    descriptor.color = lv_color_hex(view.weatherIconFresh_ ? color : 0x718093);
    descriptor.width = 2;
    descriptor.round_start = descriptor.round_end = true;
    lv_draw_line(layer, &descriptor);
  };
  const auto condition = view.weatherCondition_;
  if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_CLEAR) {
    shape(11, 8, 11, 11, LV_RADIUS_CIRCLE, 0xffcf7a);
    const int rays[][4] = {{16, 1, 16, 4}, {16, 23, 16, 26}, {4, 13, 7, 13}, {26, 13, 29, 13},
        {7, 4, 9, 6}, {24, 21, 26, 23}, {7, 23, 9, 21}, {24, 6, 26, 4}};
    for (const auto& ray : rays) stroke(ray[0], ray[1], ray[2], ray[3], 0xffcf7a);
    return;
  }
  if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_UNKNOWN) {
    stroke(12, 7, 17, 5, 0x9baabd);
    stroke(17, 5, 21, 9, 0x9baabd);
    stroke(21, 9, 16, 15, 0x9baabd);
    stroke(16, 15, 16, 17, 0x9baabd);
    shape(15, 22, 3, 3, LV_RADIUS_CIRCLE, 0x9baabd);
    return;
  }
  shape(10, 4, 15, 15, LV_RADIUS_CIRCLE, 0xc6d6e8);
  shape(3, 10, 13, 11, LV_RADIUS_CIRCLE, 0x9fb6d0);
  shape(10, 12, 20, 9, 5, 0xc6d6e8);
  if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_RAIN) {
    for (int x : {9, 17, 25}) stroke(x, 23, x - 2, 26, 0x8bc5ff);
  } else if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_SNOW) {
    stroke(16, 22, 16, 27, 0xb8e4ff);
    stroke(13, 23, 19, 26, 0xb8e4ff);
    stroke(13, 26, 19, 23, 0xb8e4ff);
  } else if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_STORM) {
    stroke(18, 21, 14, 24, 0xffcf7a);
    stroke(14, 24, 18, 24, 0xffcf7a);
    stroke(18, 24, 14, 27, 0xffcf7a);
  } else if (condition == info_tv_v1_WeatherCondition_WEATHER_CONDITION_FOG) {
    stroke(4, 23, 27, 23, 0x9fb6d0);
    stroke(9, 27, 23, 27, 0x9fb6d0);
  }
}

void ScreenView::initialize() {
  auto* screen = lv_screen_active();
  lv_obj_set_style_bg_color(screen, lv_color_hex(0x000000), 0);
  lv_obj_set_style_text_color(screen, lv_color_hex(0xf0f4f8), 0);
  lv_obj_set_style_text_font(screen, &font_maple_mono_16, 0);
  lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  smallFont_ = lv_font_montserrat_14;
  smallFont_.fallback = &font_maple_mono_16;
  // Reserve the full CJK fallback ink height and align its baseline with metadata.
  smallFont_.line_height = 18;
  smallFont_.base_line = 2;
  header_ = label(screen, 12, 5, 12, 20);
  lv_obj_set_style_text_font(header_, &lv_font_montserrat_16, 0);
  headerUnit_ = label(screen, 28, 7, 50, 18);
  lv_obj_set_style_text_font(headerUnit_, &smallFont_, 0);
  lv_obj_set_style_text_color(headerUnit_, lv_color_hex(0x8998ab), 0);
  summary_ = label(screen, 111, 5, 46, 20);
  lv_obj_set_style_text_font(summary_, &smallFont_, 0);
  lv_obj_set_style_text_align(summary_, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_pad_top(summary_, 2, 0);
  lv_obj_set_style_radius(summary_, 7, 0);
  lv_obj_set_style_bg_color(summary_, lv_color_hex(0x302718), 0);
  lv_obj_set_style_bg_opa(summary_, LV_OPA_COVER, 0);
  lv_obj_set_style_text_color(summary_, lv_color_hex(0xffcf7a), 0);
  message_ = bubble(29, 110);
  icon_ = label(message_, 10, 5, 18, 20);
  lv_obj_set_style_text_font(icon_, &lv_font_montserrat_16, 0);
  sender_ = label(message_, 34, 5, 174, 20);
  lv_obj_set_style_text_font(sender_, &smallFont_, 0);
  lv_obj_set_style_text_color(sender_, lv_color_hex(0xb1bdcb), 0);
  title_ = label(message_, 10, 21, 198, 30);
  status_ = label(message_, 10, 46, 198, 30);
  detail_ = label(message_, 10, 71, 198, 30);
  lv_obj_set_style_text_color(detail_, lv_color_hex(0xc7d2df), 0);
  progress_ = progressBar(message_, 10, 102, 198);
  empty_ = label(screen, 12, 59, 216, 30);
  lv_label_set_text(empty_, "No tasks yet");
  lv_obj_set_style_text_align(empty_, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_color(empty_, lv_color_hex(0x9baabd), 0);
  character_ = lv_image_create(screen);
  characterFrame_ = &whale_idle;
  lv_image_set_src(character_, characterFrame_);
  lv_obj_set_pos(character_, 14, 152);
  location_ = label(screen, 106, 145, 122, 30);
  temperature_ = label(screen, 106, 174, 86, 22);
  lv_obj_set_style_text_font(temperature_, &lv_font_montserrat_16, 0);
  conditions_ = label(screen, 106, 198, 122, 18);
  weatherDetails_ = label(screen, 124, 220, 104, 18);
  lv_obj_set_style_text_font(weatherDetails_, &smallFont_, 0);
  weatherIcon_ = lv_obj_create(screen);
  lv_obj_remove_style_all(weatherIcon_);
  lv_obj_set_pos(weatherIcon_, 196, 169);
  lv_obj_set_size(weatherIcon_, 32, 29);
  lv_obj_remove_flag(weatherIcon_, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_event_cb(weatherIcon_, drawWeatherIcon, LV_EVENT_DRAW_MAIN, this);
  weatherAlertIcon_ = label(screen, 106, 220, 16, 18);
  lv_obj_set_style_text_font(weatherAlertIcon_, &smallFont_, 0);
  lv_label_set_text(weatherAlertIcon_, LV_SYMBOL_WARNING);
  lv_obj_set_style_text_font(conditions_, &smallFont_, 0);
  lv_obj_set_style_text_color(location_, lv_color_hex(0xb1bdcb), 0);
  lv_obj_set_style_text_color(conditions_, lv_color_hex(0x9baabd), 0);
  connection_ = label(screen, 176, 7, 16, 18);
  lv_obj_set_style_text_font(connection_, &smallFont_, 0);
  lv_obj_set_style_text_align(connection_, LV_TEXT_ALIGN_CENTER, 0);
  page_ = label(screen, 197, 7, 31, 18);
  lv_label_set_recolor(page_, true);
  lv_obj_set_style_text_font(page_, &smallFont_, 0);
  lv_obj_set_style_text_color(page_, lv_color_hex(0x9baabd), 0);
  lv_obj_set_style_text_align(page_, LV_TEXT_ALIGN_RIGHT, 0);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    rowBubbles_[row] = bubble(29 + row * 38, 34);
    rowIcons_[row] = label(rowBubbles_[row], 10, 6, 18, 20);
    lv_obj_set_style_text_font(rowIcons_[row], &lv_font_montserrat_16, 0);
    rowTitles_[row] = label(rowBubbles_[row], 34, 0, 120, 30);
    rowDetails_[row] = label(rowBubbles_[row], 158, 5, 48, 21);
    lv_obj_set_style_text_font(rowDetails_[row], &smallFont_, 0);
    lv_obj_set_style_text_align(rowDetails_[row], LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_pad_top(rowDetails_[row], 3, 0);
    lv_obj_set_style_radius(rowDetails_[row], 6, 0);
    lv_obj_set_style_bg_opa(rowDetails_[row], LV_OPA_COVER, 0);
    rowProgress_[row] = progressBar(rowBubbles_[row], 34, 28, 174);
  }
}

bool ScreenView::animate(uint64_t nowMs) {
  const auto* frame = companionFrame(nowMs);
  if (frame == characterFrame_) return false;
  characterFrame_ = frame;
  lv_image_set_src(character_, frame);
  return true;
}

void ScreenView::render(const RenderModel& model) {
  // Use set_text after formatting: LVGL 9.3 set_text_fmt can restore old DOT
  // characters into a replacement string when the previous label was truncated.
  char text[256];
  const bool notification = model.kind == RenderModel::Kind::kNotification;
  const bool overview = model.kind == RenderModel::Kind::kOverview;
  lv_obj_add_flag(empty_, LV_OBJ_FLAG_HIDDEN);
  for (auto* object : {message_, progress_})
    lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    lv_obj_add_flag(rowBubbles_[row], LV_OBJ_FLAG_HIDDEN);
  }
  std::snprintf(text, sizeof(text), "%u", static_cast<unsigned>(model.cardCount));
  lv_label_set_text(header_, text);
  lv_label_set_text(headerUnit_, model.cardCount == 1 ? "task" : "tasks");
  lv_obj_add_flag(summary_, LV_OBJ_FLAG_HIDDEN);
  if (model.attentionCount) {
    lv_obj_remove_flag(summary_, LV_OBJ_FLAG_HIDDEN);
    std::snprintf(text, sizeof(text), "%u " LV_SYMBOL_BELL,
                  static_cast<unsigned>(model.attentionCount));
    lv_label_set_text(summary_, text);
  }
  if (overview) {
    for (size_t row = 0; row < model.rowCount; ++row) {
      const auto& view = model.rows[row].card.view;
      const auto& status = view.content.status;
      lv_obj_remove_flag(rowBubbles_[row], LV_OBJ_FLAG_HIDDEN);
      lv_label_set_text(rowIcons_[row], iconSymbol(view.icon));
      lv_label_set_text(rowTitles_[row], view.title);
      lv_label_set_text(rowDetails_[row], compactState(status.text));
      const auto color = lv_color_hex(model.connected ? toneColor(status.tone) : 0xb1bdcb);
      lv_obj_set_style_text_color(rowDetails_[row], color, 0);
      lv_obj_set_style_text_color(rowIcons_[row], color, 0);
      lv_obj_set_style_bg_color(rowDetails_[row],
          lv_color_hex(model.connected ? badgeColor(status.tone) : 0x252d37), 0);
      lv_obj_set_style_text_color(rowTitles_[row], lv_color_hex(
          !model.connected || status.tone == info_tv_v1_Tone_TONE_POSITIVE ? 0xaab7c7 : 0xedf2f7), 0);
      lv_obj_add_flag(rowProgress_[row], LV_OBJ_FLAG_HIDDEN);
      if (status.has_progress_percent && model.connected) {
        lv_obj_remove_flag(rowProgress_[row], LV_OBJ_FLAG_HIDDEN);
        lv_bar_set_value(rowProgress_[row], status.progress_percent, LV_ANIM_OFF);
        lv_obj_set_style_bg_color(rowProgress_[row], color, LV_PART_INDICATOR);
      }
    }
  }
  if (model.kind == RenderModel::Kind::kEmpty) {
    lv_obj_remove_flag(empty_, LV_OBJ_FLAG_HIDDEN);
  } else if (notification) {
    lv_obj_remove_flag(message_, LV_OBJ_FLAG_HIDDEN);
    const auto& status = model.view.content.status;
    if (model.weatherNotification)
      std::snprintf(text, sizeof(text), "%s | %s", model.view.source, model.view.context);
    else
      std::snprintf(text, sizeof(text), "%s #%.4s%s%s", model.view.source, model.cardId,
                    model.view.context[0] ? " | " : "", model.view.context);
    lv_label_set_text(sender_, text);
    lv_label_set_text(icon_, model.weatherNotification ? LV_SYMBOL_WARNING : iconSymbol(model.view.icon));
    lv_label_set_text(title_, model.view.title);
    std::snprintf(text, sizeof(text), "%s%s", model.connected ? "" : "last: ", status.text);
    if (status.has_progress_percent && model.connected)
      std::snprintf(text, sizeof(text), "%s %u%%", status.text,
                    static_cast<unsigned>(status.progress_percent));
    lv_label_set_text(status_, text);
    lv_label_set_text(detail_, status.detail);
    const auto color = lv_color_hex(model.connected ? toneColor(status.tone) : 0xb1bdcb);
    lv_obj_set_style_text_color(status_, color, 0);
    lv_obj_set_style_text_color(icon_, color, 0);
    if (status.has_progress_percent && model.connected) {
      lv_obj_remove_flag(progress_, LV_OBJ_FLAG_HIDDEN);
      lv_bar_set_value(progress_, status.progress_percent, LV_ANIM_OFF);
      lv_obj_set_style_bg_color(progress_, color, LV_PART_INDICATOR);
    }
  }
  lv_label_set_text(connection_, model.connected ? LV_SYMBOL_USB : LV_SYMBOL_CLOSE);
  lv_obj_set_style_text_color(connection_, lv_color_hex(model.connected ? 0x82dcb4 : 0x718093), 0);
  const auto& weather = model.weather;
  lv_label_set_text(location_, weather.has_temperature_c ? weather.location :
      model.weatherAlertActive ? model.weatherAlert.location : "Weather");
  weatherCondition_ = weather.condition;
  weatherIconFresh_ = model.weatherFresh;
  lv_obj_add_flag(weatherIcon_, LV_OBJ_FLAG_HIDDEN);
  lv_obj_add_flag(conditions_, LV_OBJ_FLAG_HIDDEN);
  lv_obj_add_flag(weatherDetails_, LV_OBJ_FLAG_HIDDEN);
  if (weather.has_temperature_c) {
    lv_obj_remove_flag(weatherIcon_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_invalidate(weatherIcon_);
    std::snprintf(text, sizeof(text), "%ld\xc2\xb0" "C", static_cast<long>(weather.temperature_c));
    lv_label_set_text(temperature_, text);
    if (model.weatherFresh && weather.has_daily_low_c && weather.has_daily_high_c) {
      std::snprintf(text, sizeof(text), "%d\xc2\xb0 / %d\xc2\xb0",
                    static_cast<int>(weather.daily_low_c), static_cast<int>(weather.daily_high_c));
      lv_label_set_text(conditions_, text);
      lv_obj_remove_flag(conditions_, LV_OBJ_FLAG_HIDDEN);
    } else if (!model.weatherFresh) {
      lv_label_set_text(conditions_, "Stale");
      lv_obj_remove_flag(conditions_, LV_OBJ_FLAG_HIDDEN);
    }
  } else {
    lv_label_set_text(temperature_, "--\xc2\xb0" "C");
    lv_label_set_text(conditions_, "Not set");
    lv_obj_remove_flag(conditions_, LV_OBJ_FLAG_HIDDEN);
  }
  lv_obj_add_flag(weatherAlertIcon_, LV_OBJ_FLAG_HIDDEN);
  if (model.weatherAlertActive) {
    const auto severity = model.weatherAlert.severity;
    const char* levels[] = {"", "BLU", "YLW", "ORG", "RED"};
    const uint32_t colors[] = {0, 0x8bc5ff, 0xffdf7a, 0xffb16b, 0xff9b9b};
    std::snprintf(text, sizeof(text), "%s %s", levels[severity], model.weatherAlert.title);
    lv_label_set_text(weatherDetails_, text);
    lv_obj_remove_flag(weatherDetails_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(weatherAlertIcon_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_text_color(weatherDetails_, lv_color_hex(colors[severity]), 0);
    lv_obj_set_style_text_color(weatherAlertIcon_, lv_color_hex(colors[severity]), 0);
  }
  lv_obj_set_style_text_color(temperature_, lv_color_hex(model.weatherFresh ? 0xf0f4f8 : 0x9baabd), 0);
  if (overview && model.pageCount > 1) {
    std::snprintf(text, sizeof(text), "#edf2f7 %u#/%u",
                  static_cast<unsigned>(model.pageIndex + (model.pageCount ? 1 : 0)),
                  static_cast<unsigned>(model.pageCount));
    lv_label_set_text(page_, text);
  } else {
    lv_label_set_text(page_, "");
  }
}
}  // namespace info_tv
