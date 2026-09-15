#ifndef KSFILTER_H
#define KSFILTER_H

#include <stdint.h>

double power_50HZ(double x);
double filter(double x);
double Filter_All(double x);

double power1_50HZ(double x);
double filter1(double x);
double Filter1_All(double x);

// Configuration functions
void ksfilter_set_sample_rate(uint32_t sample_interval_us);
void ksfilter_reset(void);
void ksfilter1_reset(void);

#endif
