#ifndef __LVBO_H
#define __LVBO_H	 
	 


int LDF(float input);//1ÎªÍÑÂä 

float IIR_LBF(float ori_input);
float IIR_BPF(float ori_input);
void iir_bandstop_init(void);
float iir_bandstop_filter(float x);
float LDF_dB(float signal,float noise);


#endif

