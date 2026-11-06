idf_component_register(
    SRCS "app_main.cpp" "application.cpp"
         "board/display_driver.cpp"
         "communication/usb_transport.cpp" "communication/device_session.cpp"
         "protocol/codec.cpp" "protocol/framing.cpp" "protocol/generated/device.pb.c"
         "ui/display_state.cpp" "ui/presentation_controller.cpp" "ui/screen_view.cpp"
         "ui/assets/whale_idle.c"
         "ui/assets/whale_closed.c" "ui/assets/whale_shift_0.c"
         "ui/assets/whale_shift_1.c" "ui/assets/whale_shift_2.c" "ui/assets/whale_shift_3.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_driver_ledc esp_driver_spi esp_driver_usb_serial_jtag esp_lcd esp_timer nanopb lvgl)
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
