#ifndef IIR_FILTER_H
#define IIR_FILTER_H

#include <stdint.h>

double IIR_50HZ(double x);
double IIR_100HZ_LPF(double x);
double IIR_Filter1_All(double x);

double IIR1_50HZ(double x);
double IIR1_100HZ_LPF(double x);
double IIR1_Filter1_All(double x);

// Configuration functions
void iir_filter_set_sample_rate(uint32_t sample_interval_us);
void iir_filter_reset(void);
void iir1_filter_reset(void);

#endif
