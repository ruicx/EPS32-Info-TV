#pragma once

#include <atomic>
#include <cstdint>

#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "lvgl.h"

namespace info_tv {
/** Own the board panel, DMA buffer, and narrow LVGL display integration. */
class DisplayDriver {
 public:
  /** Initialize the board and LVGL display from the UI task. */
  void initialize();
  /** Apply an active-low PWM level in 0..100; return false on driver failure. */
  bool setBrightness(uint32_t percent);
  /** Return whether the last successfully applied level enables the backlight. */
  bool backlightEnabled() const { return brightnessPercent_ > 0; }
  /** Force one refresh associated with a presentation generation. */
  void present(uint32_t generation);
  /** Return whether the current refresh still owns the DMA buffer. */
  bool hasPendingFrame() const;
  /** Return the most recent generation whose final DMA transfer completed. */
  uint32_t completedGeneration() const;

 private:
  /** Convert RGB565 bytes and submit one LVGL area to the panel. */
  static void flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels);
  /** Notify LVGL and publish the final-area completion from driver context. */
  static bool transferDone(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t* event, void* context);
  /** Read a monotonic millisecond tick without creating another UI task. */
  static uint32_t tickMs();
  esp_lcd_panel_io_handle_t io_ = nullptr;
  esp_lcd_panel_handle_t panel_ = nullptr;
  lv_display_t* display_ = nullptr;
  uint32_t brightnessPercent_ = 0;
  std::atomic<bool> lastFlush_{false};
  std::atomic<uint32_t> activeGeneration_{0};
  std::atomic<uint32_t> completedGeneration_{0};
};
}  // namespace info_tv
