#pragma once

#include "lvgl.h"

#include "protocol/model.h"

namespace info_tv {
/** Own reusable message bubbles; pixel styling stays off the wire. */
class ScreenView {
 public:
  /** Create the screen and persistent widgets on the UI task. */
  void initialize();
  /** Apply one render model without reconstructing the widget tree. */
  void render(const RenderModel& model);
  /** Update the visual touch indicator badge (brief feedback for touch and click events). */
  bool setTouchIndicator(bool touched, uint32_t clickCount);
  /** Sample local motion; return true only when the character pixels change. */
  bool animate(uint64_t nowMs);

 private:
  /** Create a fixed-position, bounded text widget. */
  lv_obj_t* label(lv_obj_t* parent, int x, int y, int width, int height);
  /** Create a rounded rectangular message surface. */
  lv_obj_t* bubble(int y, int height);
  /** Create a thin reported-progress track inside a message surface. */
  lv_obj_t* progressBar(lv_obj_t* parent, int x, int y, int width);
  /** Draw the bounded local weather symbol using LVGL vector primitives. */
  static void drawWeatherIcon(lv_event_t* event);
  lv_font_t smallFont_{};
  lv_obj_t* header_ = nullptr;
  lv_obj_t* headerUnit_ = nullptr;
  lv_obj_t* touchBadge_ = nullptr;
  lv_obj_t* summary_ = nullptr;
  lv_obj_t* message_ = nullptr;
  lv_obj_t* icon_ = nullptr;
  lv_obj_t* sender_ = nullptr;
  lv_obj_t* title_ = nullptr;
  lv_obj_t* status_ = nullptr;
  lv_obj_t* detail_ = nullptr;
  lv_obj_t* progress_ = nullptr;
  lv_obj_t* page_ = nullptr;
  lv_obj_t* connection_ = nullptr;
  lv_obj_t* empty_ = nullptr;
  lv_obj_t* location_ = nullptr;
  lv_obj_t* temperature_ = nullptr;
  lv_obj_t* conditions_ = nullptr;
  lv_obj_t* weatherDetails_ = nullptr;
  lv_obj_t* weatherIcon_ = nullptr;
  lv_obj_t* weatherAlertIcon_ = nullptr;
  info_tv_v1_WeatherCondition weatherCondition_ = info_tv_v1_WeatherCondition_WEATHER_CONDITION_UNKNOWN;
  bool weatherIconFresh_ = false;
  lv_obj_t* character_ = nullptr;
  const lv_image_dsc_t* characterFrame_ = nullptr;
  std::array<lv_obj_t*, policy::kRowsPerPage> rowBubbles_{};
  std::array<lv_obj_t*, policy::kRowsPerPage> rowIcons_{};
  std::array<lv_obj_t*, policy::kRowsPerPage> rowTitles_{};
  std::array<lv_obj_t*, policy::kRowsPerPage> rowDetails_{};
  std::array<lv_obj_t*, policy::kRowsPerPage> rowProgress_{};
};
}  // namespace info_tv
