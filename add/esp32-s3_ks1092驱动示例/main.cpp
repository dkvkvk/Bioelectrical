#include <Arduino.h>
#include <SPI.h>
#include "KS1082.h"
#include "myspi.h"
#include <stdio.h>

// 定义测试用的寄存器数据（根据KS1082手册调整）
#define TEST_CH1_DATA 0x38  // 通道1配置值 
#define TEST_CH2_DATA 0x18  // 通道2配置值

// ADC引脚定义 (ADC1_CH0=GPIO1, ADC1_CH1=GPIO2)
#define ADC_PIN_1 1    // 第一个ADC引脚 (通道0)
#define ADC_PIN_2 2    // 第二个ADC引脚 (通道1)

// PWM配置
#define PWM_PIN 18     // PWM输出引脚
#define PWM_CHANNEL 0  // PWM通道
#define PWM_FREQ 500   // PWM频率（Hz）- 也是采样频率
#define PWM_RESOLUTION 8 // PWM分辨率

// 全局变量
volatile bool sample_flag = false; // 采样触发标志

// PWM中断处理函数
void IRAM_ATTR onPwmTrigger() {
  sample_flag = true;
}

void testKS1082() {
  // 初始化KS1082和SPI接口
  KS1082_Init();
  KS1082_Write_Reg(ks1082_REG_ADDR_CH1SET, TEST_CH1_DATA);
  KS1082_Write_Reg(ks1082_REG_ADDR_CH2SET, TEST_CH2_DATA);
}

void setup() {
  testKS1082();// 测试KS1082初始化和寄存器写入
  
  // 初始化串口通信
  Serial.begin(115200);
  while (!Serial) {;
  }
  
  // 配置ADC参数
  analogReadResolution(12);  // 设置ADC分辨率为12位
  analogSetPinAttenuation(ADC_PIN_1, ADC_11db);  // 设置第一个ADC引脚的衰减值为11db
  analogSetPinAttenuation(ADC_PIN_2, ADC_11db);  // 设置第二个ADC引脚的衰减值为11db
  pinMode(ADC_PIN_1, INPUT);  // 设置第一个ADC引脚为输入模式
  pinMode(ADC_PIN_2, INPUT);  // 设置第二个ADC引脚为输入模式
  
  // 配置PWM输出
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PWM_PIN, PWM_CHANNEL);
  ledcWrite(PWM_CHANNEL, 128); // 50%占空比
  
  // 配置PWM中断触发
  attachInterrupt(digitalPinToInterrupt(PWM_PIN), onPwmTrigger, RISING);
  
  delay(3000);
}

void loop() {
  // 当PWM触发中断时进行ADC采样
  if (sample_flag) {
    sample_flag = false;
    
    // 执行双通道ADC采样
    int analogvolts1 = analogReadMilliVolts(ADC_PIN_1);
    int analogvolts2 = analogReadMilliVolts(ADC_PIN_2);
    
    // 转换为电压值
    float voltage1 = analogvolts1 / 1000.0f;
    float voltage2 = analogvolts2 / 1000.0f;
    
    // 直接输出原始采样转换后的电压值
    Serial.printf("Ch1: %.3fV, Ch2: %.3fV\n", voltage1, voltage2);
  }
  
  // 可以添加其他非阻塞任务
}