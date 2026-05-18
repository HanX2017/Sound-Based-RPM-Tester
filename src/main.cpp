#include <Arduino.h>
#include <driver/i2s.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

// ===== TFT 設定 =====
#define TFT_CS     5
#define TFT_DC     16
#define TFT_RST    17

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

// ===== I2S =====
#define I2S_PORT I2S_NUM_0
#define PIN_I2S_BCLK 26
#define PIN_I2S_LRCL 25
#define PIN_I2S_DOUT 33

#define SAMPLE_RATE 8000
#define BLOCK_SIZE 512

// ===== 顯示資料 =====
float current_freq = 0;
float current_rpm = 0;
unsigned long lastDisplayMillis = 0; // 用於限制重新整理頻率

void setup() {
  Serial.begin(921600);

  // ===== TFT init =====
  pinMode(27, OUTPUT);
  digitalWrite(27, HIGH);  // 背光開
  tft.init(240, 320);
  tft.setRotation(1);
  tft.fillScreen(ST77XX_BLACK);

  // 固定不變的標題只需在 setup 畫一次
  tft.setTextColor(ST77XX_GREEN);
  tft.setTextSize(2);
  tft.setCursor(10, 20);
  tft.println("RPM Monitor");

  // ===== I2S init =====
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,
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

// ===== 顯示更新 (修正後：不閃爍版本) =====
void updateDisplay() {
  // 技巧 1：移除 tft.fillRect，改用帶有背景色的 setTextColor
  
  // 更新 Hz
  tft.setCursor(10, 80);
  tft.setTextColor(ST77XX_YELLOW, ST77XX_BLACK); // 前景黃，背景黑
  tft.setTextSize(3);
  tft.print("Hz: ");
  tft.print(current_freq, 1);
  tft.print("      "); // 技巧 2：在結尾補空格，確保舊的大數字被短數字蓋掉

  // 更新 RPM
  tft.setCursor(10, 140);
  tft.setTextColor(ST77XX_CYAN, ST77XX_BLACK);  // 前景青，背景黑
  tft.print("RPM: ");
  tft.print(current_rpm, 0);
  tft.print("      "); // 同樣補空格
}

// ===== 接收 Python 回傳 =====
void handleSerialRX() {
  while (Serial.available() >= 10) {
    if (Serial.read() == 0xAA) {
      if (Serial.read() == 0x55) {
        float f, r;
        Serial.readBytes((char*)&f, 4);
        Serial.readBytes((char*)&r, 4);

        current_freq = f;
        current_rpm = r;

        // 技巧 3：限制更新頻率，每 100ms (10fps) 更新一次即可，避免佔用過多 CPU
        if (millis() - lastDisplayMillis > 100) {
          updateDisplay();
          lastDisplayMillis = millis();
        }
      }
    }
  }
}

void loop() {
  int32_t samples[BLOCK_SIZE];
  size_t bytes_read;

  // 1. I2S 讀取
  esp_err_t result = i2s_read(I2S_PORT, &samples, sizeof(samples), &bytes_read, portMAX_DELAY);

  if (result == ESP_OK && bytes_read > 0) {
    int16_t out_samples[BLOCK_SIZE];
    for (int i = 0; i < BLOCK_SIZE; i++) {
      out_samples[i] = (int16_t)(samples[i] >> 14);
    }
    Serial.write((uint8_t*)out_samples, sizeof(out_samples));
  }

  // 2. 處理回傳資料
  handleSerialRX();
}