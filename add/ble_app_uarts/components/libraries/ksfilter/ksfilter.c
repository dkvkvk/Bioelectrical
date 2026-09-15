#include "ksfilter.h"


#define HEAD_INC( var, n, max)				( var = (var + n) % max )
static double sum_sample = 0;
static double sample_buf[M] = {0};
static int sample_buf_head = 0;



//去除50HZ工频（滑动平均滤波算法）
extern double power_50HZ(double x)
{
    double aver = 0;
	
	 
	  sum_sample -= sample_buf[sample_buf_head];
	  sample_buf[sample_buf_head] = x;
	  sum_sample += sample_buf[sample_buf_head];
	  HEAD_INC( sample_buf_head, 1, M);

	  aver = sum_sample / (M/2);
	 
	  return aver;
}

static double sum_sample1 = 0;
static double sample_buf1[M] = {0};
static int sample_buf_head1 = 0;



//去除50HZ工频
extern double power1_50HZ(double x)
{
    double aver = 0;
	
	 
	  sum_sample1 -= sample_buf1[sample_buf_head1];
	  sample_buf1[sample_buf_head1] = x;
	  sum_sample1 += sample_buf1[sample_buf_head1];
	  HEAD_INC( sample_buf_head1, 1, M);

	  aver = sum_sample1 / (M/2);
	 
	  return aver;
}



//Q=200;   %Q参数可调，Q越大，波形保真度越好，去基漂能力越差，Q最大425
//#define Q	425
static double buf_in[Q];
static double a3[Q];	// 缓存数据
static int in_head = 0;
static int a3_head = 0;

/*******************************************************************************
 * FUNC: filter
 *
 * DESC: 去除基线漂移
 */
extern double filter( double x )
{
	static double sum_buf_in = 0;
	static double sum_a3 = 0;
	double aver = 0;
	double f_data = 0;

	sum_buf_in -= buf_in[in_head];
	buf_in[in_head] = x;
	sum_buf_in += buf_in[in_head];
	HEAD_INC( in_head, 1, Q);
    
	aver = sum_buf_in / Q;

	sum_a3 -= a3[a3_head];
	a3[a3_head] = aver;
	sum_a3 += a3[a3_head];
	HEAD_INC( a3_head, 1, Q);
	
	aver = sum_a3 / Q;			// a4

	  f_data=x- aver;		// aa - a4;
	
	return f_data;
}


//Q=200;   %Q参数可调，Q越大，波形保真度越好，去基漂能力越差，Q最大425
//#define Q	425
static double buf_in1[Q];
static double a31[Q];	// 缓存数据
static int in_head1 = 0;
static int a3_head1 = 0;

/*******************************************************************************
 * FUNC: filter
 *
 * DESC: 去除基线漂移
 */
extern double filter1( double x )
{
	static double sum_buf_in1 = 0;
	static double sum_a31 = 0;
	double aver = 0;
	double f_data = 0;

	sum_buf_in1 -= buf_in1[in_head1];
	buf_in1[in_head1] = x;
	sum_buf_in1 += buf_in1[in_head1];
	HEAD_INC( in_head1, 1, Q);
    
	aver = sum_buf_in1 / Q;

	sum_a31 -= a31[a3_head1];
	a31[a3_head1] = aver;
	sum_a31 += a31[a3_head1];
	HEAD_INC( a3_head1, 1, Q);
	
	aver = sum_a31 / Q;			// a4

	  f_data=x- aver;		// aa - a4;
	
	return f_data;
}

//去除50HZ工频和基线漂移
extern double Filter_All(double x)
{
    return filter(power_50HZ(x));
}


//去除50HZ工频和基线漂移
extern double Filter1_All(double x)
{
    return filter1(power1_50HZ(x));
}


