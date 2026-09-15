#include "WaveDetection.h"
#define Fs						500				//采样频率
#define CurrentPoint			200		//实时数据窗口中实际判断是否为R点的点位
#define DataLength				400			//实时数据窗口长度
#define DataTail				(DataLength-1)


#define Thrh0State_Finished		800				//阈值初值运算未完成标志
#define PreStorage				(Thrh0State_Finished - CurrentPoint + 1)				//实时数据窗口开始预存储数据
#define UpdateFinished			1				//发生更新
#define FindRPeak				1				//R峰值标志
#define WindowFull				1
#define Correction             ( DataLength - (CurrentPoint + 1))
void FindArrayMax_1D_Float(float array[], int Length, float* ans)
{
	float MAX = array[CurrentPoint];
	float Index = CurrentPoint;
	ans[0] = MAX;
	ans[1] = Index;

	for (int i = 0; i < Length; i++)
	{
		if (array[i] > MAX)
		{
			MAX = array[i];
			Index = (float)i;
		}
	}
	ans[0] = MAX;
	ans[1] = Index;
}


//1.1心电数据预处理
// 输入为float型心电信号，输出为平滑后的float型心电信号
float Smooth(float input)
{
	static float SmoothWindow[5] = { 0 };
	float ans = 0;
	for (int i = 0; i < 4; i++)
	{
		SmoothWindow[i] = SmoothWindow[i + 1]; //数据左移
	}

	SmoothWindow[4] = input; //前4个数据叠加

	ans = 0.2f *(SmoothWindow[4]+ SmoothWindow[3] + SmoothWindow[2] + SmoothWindow[1] + SmoothWindow[0]); //加入当前数据，并计算五个数据的均值

	return ans; //输出平滑后的值
}


//1.2双阈值法确定阈值
int Threshold(float input, float *THrh0) // ECG_THrh0. Diff_THrh0
{
	float ThresholdMax_ECG_Temp = 0, ThresholdMax_Diff_Temp = 0;
	static int count = 0; //计算数据数量->800个
	static float ThresholdWindow[3] = { 0 };
	static float ThresholdMax_ECG = 0, ThresholdMax_Diff = 0;

	if (count < 800)
	{  
		for (int i = 0; i < 2; i++)
		{
			ThresholdWindow[i] = ThresholdWindow[i+1]; //数据左移
		}
		
		//计算800个数据中的最大值
		ThresholdMax_ECG_Temp = input;
		if (ThresholdMax_ECG_Temp > ThresholdMax_ECG)
		{
			ThresholdMax_ECG = ThresholdMax_ECG_Temp;
		}
;
		//计算800个数据中的隔项差分的最大值
		ThresholdWindow[2] = input;
		if (count >= 2)//前两个值初值为空
		{
			ThresholdMax_Diff_Temp = ThresholdWindow[2] - ThresholdWindow[0];
		}
		if (ThresholdMax_Diff_Temp > ThresholdMax_Diff)
		{
			ThresholdMax_Diff = ThresholdMax_Diff_Temp;
		}

		//THrh0[0] = ThresholdMax_ECG * 0.6f;
		//THrh0[1] = ThresholdMax_Diff * 0.5f;

		THrh0[0] = ThresholdMax_ECG *  0.9f;
		THrh0[1] = ThresholdMax_Diff * 0.8f;



		count++;
	 }
	return count; //count < 800,阈值计算中 //count = 800,阈值计算完毕
}


//检测R波
int DetectionR(float input, float Threshold_ECG, float Threshold_Diff,int* IsPeak)
{
	static int Flag = 0;
	float MaxR[2] = { 0 };
	float MaxR_Index = 0;
	
	static int count = 0; 
	static float DetectionRWindow[DataLength] = { 0 };//检测R波要用

	IsPeak[0] = 0;
	if (count < DataTail)
	{
		DetectionRWindow[count] = input;//预存计算点和计算点前10个
		count++;
		return 0;
	}
	else 
	{
		if (count == DataTail)//数据初次填满时，不需数据右移
		{
			Flag = WindowFull;
			count++;
		}
		else if(count > DataTail)//数据左移
		{
			for (int i = 0; i < DataTail; i++)
			{
				DetectionRWindow[i] = DetectionRWindow[i + 1];
			}
		}
		
		DetectionRWindow[DataTail] = input;

		if ((DetectionRWindow[CurrentPoint] > Threshold_ECG) && (DetectionRWindow[CurrentPoint] > Threshold_Diff))
		{
			
			FindArrayMax_1D_Float(DetectionRWindow, DataLength, MaxR);
			MaxR_Index = MaxR[1];
			if (MaxR_Index == CurrentPoint)
			{
				IsPeak[0] = FindRPeak;
			}
		}
	}
	return Flag;
}

int ThresholdUpdate(int PeakNum, float* THrh0)
{
	static int count = 0;
	static int InitialCount = 0;//控制是否允许阈值更新
	static float C1 = 0.1f;
	static float C2 = 0.1f;
	float ThresholdMax_ECG = THrh0[0];
	float ThresholdMax_Diff = THrh0[1];
	if (PeakNum == 1)
	{
		count++;
	}
	if ((count == 5) && (InitialCount == 1))//初次更新后，每五个峰值更新一次
	{
		ThresholdMax_ECG = 0.2f * ThresholdMax_ECG + C1;//计算新阈值
		ThresholdMax_Diff = 0.1667f * ThresholdMax_Diff + C2;

		THrh0[0] = ThresholdMax_ECG;//更新阈值
		THrh0[1] = ThresholdMax_Diff;
		return UpdateFinished;
	}
	if (count == 5) //初次更新发生在第十个R峰，因此第五个峰值到来后再允许更新。
	{
		count = 0;
		InitialCount = 1;
	}
	return (!UpdateFinished);
}

float Period(int PeakNum)
{
	static int RR_time = 0;
	static float RR_period = 0;
	static float fs = Fs;
	RR_time++;
	if ((PeakNum == 1)&&(RR_time > 60))
	{
		RR_period = 60.0f / (RR_time / fs);
		RR_time = 0;
	}

	return RR_period;
}

int SelfAdaptiveDoubleThreshold(float input)
{
	float INputSmooth = 0;
	int Flag = 0;
	static int Thrh0State = 0;
	static float Thrh0[2] = { 0 };//接收阈值初值
	static float RRpeiod = 0;
	static int IsPeakArry[1] = {0};
	//平滑滤波
	INputSmooth = Smooth(input);
	//计算阈值初值，输出计算状态
	Thrh0State = Threshold(INputSmooth, Thrh0);
	
	if (Thrh0State >= PreStorage)//阈值初值计算到第791（PreStorage）个时，对实时窗口进行存储，方便后续计算
	{
		Flag = DetectionR(INputSmooth, Thrh0[0], Thrh0[1], IsPeakArry);//预存储数值
	}

	if (Flag == WindowFull)//实时窗口充满，开始计算R波和阈值更新
	{
		//阈值更新，判断更新状态
		ThresholdUpdate(IsPeakArry[0], Thrh0);
		//printf("Thrh0 = %f\n", Thrh0[0]);
		//printf("Thrh1 = %f\n", Thrh0[1]);
		//根据R波个数计算周期，起始计算点为实时窗口充满后
		RRpeiod = Period(IsPeakArry[0]);

	}

	return (int)RRpeiod;
}

