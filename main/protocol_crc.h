#ifndef PROTOCOL_CRC_H
#define PROTOCOL_CRC_H

#include <stdint.h>

uint8_t Fast_CRC_Cal8Bits(uint8_t crc, int size, const uint8_t *buffer);

#endif
