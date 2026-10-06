# csrc/CMakeLists.txt

cmake_minimum_required(VERSION 3.15)
project(readevents C)

# Try to find libusb (for future libusb implementation in Phase 2)
# In Phase 1, it's just a skeleton, so we make it optional.
find_package(PkgConfig QUIET)
if(PKG_CONFIG_FOUND)
    pkg_check_modules(LIBUSB libusb-1.0)
endif()

add_library(readevents SHARED
    readevents/readevents.c
    readevents/usb_libusb.c
)

target_include_directories(readevents
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/readevents
)

if(LIBUSB_FOUND)
    target_link_libraries(readevents PRIVATE ${LIBUSB_LIBRARIES})
    target_compile_definitions(readevents PRIVATE HAVE_LIBUSB=1)
    target_include_directories(readevents PRIVATE ${LIBUSB_INCLUDE_DIRS})
endif()

# Coincidences library target
add_library(coincidences SHARED
    coincidences/coincidences.c
    coincidences/multi_coincidences.c
)

target_include_directories(coincidences
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/coincidences
)

# Installation targets for coincidences
install(TARGETS coincidences
    LIBRARY DESTINATION tdc/_native
    RUNTIME DESTINATION tdc/_native
    ARCHIVE DESTINATION tdc/_native
)

# Installation target
install(TARGETS readevents
    LIBRARY DESTINATION tdc/_native
    RUNTIME DESTINATION tdc/_native
    ARCHIVE DESTINATION tdc/_native
)
