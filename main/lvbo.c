#include "lvbo.h"

#include <math.h>

#define LENGTH_LPF 7
#define LENGTH_BPF 7
#define LENGTH_DB 200

static float window_lpf[LENGTH_LPF];
static float result_lpf[LENGTH_LPF];
static float window_bpf[LENGTH_BPF];
static float result_bpf[LENGTH_BPF];
static float pow_signal[LENGTH_DB];
static float pow_noise[LENGTH_DB];

static const float num_lpf[LENGTH_LPF] = {
    2.313304970974e-05f,
    0.0001387982982584f,
    0.000346995745646f,
    0.0004626609941947f,
    0.000346995745646f,
    0.0001387982982584f,
    2.313304970974e-05f,
};

static const float den_lpf[LENGTH_LPF] = {
    1.0f,
    -4.545047459119f,
    8.746397596944f,
    -9.098376319853f,
    5.386173059399f,
    -1.718135349469f,
    0.2304689872793f,
};

static const float num_bpf[LENGTH_BPF] = {
    0.0002196062112254f,
    0.0f,
    -0.0006588186336761f,
    0.0f,
    0.0006588186336761f,
    0.0f,
    -0.0002196062112254f,
};

static const float den_bpf[LENGTH_BPF] = {
    1.0f,
    -4.660101513364f,
    9.993947841762f,
    -12.31308359291f,
    9.190043571556f,
    -3.940526182431f,
    0.7776385602381f,
};

float IIR_LBF(float input)
{
    for (int i = 0; i < LENGTH_LPF - 1; i++) {
        window_lpf[i] = window_lpf[i + 1];
        result_lpf[i] = result_lpf[i + 1];
    }

    window_lpf[LENGTH_LPF - 1] = input;
    result_lpf[LENGTH_LPF - 1] = 0.0f;

    for (int i = 0; i < LENGTH_LPF; i++) {
        result_lpf[LENGTH_LPF - 1] += num_lpf[i] * window_lpf[LENGTH_LPF - 1 - i];
    }
    for (int i = 1; i < LENGTH_LPF; i++) {
        result_lpf[LENGTH_LPF - 1] -= den_lpf[i] * result_lpf[LENGTH_LPF - 1 - i];
    }

    return result_lpf[LENGTH_LPF - 1];
}

float IIR_BPF(float input)
{
    for (int i = 0; i < LENGTH_BPF - 1; i++) {
        window_bpf[i] = window_bpf[i + 1];
        result_bpf[i] = result_bpf[i + 1];
    }

    window_bpf[LENGTH_BPF - 1] = input;
    result_bpf[LENGTH_BPF - 1] = 0.0f;

    for (int i = 0; i < LENGTH_BPF; i++) {
        result_bpf[LENGTH_BPF - 1] += num_bpf[i] * window_bpf[LENGTH_BPF - 1 - i];
    }
    for (int i = 1; i < LENGTH_BPF; i++) {
        result_bpf[LENGTH_BPF - 1] -= den_bpf[i] * result_bpf[LENGTH_BPF - 1 - i];
    }

    return result_bpf[LENGTH_BPF - 1];
}

float LDF_dB(float signal, float noise)
{
    float sum_signal = 0.0f;
    float sum_noise = 0.0f;

    for (int i = 0; i < LENGTH_DB - 1; i++) {
        pow_signal[i] = pow_signal[i + 1];
        pow_noise[i] = pow_noise[i + 1];
    }

    pow_signal[LENGTH_DB - 1] = signal * signal;
    pow_noise[LENGTH_DB - 1] = noise * noise;

    for (int i = 0; i < LENGTH_DB; i++) {
        sum_signal += pow_signal[i];
        sum_noise += pow_noise[i];
    }

    if (sum_noise <= 0.0f) {
        return 0.0f;
    }

    return 10.0f * log10f(sum_signal / sum_noise);
}

int LDF(float input)
{
    float signal = IIR_LBF(input);
    float noise = IIR_BPF(input);
    float snr = LDF_dB(signal, noise);

    return (int)snr;
}

void lvbo_reset(void)
{
    for (int i = 0; i < LENGTH_LPF; i++) {
        window_lpf[i] = 0.0f;
        result_lpf[i] = 0.0f;
    }
    for (int i = 0; i < LENGTH_BPF; i++) {
        window_bpf[i] = 0.0f;
        result_bpf[i] = 0.0f;
    }
    for (int i = 0; i < LENGTH_DB; i++) {
        pow_signal[i] = 0.0f;
        pow_noise[i] = 0.0f;
    }
}
