#include "ui/screen_view.h"

#include <cstdio>

namespace info_tv {
lv_obj_t* ScreenView::label(int x, int y, int width, int height) {
  auto* object = lv_label_create(lv_screen_active());
  lv_obj_set_pos(object, x, y);
  lv_obj_set_size(object, width, height);
  lv_label_set_long_mode(object, LV_LABEL_LONG_DOT);
  return object;
}

void ScreenView::initialize() {
  auto* screen = lv_screen_active();
  lv_obj_set_style_bg_color(screen, lv_color_hex(0x101820), 0);
  lv_obj_set_style_text_color(screen, lv_color_hex(0xf0f4f8), 0);
  lv_obj_set_style_text_font(screen, &lv_font_source_han_sans_sc_16_cjk, 0);
  lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  header_ = label(12, 10, 216, 20);
  title_ = label(12, 42, 216, 44);
  status_ = label(12, 92, 216, 22);
  detail_ = label(12, 124, 216, 48);
  progress_ = lv_bar_create(screen);
  lv_obj_set_pos(progress_, 12, 187);
  lv_obj_set_size(progress_, 216, 8);
  lv_bar_set_range(progress_, 0, 100);
  footer_ = label(12, 211, 216, 20);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    rowTitles_[row] = label(12, 42 + row * 53, 216, 21);
    rowDetails_[row] = label(12, 64 + row * 53, 216, 21);
  }
}

void ScreenView::render(const RenderModel& model) {
  // Use set_text after formatting: LVGL 9.3 set_text_fmt can restore old DOT
  // characters into a replacement string when the previous label was truncated.
  char text[256];
  const bool notification = model.kind == RenderModel::Kind::kNotification;
  const bool overview = model.kind == RenderModel::Kind::kOverview;
  for (auto* object : {title_, status_, detail_, progress_})
    lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
  for (size_t row = 0; row < policy::kRowsPerPage; ++row) {
    lv_obj_add_flag(rowTitles_[row], LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(rowDetails_[row], LV_OBJ_FLAG_HIDDEN);
  }
  lv_label_set_text(header_, notification ? "NOTIFICATION" : "INFO TV");
  if (overview) {
    std::snprintf(text, sizeof(text), "%u sessions | %u need you",
                  static_cast<unsigned>(model.cardCount), static_cast<unsigned>(model.attentionCount));
    lv_label_set_text(header_, text);
    for (size_t row = 0; row < model.rowCount; ++row) {
      const auto& view = model.rows[row].card.view;
      const auto& status = view.content.status;
      lv_obj_remove_flag(rowTitles_[row], LV_OBJ_FLAG_HIDDEN);
      lv_obj_remove_flag(rowDetails_[row], LV_OBJ_FLAG_HIDDEN);
      std::snprintf(text, sizeof(text), "%s #%.4s | %s", view.source,
                    model.rows[row].card.card_id, view.title);
      lv_label_set_text(rowTitles_[row], text);
      std::snprintf(text, sizeof(text), "%s%s%s%s", view.context,
                    view.context[0] ? " | " : "", model.connected ? "" : "last: ", status.text);
      if (status.has_progress_percent && model.connected) {
        std::snprintf(text, sizeof(text), "%s%s%s %u%%", view.context,
                      view.context[0] ? " | " : "", status.text,
                      static_cast<unsigned>(status.progress_percent));
      }
      lv_label_set_text(rowDetails_[row], text);
      uint32_t color = 0x69b7ff;
      if (status.tone == info_tv_v1_Tone_TONE_ATTENTION) color = 0xffc857;
      if (status.tone == info_tv_v1_Tone_TONE_POSITIVE) color = 0x67db99;
      if (status.tone == info_tv_v1_Tone_TONE_NEGATIVE) color = 0xff7777;
      lv_obj_set_style_text_color(rowDetails_[row], lv_color_hex(color), 0);
    }
  } else {
    lv_obj_remove_flag(title_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(status_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(detail_, LV_OBJ_FLAG_HIDDEN);
  }
  if (model.kind == RenderModel::Kind::kEmpty) {
    lv_label_set_text(title_, "Ready for tasks");
    lv_label_set_text(status_, "Waiting for host");
    lv_label_set_text(detail_, "Submit a task through the local service.");
    lv_obj_add_flag(progress_, LV_OBJ_FLAG_HIDDEN);
  } else if (notification) {
    const auto& status = model.view.content.status;
    std::snprintf(text, sizeof(text), "%s #%.4s%s%s", model.view.source, model.cardId,
                  model.view.context[0] ? " | " : "", model.view.context);
    lv_label_set_text(header_, text);
    lv_label_set_text(title_, model.view.title);
    lv_label_set_text(status_, status.text);
    lv_label_set_text(detail_, status.detail);
    uint32_t color = 0x69b7ff;
    if (status.tone == info_tv_v1_Tone_TONE_ATTENTION) color = 0xffc857;
    if (status.tone == info_tv_v1_Tone_TONE_POSITIVE) color = 0x67db99;
    if (status.tone == info_tv_v1_Tone_TONE_NEGATIVE) color = 0xff7777;
    lv_obj_set_style_text_color(status_, lv_color_hex(color), 0);
    if (status.has_progress_percent) {
      lv_obj_remove_flag(progress_, LV_OBJ_FLAG_HIDDEN);
      lv_bar_set_value(progress_, status.progress_percent, LV_ANIM_OFF);
      lv_obj_set_style_bg_color(progress_, lv_color_hex(color), LV_PART_INDICATOR);
    } else {
      lv_obj_add_flag(progress_, LV_OBJ_FLAG_HIDDEN);
    }
  }
  char footer[48];
  if (!model.connected) std::snprintf(footer, sizeof(footer), "OFFLINE | cached | %u/%u",
                                    static_cast<unsigned>(model.pageIndex + (model.pageCount ? 1 : 0)),
                                    static_cast<unsigned>(model.pageCount));
  else if (notification) std::snprintf(footer, sizeof(footer), "Returns to overview");
  else std::snprintf(footer, sizeof(footer), "USB online | Page %u/%u",
                     static_cast<unsigned>(model.pageIndex + (model.pageCount ? 1 : 0)),
                     static_cast<unsigned>(model.pageCount));
  lv_label_set_text(footer_, footer);
}
}  // namespace info_tv
