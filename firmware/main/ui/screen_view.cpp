#include "ui/screen_view.h"

#include <cstdio>
#include <cstring>

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

/** Tint the message surface without relying on color to describe its state. */
uint32_t bubbleColor(info_tv_v1_Tone tone) {
  switch (tone) {
    case info_tv_v1_Tone_TONE_ATTENTION: return 0x332c22;
    case info_tv_v1_Tone_TONE_POSITIVE: return 0x20332e;
    case info_tv_v1_Tone_TONE_NEGATIVE: return 0x35262d;
    default: return 0x1e2c3e;
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
  return text;
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
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
  lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
  return object;
}

lv_obj_t* ScreenView::progressBar(lv_obj_t* parent, int x, int y, int width) {
  auto* object = lv_bar_create(parent);
  lv_obj_remove_style_all(object);
  lv_obj_set_pos(object, x, y);
  lv_obj_set_size(object, width, 3);
  lv_obj_set_style_bg_color(object, lv_color_hex(0x101820), 0);
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(object, 2, 0);
  lv_obj_set_style_bg_opa(object, LV_OPA_COVER, LV_PART_INDICATOR);
  lv_obj_set_style_radius(object, 2, LV_PART_INDICATOR);
  lv_bar_set_range(object, 0, 100);
  return object;
}

void ScreenView::initialize() {
  auto* screen = lv_screen_active();
  lv_obj_set_style_bg_color(screen, lv_color_hex(0x000000), 0);
  lv_obj_set_style_text_color(screen, lv_color_hex(0xf0f4f8), 0);
  lv_obj_set_style_text_font(screen, &lv_font_source_han_sans_sc_16_cjk, 0);
  lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  smallFont_ = lv_font_montserrat_14;
  smallFont_.fallback = &lv_font_source_han_sans_sc_16_cjk;
  header_ = label(screen, 12, 5, 110, 20);
  summary_ = label(screen, 124, 7, 104, 18);
  lv_obj_set_style_text_font(summary_, &smallFont_, 0);
  lv_obj_set_style_text_align(summary_, LV_TEXT_ALIGN_RIGHT, 0);
  message_ = bubble(37, 175);
  icon_ = label(message_, 10, 9, 18, 20);
  lv_obj_set_style_text_font(icon_, &lv_font_montserrat_16, 0);
  sender_ = label(message_, 34, 9, 174, 20);
  lv_obj_set_style_text_font(sender_, &smallFont_, 0);
  lv_obj_set_style_text_color(sender_, lv_color_hex(0xb1bdcb), 0);
  title_ = label(message_, 10, 34, 198, 44);
  status_ = label(message_, 10, 82, 198, 22);
  detail_ = label(message_, 10, 108, 198, 44);
  lv_obj_set_style_text_color(detail_, lv_color_hex(0xc7d2df), 0);
  progress_ = progressBar(message_, 10, 160, 198);
  connection_ = lv_obj_create(screen);
  lv_obj_remove_style_all(connection_);
  lv_obj_set_pos(connection_, 12, 226);
  lv_obj_set_size(connection_, 5, 5);
  lv_obj_set_style_radius(connection_, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_opa(connection_, LV_OPA_COVER, 0);
  footer_ = label(screen, 23, 220, 174, 20);
  page_ = label(screen, 197, 220, 31, 20);
  for (auto* object : {footer_, page_}) {
    lv_obj_set_style_text_font(object, &smallFont_, 0);
    lv_obj_set_style_text_color(object, lv_color_hex(0x9baabd), 0);
  }
  lv_obj_set_style_text_align(page_, LV_TEXT_ALIGN_RIGHT, 0);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    rowBubbles_[row] = bubble(29 + row * 38, 34);
    rowIcons_[row] = label(rowBubbles_[row], 10, 6, 18, 20);
    lv_obj_set_style_text_font(rowIcons_[row], &lv_font_montserrat_16, 0);
    rowTitles_[row] = label(rowBubbles_[row], 34, 5, 120, 20);
    rowDetails_[row] = label(rowBubbles_[row], 158, 7, 50, 20);
    lv_obj_set_style_text_font(rowDetails_[row], &smallFont_, 0);
    lv_obj_set_style_text_align(rowDetails_[row], LV_TEXT_ALIGN_RIGHT, 0);
    rowProgress_[row] = progressBar(rowBubbles_[row], 34, 28, 174);
  }
}

void ScreenView::render(const RenderModel& model) {
  // Use set_text after formatting: LVGL 9.3 set_text_fmt can restore old DOT
  // characters into a replacement string when the previous label was truncated.
  char text[256];
  const bool notification = model.kind == RenderModel::Kind::kNotification;
  const bool overview = model.kind == RenderModel::Kind::kOverview;
  for (auto* object : {message_, progress_})
    lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    lv_obj_add_flag(rowBubbles_[row], LV_OBJ_FLAG_HIDDEN);
  }
  lv_label_set_text(header_, notification ? "New message" : "Messages");
  lv_label_set_text(summary_, "");
  if (overview) {
    std::snprintf(text, sizeof(text), "%u sessions", static_cast<unsigned>(model.cardCount));
    lv_label_set_text(header_, text);
    std::snprintf(text, sizeof(text), "%u need you", static_cast<unsigned>(model.attentionCount));
    lv_label_set_text(summary_, text);
    lv_obj_set_style_text_color(summary_, lv_color_hex(model.attentionCount ? 0xffcf7a : 0x9baabd), 0);
    for (size_t row = 0; row < model.rowCount; ++row) {
      const auto& view = model.rows[row].card.view;
      const auto& status = view.content.status;
      const auto background = lv_color_hex(model.connected ? bubbleColor(status.tone) : 0x222b35);
      lv_obj_remove_flag(rowBubbles_[row], LV_OBJ_FLAG_HIDDEN);
      lv_obj_set_style_bg_color(rowBubbles_[row], background, 0);
      lv_label_set_text(rowIcons_[row], iconSymbol(view.icon));
      lv_label_set_text(rowTitles_[row], view.title);
      lv_label_set_text(rowDetails_[row], compactState(status.text));
      const auto color = lv_color_hex(model.connected ? toneColor(status.tone) : 0xb1bdcb);
      lv_obj_set_style_text_color(rowDetails_[row], color, 0);
      lv_obj_set_style_text_color(rowIcons_[row], color, 0);
      lv_obj_add_flag(rowProgress_[row], LV_OBJ_FLAG_HIDDEN);
      if (status.has_progress_percent && model.connected) {
        lv_obj_remove_flag(rowProgress_[row], LV_OBJ_FLAG_HIDDEN);
        lv_bar_set_value(rowProgress_[row], status.progress_percent, LV_ANIM_OFF);
        lv_obj_set_style_bg_color(rowProgress_[row], color, LV_PART_INDICATOR);
      }
    }
  } else {
    lv_obj_remove_flag(message_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(message_, lv_color_hex(0x1e2c3e), 0);
    lv_obj_set_style_text_color(status_, lv_color_hex(0x8bc5ff), 0);
  }
  if (model.kind == RenderModel::Kind::kEmpty) {
    lv_label_set_text(icon_, iconSymbol(info_tv_v1_TaskIcon_TASK_ICON_TASK));
    lv_obj_set_style_text_color(icon_, lv_color_hex(0x8bc5ff), 0);
    lv_label_set_text(sender_, "INFO TV");
    lv_label_set_text(title_, "Ready for tasks");
    lv_label_set_text(status_, model.connected ? "No messages yet" : "Waiting for host");
    lv_label_set_text(detail_, "Submit a task through the local service.");
  } else if (notification) {
    const auto& status = model.view.content.status;
    std::snprintf(text, sizeof(text), "%s #%.4s%s%s", model.view.source, model.cardId,
                  model.view.context[0] ? " | " : "", model.view.context);
    lv_label_set_text(sender_, text);
    lv_label_set_text(icon_, iconSymbol(model.view.icon));
    lv_label_set_text(title_, model.view.title);
    std::snprintf(text, sizeof(text), "%s%s", model.connected ? "" : "last: ", status.text);
    if (status.has_progress_percent && model.connected)
      std::snprintf(text, sizeof(text), "%s %u%%", status.text,
                    static_cast<unsigned>(status.progress_percent));
    lv_label_set_text(status_, text);
    lv_label_set_text(detail_, status.detail);
    const auto color = lv_color_hex(model.connected ? toneColor(status.tone) : 0xb1bdcb);
    const auto background = lv_color_hex(model.connected ? bubbleColor(status.tone) : 0x222b35);
    lv_obj_set_style_bg_color(message_, background, 0);
    lv_obj_set_style_text_color(status_, color, 0);
    lv_obj_set_style_text_color(icon_, color, 0);
    if (status.has_progress_percent && model.connected) {
      lv_obj_remove_flag(progress_, LV_OBJ_FLAG_HIDDEN);
      lv_bar_set_value(progress_, status.progress_percent, LV_ANIM_OFF);
      lv_obj_set_style_bg_color(progress_, color, LV_PART_INDICATOR);
    }
  }
  lv_obj_set_style_bg_color(connection_, lv_color_hex(model.connected ? 0x82dcb4 : 0xffcf7a), 0);
  lv_label_set_text(footer_, !model.connected ? "Offline | last state" :
                    notification ? "Returns to overview" : "USB online");
  if (overview) {
    std::snprintf(text, sizeof(text), "%u/%u",
                  static_cast<unsigned>(model.pageIndex + (model.pageCount ? 1 : 0)),
                  static_cast<unsigned>(model.pageCount));
    lv_label_set_text(page_, text);
  } else {
    lv_label_set_text(page_, "");
  }
}
}  // namespace info_tv
