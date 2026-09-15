#include "ksfilter.h"

#define HEAD_INC(var, n, max)  (var = (var + n) % max)

// Maximum buffer sizes (for 1000Hz)
#define MAX_M 20   // Max 50Hz notch window
#define MAX_Q 400  // Max baseline drift window

// Multi-rate filter parameters
// Index: 0=250Hz, 1=500Hz, 2=1000Hz
static const int M_TABLE[3] = {5, 10, 20};    // 50Hz notch window sizes
static const int Q_TABLE[3] = {100, 200, 400};  // Baseline drift window sizes

// Current filter parameters (default: 500Hz)
static int current_M = 10;
static int current_Q = 200;

// ============================================================
// Channel 1: moving-average 50Hz notch + baseline drift removal
// ============================================================

// 50Hz notch: sliding window average, then subtract
static double sum_sample = 0;
static double sample_buf[MAX_M] = {0};
static int sample_buf_head = 0;

double power_50HZ(double x)
{
    double aver = 0;
    sum_sample -= sample_buf[sample_buf_head];
    sample_buf[sample_buf_head] = x;
    sum_sample += sample_buf[sample_buf_head];
    HEAD_INC(sample_buf_head, 1, current_M);
    aver = sum_sample / (current_M / 2.0);
    return aver;
}

// Baseline drift removal: two-stage sliding window, subtract DC component
static double buf_in[MAX_Q];
static double a3[MAX_Q];
static int in_head = 0;
static int a3_head = 0;
static double sum_buf_in = 0;
static double sum_a3 = 0;
static int filter_primed = 0;

double filter(double x)
{
    double aver = 0;
    double f_data = 0;

    if (!filter_primed) {
        filter_primed = 1;
        for (int i = 0; i < current_Q; i++) {
            buf_in[i] = x;
            a3[i] = x;
        }
        sum_buf_in = x * current_Q;
        sum_a3 = x * current_Q;
        in_head = 0;
        a3_head = 0;
    }

    sum_buf_in -= buf_in[in_head];
    buf_in[in_head] = x;
    sum_buf_in += buf_in[in_head];
    HEAD_INC(in_head, 1, current_Q);
    aver = sum_buf_in / current_Q;

    sum_a3 -= a3[a3_head];
    a3[a3_head] = aver;
    sum_a3 += a3[a3_head];
    HEAD_INC(a3_head, 1, current_Q);
    aver = sum_a3 / current_Q;

    f_data = x - aver;
    return f_data;
}

double Filter_All(double x)
{
    return filter(power_50HZ(x));
}


// ============================================================
// Channel 2: independent filter states
// ============================================================

static double sum_sample1 = 0;
static double sample_buf1[MAX_M] = {0};
static int sample_buf_head1 = 0;

double power1_50HZ(double x)
{
    double aver = 0;
    sum_sample1 -= sample_buf1[sample_buf_head1];
    sample_buf1[sample_buf_head1] = x;
    sum_sample1 += sample_buf1[sample_buf_head1];
    HEAD_INC(sample_buf_head1, 1, current_M);
    aver = sum_sample1 / (current_M / 2.0);
    return aver;
}

static double buf_in1[MAX_Q];
static double a31[MAX_Q];
static int in_head1 = 0;
static int a3_head1 = 0;
static double sum_buf_in1 = 0;
static double sum_a31 = 0;
static int filter1_primed = 0;

double filter1(double x)
{
    double aver = 0;
    double f_data = 0;

    if (!filter1_primed) {
        filter1_primed = 1;
        for (int i = 0; i < current_Q; i++) {
            buf_in1[i] = x;
            a31[i] = x;
        }
        sum_buf_in1 = x * current_Q;
        sum_a31 = x * current_Q;
        in_head1 = 0;
        a3_head1 = 0;
    }

    sum_buf_in1 -= buf_in1[in_head1];
    buf_in1[in_head1] = x;
    sum_buf_in1 += buf_in1[in_head1];
    HEAD_INC(in_head1, 1, current_Q);
    aver = sum_buf_in1 / current_Q;

    sum_a31 -= a31[a3_head1];
    a31[a3_head1] = aver;
    sum_a31 += a31[a3_head1];
    HEAD_INC(a3_head1, 1, current_Q);
    aver = sum_a31 / current_Q;

    f_data = x - aver;
    return f_data;
}

double Filter1_All(double x)
{
    return filter1(power1_50HZ(x));
}


// ========== Filter configuration functions ==========

// Set sample rate and update M and Q parameters
void ksfilter_set_sample_rate(uint32_t sample_interval_us)
{
    // Map sample_interval_us to parameter index
    // 4000us = 250Hz (index 0)
    // 2000us = 500Hz (index 1)
    // 1000us = 1000Hz (index 2)
    int idx;
    if (sample_interval_us >= 3500) {
        idx = 0;  // 250Hz
    } else if (sample_interval_us >= 1500) {
        idx = 1;  // 500Hz
    } else {
        idx = 2;  // 1000Hz
    }

    current_M = M_TABLE[idx];
    current_Q = Q_TABLE[idx];
}

// Reset channel 1 filter states
void ksfilter_reset(void)
{
    int i;

    // Reset 50Hz notch filter
    sum_sample = 0.0;
    for (i = 0; i < MAX_M; i++) {
        sample_buf[i] = 0.0;
    }
    sample_buf_head = 0;

    // Reset baseline drift filter
    for (i = 0; i < MAX_Q; i++) {
        buf_in[i] = 0.0;
        a3[i] = 0.0;
    }
    in_head = 0;
    a3_head = 0;
    sum_buf_in = 0.0;
    sum_a3 = 0.0;
    filter_primed = 0;
}

// Reset channel 2 filter states
void ksfilter1_reset(void)
{
    int i;

    // Reset 50Hz notch filter
    sum_sample1 = 0.0;
    for (i = 0; i < MAX_M; i++) {
        sample_buf1[i] = 0.0;
    }
    sample_buf_head1 = 0;

    // Reset baseline drift filter
    for (i = 0; i < MAX_Q; i++) {
        buf_in1[i] = 0.0;
        a31[i] = 0.0;
    }
    in_head1 = 0;
    a3_head1 = 0;
    sum_buf_in1 = 0.0;
    sum_a31 = 0.0;
    filter1_primed = 0;
}
