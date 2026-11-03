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
endforeach()
add_executable(protocol_bridge protocol_bridge.cpp)
target_link_libraries(protocol_bridge PRIVATE info_tv_core)
