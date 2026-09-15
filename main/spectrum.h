#ifndef SPECTRUM_H
#define SPECTRUM_H

// Diagnostic spectrum analyzer.
// Feed raw (pre-filter) and filtered (post-filter) samples each tick; a
// background task runs a Goertzel magnitude scan once per block and logs the
// dominant frequencies plus a compact bar, for both signals. Used to find the
// frequency of residual noise and verify the filter chain removed it.

void spectrum_start(double fs);
void spectrum_feed(double raw, double filtered);

#endif
