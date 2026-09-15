#include "heart_rate.h"

#define check_gap 5

float rate_list[check_gap];
int initialization=0, check_time=0;
int RealT_HR=0;
int fR=0, fP=0, sR=0, sP=0, flag_HR=0;
int time_out=0;

int get_heart_rate(float input)
{
  float slope=0.0f;
	int RR=0, i=0;
	if(initialization < check_gap)
	{
		rate_list[initialization] = input;
		initialization++;
		return 0;
	}
	else
	{
		for(i=0; i<check_gap - 1; i++)
		{
			rate_list[i] = rate_list[i+1];
		}
		rate_list[check_gap - 1] = input;
	}
	
  slope = (-2.0f) * rate_list[0] + (-1.0f) * rate_list[1] + rate_list[check_gap-2] + 2.0f * rate_list[check_gap-1];//计算斜率
  if (slope < 100 || slope > 1000)
  {
		flag_HR++;
		time_out++;
		if(time_out > 1000)
		{
			RealT_HR = 0;
		}
		return RealT_HR;
  }
	else
	{
		time_out = 0;
	}
	
	
  if (fR == 0 || sR == 0)
	{
		if (slope > 100)
		{
			if (fR == 0)
			{
				fR = 1;//记录第一个R波
				fP = flag_HR;
			}
			else if (sR == 0)
			{
				sR = 1;//记录第二个R波
				sP = flag_HR;
									
				if (sP - fP < 60)
				{
					sR = 0;//如间距过近忽略
				}
			}
		}
    flag_HR++;
  }
  else
  {
    RR = sP - fP;

    RealT_HR = 60.0f / ((float)RR / 500.0f);
    fR = 0;
    sR = 0;
		flag_HR = 0;
  }
	//printf("%d\r\n", RealT_HR);
	return (int)RealT_HR;
}
