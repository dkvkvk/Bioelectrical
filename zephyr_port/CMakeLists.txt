# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.30.0)

# 指定自定义板子的搜索路径为当前应用目录下的 boards/
set(BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(bioelectrical)

target_sources(app PRIVATE
	src/main.c
	src/ble.c
	src/uart.c
	src/myspi.c
	src/KS1092.c
	src/iir_filter.c
	src/ksfilter.c
	src/heart_rate.c
	src/lvbo.c
	src/kalman_filter.c
	src/protocol_crc.c
)