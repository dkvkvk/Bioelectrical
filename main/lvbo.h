#ifndef LVBO_H
#define LVBO_H

float IIR_LBF(float input);
float IIR_BPF(float input);
float LDF_dB(float signal, float noise);
int LDF(float input);
void lvbo_reset(void);

#endif
