#include <Arduino.h>
#include <driver/i2s.h>

#define I2S_PORT I2S_NUM_0
#define PIN_I2S_BCLK 26
#define PIN_I2S_LRCL 25
#define PIN_I2S_DOUT 33

// 取樣率 16kHz，配合 Python 端 16384 點 FFT 可達成 < 1Hz 解析度
#define SAMPLE_RATE 8000
#define BLOCK_SIZE 512     

void setup() {
  Serial.begin(921600); 
  
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT, 
    .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT, // 設定為右聲道 (L/R pin 接 High)
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = BLOCK_SIZE,
    .use_apll = false
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = PIN_I2S_BCLK,
    .ws_io_num = PIN_I2S_LRCL,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = PIN_I2S_DOUT
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
}

void loop() {
  int32_t samples[BLOCK_SIZE];
  size_t bytes_read;

  esp_err_t result = i2s_read(I2S_PORT, &samples, sizeof(samples), &bytes_read, portMAX_DELAY);

  if (result == ESP_OK && bytes_read > 0) {
    int16_t out_samples[BLOCK_SIZE];
    for (int i = 0; i < BLOCK_SIZE; i++) {
      // 取出 24-bit 有效位元並縮放至 16-bit
      out_samples[i] = (int16_t)(samples[i] >> 14);
    }
    Serial.write((uint8_t*)out_samples, sizeof(out_samples));
  }
}