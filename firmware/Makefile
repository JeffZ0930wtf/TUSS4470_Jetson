CC ?= msp430-elf-gcc
MCU := msp430f5529
BUILD_DIR := build
TARGET := $(BUILD_DIR)/m0-safe.elf
CFLAGS := -mmcu=$(MCU) -Os -std=c11 -Wall -Wextra -Werror

.PHONY: all clean

all: $(TARGET)

$(TARGET): src/main.c
	mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) $< -o $@

clean:
	rm -rf $(BUILD_DIR)
