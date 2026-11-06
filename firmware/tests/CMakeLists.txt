cmake_minimum_required(VERSION 3.22)
project(info_tv_core_tests LANGUAGES C CXX)
enable_testing()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(APP "${CMAKE_CURRENT_LIST_DIR}/../main")
set(NANOPB "${CMAKE_CURRENT_LIST_DIR}/../components/nanopb/upstream")
add_library(info_tv_core STATIC
    "${APP}/protocol/framing.cpp" "${APP}/protocol/codec.cpp"
    "${APP}/protocol/generated/device.pb.c"
    "${APP}/ui/display_state.cpp" "${APP}/ui/presentation_controller.cpp"
    "${NANOPB}/pb_common.c" "${NANOPB}/pb_encode.c" "${NANOPB}/pb_decode.c")
target_include_directories(info_tv_core PUBLIC "${APP}" "${NANOPB}")
foreach(name framing codec presentation)
    add_executable(test_${name} test_${name}.cpp)
    target_link_libraries(test_${name} PRIVATE info_tv_core)
    add_test(NAME ${name} COMMAND test_${name} "${CMAKE_CURRENT_LIST_DIR}/../../protocol/test_vectors")
    set_tests_properties(${name} PROPERTIES LABELS "unit")
endforeach()
add_executable(protocol_bridge protocol_bridge.cpp)
target_link_libraries(protocol_bridge PRIVATE info_tv_core)

option(INFO_TV_BUILD_UI_TESTS "Render the real LVGL screen on the desktop" OFF)
if(INFO_TV_BUILD_UI_TESTS)
    set(LVGL "${CMAKE_CURRENT_LIST_DIR}/../managed_components/lvgl__lvgl")
    if(NOT EXISTS "${LVGL}/lvgl.h")
        message(FATAL_ERROR "Build firmware once to obtain its locked LVGL dependency")
    endif()
    file(GLOB_RECURSE LVGL_SOURCES "${LVGL}/src/*.c")
    add_library(info_tv_lvgl STATIC ${LVGL_SOURCES})
    target_include_directories(info_tv_lvgl PUBLIC "${LVGL}")
    target_compile_definitions(info_tv_lvgl PUBLIC
        LV_CONF_PATH="${CMAKE_CURRENT_LIST_DIR}/lv_conf.h" LV_LVGL_H_INCLUDE_SIMPLE)
    add_executable(test_screen test_screen.cpp "${APP}/ui/screen_view.cpp" "${APP}/ui/assets/whale_idle.c")
    target_link_libraries(test_screen PRIVATE info_tv_core info_tv_lvgl)
    add_test(NAME screen COMMAND test_screen "${CMAKE_CURRENT_BINARY_DIR}/screen")
    set_tests_properties(screen PROPERTIES LABELS "unit")
endif()
