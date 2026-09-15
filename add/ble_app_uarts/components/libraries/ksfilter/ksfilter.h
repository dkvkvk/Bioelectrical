#ifndef _KSFILTER_H__
#define _KSFILTER_H__
//#include "sys.h" 

#define SAMPLE_RATE							500
#define M									( SAMPLE_RATE / 50 )	

//Q=200;   %Q参数可调，Q越大，波形保真度越好，去基漂能力越差，Q最大425
#define Q	200

extern double power_50HZ(double x);   //去除50HZ工频

extern double filter(double x);     //去除基线漂移

extern double Filter_All(double x);  //去除50HZ工频和基线漂移

extern double power1_50HZ(double x);   //去除50HZ工频

extern double filter1(double x);     //去除基线漂移

extern double Filter1_All(double x);  //去除50HZ工频和基线漂移

#endif
