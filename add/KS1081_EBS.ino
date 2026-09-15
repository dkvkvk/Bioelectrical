/******************************************************************************
file name: KS1081_EBS.ino
Demo Program for KS1081 ECG Board (KS1081 EBS)
******************************************************************************/
/******************************************************************************
Designed by Kngsense Electronics
Web: www.ks-chip.com
E-mail:support@ks-chip.com
Date:08/07/2023
Copyright  Kingsense Electronics. All Rights Reserved. 
******************************************************************************/
/******************************************************************************
The KS1081 designed by Kingsense,is an integrated single-channel analog front-end chip for high performance low power ECG recording.  
It is widely used in the wearable/portable ECG devices and other weak signals acquisitions. This example shows a easy way to create 
an real-time ECG display by Processing. 
******************************************************************************/
/******************************************************************************
Resources:
This program requires a Processing sketch to view the data in real time.
Development environment specifics:
IDE: Arduino 1.8.19
Hardware: KS1081-EBS & Arduino UNO 
******************************************************************************/
#include<MsTimer2.h>
#include<TimerOne.h>

//HR
byte Vhigh;
byte Vlow;
float slope = 0;
float Rate_List[7];
float data;
float KS_gain;
float current_estimate;
float last_estimate = 0;
float error_measure = 1;
float error_estimate = 30;
float q = 0.8;
float KF;

//Filter
float b50Hz[3] = { 0.991196234823306321359837056661490350962 , 
                  -0.000000000000000121386529630327029776745, 
                   0.991196234823306321359837056661490350962};
float a50Hz[3] = { 1,
                  -0.000000000000000121386529630327029776745, 
                   0.982392469646612642719674113322980701923};
float w1 = 0;
float w2 = 0;
float w3 = 0;
float output;

int LDF_flag = 0;
int t_count = 0;

void setup() {
  // put your setup code here, to run once:
  // baud rate setup  
  Serial.begin(115200);
  MsTimer2::set(5, loop2);
  MsTimer2::start();
  Timer1.initialize(100000);
  Timer1.attachInterrupt(Timer_Check);
  //pinMode(10, INPUT); // Setup for leads off detection LO +
  //pinMode(11, INPUT); // Setup for leads off detection LO -
  attachInterrupt(digitalPinToInterrupt(2), LDF_Check, CHANGE);
  //attachInterrupt(digitalPinToInterrupt(2), LDF_Check2, LOW);
}

void LDF_Check()
{
  if(digitalRead(2) == 0)
  {
    //LDF_flag = 0;
    t_count = 0;
    Timer1.start();
  }
  else
  {
    Timer1.stop();
    LDF_flag = 1;
  }
}

void Timer_Check()
{
  t_count++;
  if(t_count > 10)
  {
    LDF_flag = 0;
    Timer1.stop();
  }
}

void loop2()
{
  if(LDF_flag == 0)
  {
    data = analogRead(A0);
    w1 = data - a50Hz[1] * w2 - a50Hz[2] * w3;
    output = b50Hz[0] * w1 + b50Hz[1] * w2 + b50Hz[2] * w3;
    w3 = w2;
    w2 = w1;
    float TempKF = KS_Filter(output);
    KF = TempKF * 0.3223;
    Serial.println(KF);
  }
  else
  {
    //data = digitalRead(2);
    //Serial.println(data);
    Serial.write('!');
  }
}

float KS_Filter(float mea)
{
  KS_gain = error_estimate / (error_estimate + error_measure);
  current_estimate = last_estimate + KS_gain * (mea - last_estimate);
  error_estimate = (1.0 - KS_gain) * error_estimate + fabs(last_estimate - current_estimate) * q;
  last_estimate = current_estimate;
  return current_estimate;
}

void loop() {
  // put your main code here, to run repeatedly:

}
