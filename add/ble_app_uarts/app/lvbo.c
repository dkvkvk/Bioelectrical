#include <stdio.h>
#include "math.h"
#include "lvbo.h"


#define Length_LPF 7
#define Length_BPF 7
#define LengthDB 200


float Window_LPF[Length_LPF] = { 0 },Result_LPF[Length_LPF] = { 0 };
float Window_BPF[Length_BPF] = { 0 },Result_BPF[Length_BPF] = { 0 };

float Pow_Signal[LengthDB]={0},Pow_Noise[LengthDB]={0};
 

float NUM_LPF[7] = {
  2.313304970974e-05,0.0001387982982584, 0.000346995745646,0.0004626609941947,
   0.000346995745646,0.0001387982982584,2.313304970974e-05
};
 
float DEN_LPF[7] = {
                   1,   -4.545047459119,    8.746397596944,   -9.098376319853,
      5.386173059399,   -1.718135349469,   0.2304689872793
};


//45-55
float NUM_BPF[7] = {
  0.0002196062112254,                 0,-0.0006588186336761,                 0,
  0.0006588186336761,                 0,-0.0002196062112254
};
float DEN_BPF[7] = {
                   1,   -4.660101513364,    9.993947841762,   -12.31308359291,
      9.190043571556,   -3.940526182431,   0.7776385602381
};


float IIR_LBF(float ori_input)
{
	for(int i=0;i<Length_LPF-1;i++)
	{
		Window_LPF[i] = Window_LPF[i+1];
		Result_LPF[i] = Result_LPF[i+1];
	}
	
	Window_LPF[(Length_LPF-1)] = ori_input;
	
	Result_LPF[(Length_LPF-1)] = 0;
	
	for(int iii=0;iii<Length_LPF;iii++)
	{
		Result_LPF[(Length_LPF-1)] = NUM_LPF[iii] * Window_LPF[(Length_LPF-1) - iii] + Result_LPF[(Length_LPF-1)];
	}
	for(int jjj=1;jjj<Length_LPF;jjj++)
	{
		Result_LPF[(Length_LPF-1)] = (-1) * DEN_LPF[jjj] * Result_LPF[(Length_LPF-1) - jjj] + Result_LPF[(Length_LPF-1)];
	}
	
	return Result_LPF[(Length_LPF-1)];
}


float IIR_BPF(float ori_input)
{
	for(int i=0;i<(Length_BPF-1);i++)
	{
		Window_BPF[i] = Window_BPF[i+1];
		Result_BPF[i] = Result_BPF[i+1];
	}
	
	Window_BPF[(Length_BPF-1)] = ori_input;
	
	Result_BPF[(Length_BPF-1)] = 0;
	for(int i=0;i<Length_BPF;i++)
	{
		Result_BPF[(Length_BPF-1)] = NUM_BPF[i] * Window_BPF[(Length_BPF-1) - i] + Result_BPF[(Length_BPF-1)];
	}
	for(int i=1;i<Length_BPF;i++)
	{
		Result_BPF[(Length_BPF-1)] = (-1) * DEN_BPF[i] * Result_BPF[(Length_BPF-1) - i] + Result_BPF[(Length_BPF-1)];
	}


	return Result_BPF[(Length_BPF-1)];
}



float LDF_dB(float signal,float noise)
{
	float db_value=0 ,SumSigal = 0,SumNoise = 0, AveSigal=0, AveNoise = 0;

	for(int i=0;i<(LengthDB-1);i++)
	{
		Pow_Signal[i] = Pow_Signal[i+1];
		Pow_Noise[i] = Pow_Noise[i+1];
	}
   
	Pow_Signal[LengthDB-1] = signal*signal;
	Pow_Noise[LengthDB-1] = noise*noise;
   
	for(int i=0;i<LengthDB;i++)
	{
		SumSigal += Pow_Signal[i];
		SumNoise += Pow_Noise[i];
	}
	AveSigal = SumSigal / LengthDB;
	AveNoise = SumNoise / LengthDB;
	db_value = 10 * log10(AveSigal / AveNoise);
	
   return db_value;
}



int LDF(float input)
{
	float Signal,Noise,SNR;
	static int Flag_LDF = 1;
	static int Flag_NORM = 0;
	
	Signal = IIR_LBF(input);
	Noise = IIR_BPF(input);
	SNR = LDF_dB(Signal,Noise);
	
	
	if(SNR<35)
	{
		return SNR;
	}
	
	return SNR;
}



