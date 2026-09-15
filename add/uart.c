// 新增：每次采样都发送串口数据，确保数据连续性
        // 填充串口数据数组，严格按照9字节格式
        uart_send_data[0] = 0xFF;           // 数据包头
        uart_send_data[1] = 0X09;           // 数据长度9字节
        uart_send_data[2] = 0X2E;           // 数据类型定义
        uart_send_data[3] = (uint8_t)(Send_Data >> 8);   // 通道1数据高字节
        uart_send_data[4] = (uint8_t)(Send_Data);        // 通道1数据低字节
        //对于KS1081单通道，第二通道直接置0
        // uart_send_data[5] = (uint8_t)(Send_Data1 >> 8);  // 通道2数据高字节
        // uart_send_data[6] = (uint8_t)(Send_Data1);       // 通道2数据低字节
        uart_send_data[5] = 0x00;  // 通道2数据高字节=0
        uart_send_data[6] = 0x00;  // 通道2数据低字节=0
        uart_send_data[7] = avg_rate;       // 平均心率
        
        // 计算CRC校验，注意这里计算前8个字节的CRC
        uart_send_data[8] = Fast_CRC_Cal8Bits(0x00, 8, uart_send_data); // CRC-8校验
        
        // 通过串口发送9字节数据
        for (int i = 0; i < 9; i++)
        {
            app_uart_put(uart_send_data[i]);
        }
		//新增串口数据传输代码结束
