cmake_minimum_required(VERSION 3.16)

project(sanmou_battle_sim LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(sanmou_sim_cpp
    cpp/main.cpp
    cpp/json.cpp
    cpp/simulator.cpp
)

target_include_directories(sanmou_sim_cpp PRIVATE cpp)

if (MSVC)
    target_compile_options(sanmou_sim_cpp PRIVATE /utf-8)
endif()
