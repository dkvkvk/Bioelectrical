#include "heart_rate.h"

#define CHECK_GAP 5

static float rate_list[CHECK_GAP];
static int initialization = 0;
static int RealT_HR = 0;
static int fR = 0, fP = 0, sR = 0, sP = 0, flag_HR = 0;
static int time_out = 0;
static float hr_sample_rate = 500.0f;

void heart_rate_set_sample_rate(uint32_t sample_interval_us)
{
    hr_sample_rate = 1000000.0f / (float)sample_interval_us;
}

int get_heart_rate(float input)
{
    float slope = 0.0f;
    int RR = 0, i = 0;

    if (initialization < CHECK_GAP)
    {
        rate_list[initialization] = input;
        initialization++;
        return 0;
    }
    else
    {
        for (i = 0; i < CHECK_GAP - 1; i++)
        {
            rate_list[i] = rate_list[i + 1];
        }
        rate_list[CHECK_GAP - 1] = input;
    }

    slope = (-2.0f) * rate_list[0] + (-1.0f) * rate_list[1] + rate_list[CHECK_GAP - 2] + 2.0f * rate_list[CHECK_GAP - 1];

    if (slope < 100 || slope > 1000)
    {
        flag_HR++;
        time_out++;
        if (time_out > 1000)
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
                fR = 1;
                fP = flag_HR;
            }
            else if (sR == 0)
            {
                sR = 1;
                sP = flag_HR;

                if (sP - fP < 60)
                {
                    sR = 0;
                }
            }
        }
        flag_HR++;
    }
    else
    {
        RR = sP - fP;
        RealT_HR = 60.0f / ((float)RR / hr_sample_rate);
        fR = 0;
        sR = 0;
        flag_HR = 0;
    }

    return (int)RealT_HR;
}