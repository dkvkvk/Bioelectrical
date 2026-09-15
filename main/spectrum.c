#include "spectrum.h"
#include <math.h>
#include <string.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const char *TAG = "SPEC";

#define SPEC_N      500   // samples per block (1.0s at 500Hz -> 1Hz resolution)
#define SPEC_FMIN   2
#define SPEC_FMAX   120
#define SPEC_FSTEP  2
#define SPEC_NBINS  (((SPEC_FMAX - SPEC_FMIN) / SPEC_FSTEP) + 1)

static double s_fs = 500.0;

static double fill_raw[SPEC_N];
static double fill_filt[SPEC_N];
static int    fill_count = 0;

static double an_raw[SPEC_N];
static double an_filt[SPEC_N];
static volatile bool block_ready = false;

static double goertzel_mag(const double *buf, int n, double mean, double coeff)
{
    double s1 = 0.0, s2 = 0.0, s0;
    for (int i = 0; i < n; i++) {
        s0 = (buf[i] - mean) + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    double p = s1 * s1 + s2 * s2 - coeff * s1 * s2;
    return p > 0.0 ? sqrt(p) : 0.0;
}

// Compute the per-frequency magnitude spectrum (DC removed) into mag[SPEC_NBINS].
static void compute_mag(const double *buf, int n, double *mag)
{
    double mean = 0.0;
    for (int i = 0; i < n; i++) {
        mean += buf[i];
    }
    mean /= n;

    int b = 0;
    for (int f = SPEC_FMIN; f <= SPEC_FMAX; f += SPEC_FSTEP) {
        double coeff = 2.0 * cos(2.0 * M_PI * (double)f / s_fs);
        mag[b] = goertzel_mag(buf, n, mean, coeff);
        b++;
    }
}

// Render one labelled row. mag is the signal's own spectrum; ref_max is the
// shared scale (RAW's peak) so RAW and FILT are directly comparable.
static void render_row(const char *label, const double *mag, double ref_max)
{
    int p1 = 0, p2 = 0, p3 = 0;
    for (int b = 1; b < SPEC_NBINS; b++) {
        if (mag[b] > mag[p1]) { p3 = p2; p2 = p1; p1 = b; }
        else if (mag[b] > mag[p2]) { p3 = p2; p2 = b; }
        else if (mag[b] > mag[p3]) { p3 = b; }
    }
    ESP_LOGI(TAG, "%s peaks: %dHz(%d%%)  %dHz(%d%%)  %dHz(%d%%)  [scale vs RAW]",
             label,
             SPEC_FMIN + p1 * SPEC_FSTEP, (int)(mag[p1] / ref_max * 100.0),
             SPEC_FMIN + p2 * SPEC_FSTEP, (int)(mag[p2] / ref_max * 100.0),
             SPEC_FMIN + p3 * SPEC_FSTEP, (int)(mag[p3] / ref_max * 100.0));

    static const char lv[] = " .:-=+*#%@";
    char line[SPEC_NBINS + 1];
    for (int b = 0; b < SPEC_NBINS; b++) {
        int idx = (int)(mag[b] / ref_max * 9.0 + 0.5);
        if (idx < 0) idx = 0;
        if (idx > 9) idx = 9;
        line[b] = lv[idx];
    }
    line[SPEC_NBINS] = '\0';
    ESP_LOGI(TAG, "%s |%s| %d..%dHz", label, line, SPEC_FMIN, SPEC_FMAX);
}

// Analyze RAW and FILT on a SHARED scale so attenuation is visible: both rows
// are normalized to the RAW peak. A working filter makes the FILT peak %
// at the noise frequency drop well below 100%.
static void analyze_pair(const double *raw, const double *filt, int n)
{
    static double mag_raw[SPEC_NBINS];
    static double mag_filt[SPEC_NBINS];
    compute_mag(raw, n, mag_raw);
    compute_mag(filt, n, mag_filt);

    double raw_max = 1e-12;
    for (int b = 0; b < SPEC_NBINS; b++) {
        if (mag_raw[b] > raw_max) raw_max = mag_raw[b];
    }

    render_row("RAW ", mag_raw, raw_max);
    render_row("FILT", mag_filt, raw_max);
}

static void spectrum_task(void *arg)
{
    (void)arg;
    while (1) {
        if (block_ready) {
            ESP_LOGI(TAG, "============ spectrum (fs=%.0fHz, %.1fs) ============",
                     s_fs, (double)SPEC_N / s_fs);
            analyze_pair(an_raw, an_filt, SPEC_N);
            block_ready = false;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void spectrum_start(double fs)
{
    if (fs > 0.0) {
        s_fs = fs;
    }
    fill_count = 0;
    block_ready = false;
    xTaskCreate(spectrum_task, "spectrum", 4096, NULL, 3, NULL);
}

void spectrum_feed(double raw, double filtered)
{
    if (fill_count < SPEC_N) {
        fill_raw[fill_count] = raw;
        fill_filt[fill_count] = filtered;
        fill_count++;
    }
    if (fill_count >= SPEC_N) {
        if (!block_ready) {
            memcpy(an_raw, fill_raw, sizeof(an_raw));
            memcpy(an_filt, fill_filt, sizeof(an_filt));
            block_ready = true;
        }
        fill_count = 0;  // begin next block (this block dropped if analyzer busy)
    }
}
