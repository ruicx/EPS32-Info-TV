#include "board/display_driver.h"

#include <cassert>
#include <cstddef>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_timer.h"

#include "board/board_config.h"

namespace info_tv {
uint32_t DisplayDriver::tickMs() {
  return static_cast<uint32_t>(esp_timer_get_time() / 1000);
}

void DisplayDriver::initialize() {
  gpio_config_t backlight{};
  backlight.pin_bit_mask = 1ULL << board::kBacklight;
  backlight.mode = GPIO_MODE_OUTPUT;
  ESP_ERROR_CHECK(gpio_config(&backlight));
  setBrightness(false);
  spi_bus_config_t bus{};
  bus.mosi_io_num = board::kMosi;
  bus.miso_io_num = -1;
  bus.sclk_io_num = board::kClock;
  bus.quadwp_io_num = bus.quadhd_io_num = -1;
  bus.max_transfer_sz = board::kWidth * board::kDrawLines * 2;
  ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));
  esp_lcd_panel_io_spi_config_t config{};
  config.cs_gpio_num = GPIO_NUM_NC;
  config.dc_gpio_num = static_cast<gpio_num_t>(board::kDataCommand);
  config.pclk_hz = board::kSpiFrequency;
  config.spi_mode = board::kSpiMode;
  config.lcd_cmd_bits = config.lcd_param_bits = 8;
  config.trans_queue_depth = 1;
  ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI2_HOST, &config, &io_));
  esp_lcd_panel_dev_config_t panelConfig{};
  panelConfig.reset_gpio_num = static_cast<gpio_num_t>(board::kReset);
  panelConfig.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
  panelConfig.bits_per_pixel = 16;
  ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io_, &panelConfig, &panel_));
  ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_));
  ESP_ERROR_CHECK(esp_lcd_panel_init(panel_));
  ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_, true));
  ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_, true));
  lv_init();
  lv_tick_set_cb(tickMs);
  display_ = lv_display_create(board::kWidth, board::kHeight);
  assert(display_);
  const size_t bufferSize = board::kWidth * board::kDrawLines * 2;
  void* buffer = spi_bus_dma_memory_alloc(SPI2_HOST, bufferSize, 0);
  assert(buffer);
  lv_display_set_color_format(display_, LV_COLOR_FORMAT_RGB565);
  lv_display_set_buffers(display_, buffer, nullptr, bufferSize, LV_DISPLAY_RENDER_MODE_PARTIAL);
  lv_display_set_user_data(display_, this);
  lv_display_set_flush_cb(display_, flush);
  esp_lcd_panel_io_callbacks_t callbacks{};
  callbacks.on_color_trans_done = transferDone;
  ESP_ERROR_CHECK(esp_lcd_panel_io_register_event_callbacks(io_, &callbacks, this));
  setBrightness(true);
}

void DisplayDriver::setBrightness(bool enabled) {
  ESP_ERROR_CHECK(gpio_set_level(static_cast<gpio_num_t>(board::kBacklight), enabled ? 0 : 1));
}

void DisplayDriver::flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels) {
  auto& driver = *static_cast<DisplayDriver*>(lv_display_get_user_data(display));
  const size_t count = static_cast<size_t>(lv_area_get_width(area)) * lv_area_get_height(area);
  lv_draw_sw_rgb565_swap(pixels, count);
  driver.lastFlush_.store(lv_display_flush_is_last(display));
  ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(driver.panel_, area->x1, area->y1, area->x2 + 1, area->y2 + 1, pixels));
}

bool DisplayDriver::transferDone(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t*, void* context) {
  auto& driver = *static_cast<DisplayDriver*>(context);
  const bool last = driver.lastFlush_.load();
  const auto generation = driver.activeGeneration_.load();
  lv_display_flush_ready(driver.display_);
  if (last) driver.completedGeneration_.store(generation, std::memory_order_release);
  return false;
}

void DisplayDriver::present(uint32_t generation) {
  activeGeneration_.store(generation);
  lv_obj_invalidate(lv_screen_active());
  lv_refr_now(display_);
}

bool DisplayDriver::hasPendingFrame() const {
  return activeGeneration_.load() != completedGeneration_.load(std::memory_order_acquire);
}

uint32_t DisplayDriver::completedGeneration() const {
  return completedGeneration_.load(std::memory_order_acquire);
}
}  // namespace info_tv
