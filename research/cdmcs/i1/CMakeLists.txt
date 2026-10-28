cmake_minimum_required(VERSION 3.18)
project(cdmcs_i1 LANGUAGES CXX)
add_executable(cdmcs_i1 src/cdmcs_i1.cpp)
target_compile_features(cdmcs_i1 PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(cdmcs_i1 PRIVATE /W4)
else()
    target_compile_options(cdmcs_i1 PRIVATE -Wall -Wextra -Wpedantic)
endif()
# Requires installed Boost.JSON headers (Boost 1.75+). Boost.JSON compiled inline from src.hpp.
find_path(BOOST_JSON_INCLUDE_DIR boost/json.hpp REQUIRED)
target_include_directories(cdmcs_i1 SYSTEM PRIVATE "${BOOST_JSON_INCLUDE_DIR}")
# Keep this independent project out of the application's source glob and build.
include(CTest)
if(BUILD_TESTING)
    find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
    add_test(NAME differential COMMAND "${Python3_EXECUTABLE}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_differential.py"
        --binary $<TARGET_FILE:cdmcs_i1> --random 600)
    add_test(NAME hardening COMMAND "${Python3_EXECUTABLE}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_hardening.py"
        --binary $<TARGET_FILE:cdmcs_i1> -v)
    set_tests_properties(differential hardening PROPERTIES
        TIMEOUT 300 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
endif()
