# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.22)

# 只编译 main 及其依赖，避免编译 esp_lcd 等无关组件（GCC 15.2.0 编译器 bug）
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(sample_project)
