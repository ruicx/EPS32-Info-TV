#pragma once

#include "lvgl.h"

#include "protocol/model.h"

namespace info_tv {
/** Own a reusable status-card layout; pixel styling stays off the wire. */
class ScreenView {
 public:
  /** Create the screen and persistent widgets on the UI task. */
  void initialize();
  /** Apply one render model without reconstructing the widget tree. */
  void render(const RenderModel& model);

 private:
  /** Create a fixed-position, bounded text widget. */
  lv_obj_t* label(int x, int y, int width, int height);
  lv_obj_t* header_ = nullptr;
  lv_obj_t* title_ = nullptr;
  lv_obj_t* status_ = nullptr;
  lv_obj_t* detail_ = nullptr;
  lv_obj_t* progress_ = nullptr;
  lv_obj_t* footer_ = nullptr;
};
}  // namespace info_tv
