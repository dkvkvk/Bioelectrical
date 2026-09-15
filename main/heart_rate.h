#ifndef HEART_RATE_H
#define HEART_RATE_H

#include <stdint.h>

void heart_rate_set_sample_rate(uint32_t sample_interval_us);
int get_heart_rate(float input);

#endif