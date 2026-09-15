#ifndef _IIR_FILTER_H__
#define _IIR_FILTER_H__


extern double IIR_50HZ(double x);   //去除50HZ工频

extern double IIR_100HZ_LPF(double x);     //去除基线漂移

extern double IIR_Filter1_All(double x);  //去除50HZ工频和基线漂移

extern double IIR1_50HZ(double x);   //去除50HZ工频

extern double IIR1_100HZ_LPF(double x);     //去除基线漂移

extern double IIR1_Filter1_All(double x);  //去除50HZ工频和基线漂移

#endif
