#include "iir_filter.h"

// Multi-rate filter coefficients
// Index: 0=250Hz, 1=500Hz, 2=1000Hz
static int current_filter_set = 1;  // Default: 500Hz

// 50Hz notch filter coefficients (Direct Form I, Q=5)
static const double IIR_50HZ_B[3][3] = {
    {8.878397555248065398e-01, -5.487151454777277060e-01, 8.878397555248065398e-01},  // fs=250Hz
    {9.281956097374167713e-01, -1.501852044763573257e+00, 9.281956097374167713e-01},  // fs=500Hz
    {9.695312529087461995e-01, -1.844158031661335295e+00, 9.695312529087461995e-01},  // fs=1000Hz
};

static const double IIR_50HZ_A[3][3] = {
    {1.000000000000000000e+00, -5.487151454777277060e-01, 7.756795110496130796e-01},  // fs=250Hz
    {1.000000000000000000e+00, -1.501852044763573257e+00, 8.563912194748335427e-01},  // fs=500Hz
    {1.000000000000000000e+00, -1.844158031661335295e+00, 9.390625058174923989e-01},  // fs=1000Hz
};

// 4th-order Butterworth LPF, 1st biquad section (cutoff=100Hz)
static const double IIR_LPF_B[3][3] = {
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=250Hz
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=500Hz
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=1000Hz
};

static const double IIR_LPF_A[3][3] = {
    {1.000000000000000000e+00, 1.048599576362611252e+00, 2.961403575616693984e-01},  // fs=250Hz
    {1.000000000000000000e+00, -4.531195206523849217e-01, 4.663255707632369407e-01},  // fs=500Hz
    {1.000000000000000000e+00, -1.048599576362611696e+00, 2.961403575616696204e-01},  // fs=1000Hz
};

static const double IIR_LPF_Gain[3] = {
    4.328466449902918511e-01,  // fs=250Hz
    2.533015125277130464e-01,  // fs=500Hz
    4.824343357716228201e-03,  // fs=1000Hz
};

// 4th-order Butterworth LPF, 2nd biquad section (cutoff=100Hz)
static const double IIR_LPF_B1[3][3] = {
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=250Hz
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=500Hz
    {1.000000000000000000e+00, 2.000000000000000000e+00, 1.000000000000000000e+00},  // fs=1000Hz
};

static const double IIR_LPF_A1[3][3] = {
    {1.000000000000000000e+00, 1.320913430819425916e+00, 6.327387928852763466e-01},  // fs=250Hz
    {1.000000000000000000e+00, -3.289756773709530679e-01, 6.458765491644302692e-02},  // fs=500Hz
    {1.000000000000000000e+00, -1.320913430819426360e+00, 6.327387928852765686e-01},  // fs=1000Hz
};

static const double IIR_LPF_Gain1[3] = {
    1.000000000000000000e+00,  // fs=250Hz
    1.839029943863725036e-01,  // fs=500Hz
    1.000000000000000000e+00,  // fs=1000Hz
};

// Channel 1 state variables
static double w1=0.0, w2=0.0, w3=0.0;   // 50Hz notch delay line
static double l1=0.0, l2=0.0, l3=0.0;   // LPF stage 1 delay line
static double L1=0.0, L2=0.0, L3=0.0;   // LPF stage 2 delay line

// Channel 2 state variables
static double w11=0.0, w22=0.0, w33=0.0;
static double l11=0.0, l22=0.0, l33=0.0;
static double L11=0.0, L22=0.0, L33=0.0;


// Channel 1: 50Hz notch filter
double IIR_50HZ(double x)
{
    double aver = 0;
    int idx = current_filter_set;
    w1 = x - IIR_50HZ_A[idx][1]*w2 - IIR_50HZ_A[idx][2]*w3;
    aver = IIR_50HZ_B[idx][0]*w1 + IIR_50HZ_B[idx][1]*w2 + IIR_50HZ_B[idx][2]*w3;
    w3 = w2;
    w2 = w1;
    return aver;
}

// Channel 1: 40Hz 4th-order Butterworth LPF (2 biquad sections cascaded)
double IIR_100HZ_LPF(double x)
{
    double aver = 0;
    double aver1 = 0;
    int idx = current_filter_set;
    l1 = x - IIR_LPF_A[idx][1]*l2 - IIR_LPF_A[idx][2]*l3;
    aver = (IIR_LPF_B[idx][0]*l1 + IIR_LPF_B[idx][1]*l2 + IIR_LPF_B[idx][2]*l3) * IIR_LPF_Gain[idx];
    l3 = l2;
    l2 = l1;

    L1 = aver - IIR_LPF_A1[idx][1]*L2 - IIR_LPF_A1[idx][2]*L3;
    aver1 = (IIR_LPF_B1[idx][0]*L1 + IIR_LPF_B1[idx][1]*L2 + IIR_LPF_B1[idx][2]*L3) * IIR_LPF_Gain1[idx];
    L3 = L2;
    L2 = L1;

    return aver1;
}

// Channel 1: 50Hz notch + 100Hz LPF
double IIR_Filter1_All(double x)
{
    return IIR_100HZ_LPF(IIR_50HZ(x));
}


// Channel 2: 50Hz notch filter (independent state)
double IIR1_50HZ(double x)
{
    double aver1 = 0;
    int idx = current_filter_set;
    w11 = x - IIR_50HZ_A[idx][1]*w22 - IIR_50HZ_A[idx][2]*w33;
    aver1 = IIR_50HZ_B[idx][0]*w11 + IIR_50HZ_B[idx][1]*w22 + IIR_50HZ_B[idx][2]*w33;
    w33 = w22;
    w22 = w11;
    return aver1;
}

// Channel 2: 40Hz 4th-order Butterworth LPF (independent state)
double IIR1_100HZ_LPF(double x)
{
    double aver = 0;
    double aver1 = 0;
    int idx = current_filter_set;
    l11 = x - IIR_LPF_A[idx][1]*l22 - IIR_LPF_A[idx][2]*l33;
    aver = (IIR_LPF_B[idx][0]*l11 + IIR_LPF_B[idx][1]*l22 + IIR_LPF_B[idx][2]*l33) * IIR_LPF_Gain[idx];
    l33 = l22;
    l22 = l11;

    L11 = aver - IIR_LPF_A1[idx][1]*L22 - IIR_LPF_A1[idx][2]*L33;
    aver1 = (IIR_LPF_B1[idx][0]*L11 + IIR_LPF_B1[idx][1]*L22 + IIR_LPF_B1[idx][2]*L33) * IIR_LPF_Gain1[idx];
    L33 = L22;
    L22 = L11;

    return aver1;
}

// Channel 2: 50Hz notch + 100Hz LPF
double IIR1_Filter1_All(double x)
{
    return IIR1_100HZ_LPF(IIR1_50HZ(x));
}


// ========== Filter configuration functions ==========

// Set sample rate and select corresponding coefficient set
void iir_filter_set_sample_rate(uint32_t sample_interval_us)
{
    // Map sample_interval_us to filter coefficient index
    // 4000us = 250Hz (index 0)
    // 2000us = 500Hz (index 1)
    // 1000us = 1000Hz (index 2)
    if (sample_interval_us >= 3500) {
        current_filter_set = 0;  // 250Hz
    } else if (sample_interval_us >= 1500) {
        current_filter_set = 1;  // 500Hz
    } else {
        current_filter_set = 2;  // 1000Hz
    }
}

// Reset channel 1 filter states
void iir_filter_reset(void)
{
    w1 = 0.0;
    w2 = 0.0;
    w3 = 0.0;
    l1 = 0.0;
    l2 = 0.0;
    l3 = 0.0;
    L1 = 0.0;
    L2 = 0.0;
    L3 = 0.0;
}

// Reset channel 2 filter states
void iir1_filter_reset(void)
{
    w11 = 0.0;
    w22 = 0.0;
    w33 = 0.0;
    l11 = 0.0;
    l22 = 0.0;
    l33 = 0.0;
    L11 = 0.0;
    L22 = 0.0;
    L33 = 0.0;
}
