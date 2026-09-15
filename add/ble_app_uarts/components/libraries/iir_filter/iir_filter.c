#include "iir_filter.h"

static double IIR_50HZ_B[3] = {
   0.92819560973741677134540850602206774056f,
	-1.501852044763573257313282738323323428631f,
	 0.92819560973741677134540850602206774056f
};

static double IIR_50HZ_A[3] = {
	 1.0f,
	-1.501852044763573257313282738323323428631f,
	 0.856391219474833542690817012044135481119f
};
static double IIR_LPF_B[3] = {1,2,1};
static double IIR_LPF_A[3] = {1,-0.453119520652384921710620346857467666268,0.466325570763236940674545394358574412763};
static double IIR_LPF_Gain = 0.25330151252771304637434468531864695251;
static double IIR_LPF_B1[3] = {1,2,1};
static double IIR_LPF_A1[3] = {1,-0.32897567737095306794614657519559841603,0.064587654916443026920092052023392170668};
static double IIR_LPF_Gain1 = 0.183902994386372503621274177021405193955;
static double w1=0.0;
static double w2=0.0;
static double w3=0.0;
static double l1=0.0;
static double l2=0.0;
static double l3=0.0;
static double L1=0.0;
static double L2=0.0;
static double L3=0.0;

static double w11=0.0;
static double w22=0.0;
static double w33=0.0;
static double l11=0.0;
static double l22=0.0;
static double l33=0.0;
static double L11=0.0;
static double L22=0.0;
static double L33=0.0;


extern double IIR_50HZ(double x)   //去除50HZ工频
{
	 double aver = 0;
   w1 =  x-IIR_50HZ_A[1]*w2-IIR_50HZ_A[2]*w3;
	 aver = IIR_50HZ_B[0]*w1+IIR_50HZ_B[1]*w2+IIR_50HZ_B[2]*w3;
	
   w3=w2;
   w2=w1;
	 return aver;
}

extern double IIR_100HZ_LPF(double x)   
{
    double aver = 0;
    double aver1 = 0;   
	  l1 =  x-IIR_LPF_A[1]*l2-IIR_LPF_A[2]*l3;
	  aver = (IIR_LPF_B[0]*l1+IIR_LPF_B[1]*l2+IIR_LPF_B[2]*l3)*IIR_LPF_Gain;
	
    l3=l2;
    l2=l1;
	
	  L1 =  aver-IIR_LPF_A1[1]*L2-IIR_LPF_A1[2]*L3;
	  aver1 = (IIR_LPF_B1[0]*L1+IIR_LPF_B1[1]*L2+IIR_LPF_B1[2]*L3)*IIR_LPF_Gain1;
	
    L3=L2;
    L2=L1;
	
	  return aver1;
}

extern double IIR_Filter1_All(double x)
{
   return IIR_100HZ_LPF(IIR_50HZ(x));
}


extern double IIR1_50HZ(double x)   //去除50HZ工频
{
	 double aver1 = 0;
   w11 =  x-IIR_50HZ_A[1]*w22-IIR_50HZ_A[2]*w33;
	 aver1 = IIR_50HZ_B[0]*w11+IIR_50HZ_B[1]*w22+IIR_50HZ_B[2]*w33;
	
   w33=w22;
   w22=w11;
	 return aver1;
}

extern double IIR1_100HZ_LPF(double x)   
{
    double aver = 0;
    double aver1 = 0;   
	  l11 =  x-IIR_LPF_A[1]*l22-IIR_LPF_A[2]*l33;
	  aver = (IIR_LPF_B[0]*l11+IIR_LPF_B[1]*l22+IIR_LPF_B[2]*l33)*IIR_LPF_Gain;
	
    l33=l22;
    l22=l11;
	
	  L11 =  aver-IIR_LPF_A1[1]*L22-IIR_LPF_A1[2]*L33;
	  aver1 = (IIR_LPF_B1[0]*L11+IIR_LPF_B1[1]*L22+IIR_LPF_B1[2]*L33)*IIR_LPF_Gain1;
	
    L33=L22;
    L22=L11;
	
	  return aver1;
}

extern double IIR1_Filter1_All(double x)
{
   return IIR1_100HZ_LPF(IIR1_50HZ(x));
}
