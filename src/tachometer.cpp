#include <Arduino.h>
#include <driver/i2s.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <math.h>

// ===== TFT 設定 (請確保這些腳位在你的 S3 開發板上有引出) =====
#define TFT_CS     5    // 安全
#define TFT_DC     16   // 安全
#define TFT_RST    17   // 安全
#define TFT_BLK    15   // 【修正】原本是 27，改用 GPIO 15 避開 Flash 腳位

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

// ===== I2S 設定 =====
#define I2S_PORT I2S_NUM_0
#define PIN_I2S_BCLK 1  // 【修正】原本是 26，改用 GPIO 1 (安全)
#define PIN_I2S_LRCL 2  // 【修正】原本是 25，改用 GPIO 2 (安全)
#define PIN_I2S_DOUT 3  // 【修正】原本是 33，改用 GPIO 3 (安全，避開 PSRAM)

#define SAMPLE_RATE 8000
#define BLOCK_SIZE 512

// ===== DSP 參數 =====
#define FFT_SIZE 4096  // 調整為 4096 點以獲得更佳的即時動態響應
#define NUM_BINS (FFT_SIZE / 2 + 1)

// 雙核共享資料區
float rolling_buffer[FFT_SIZE] = {0};
float dsp_input_buffer[FFT_SIZE] = {0};
volatile bool bNewDataAvailable = false;

float current_freq = 0;
float current_rpm = 0;
bool signal_detected = false;
unsigned long lastDisplayMillis = 0;

// 宣告核心 1 的 DSP 任務控制
TaskHandle_t dspTaskHandle;

// ===== 輕量化向前 FFT 實現 (基 2 庫利-圖基演算法) =====
void fft(float* re, float* im, int n) {
    int i, j, k;
    for (i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float t = re[i]; re[i] = re[j]; re[j] = t;
            t = im[i]; im[i] = im[j]; im[j] = t;
        }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float ang = 2.0 * M_PI / len;
        float wlen_re = cos(ang);
        float wlen_im = -sin(ang);
        for (i = 0; i < n; i += len) {
            float w_re = 1.0;
            float w_im = 0.0;
            for (j = 0; j < len / 2; j++) {
                int u = i + j;
                int v = i + j + len / 2;
                float t_re = re[v] * w_re - im[v] * w_im;
                float t_im = re[v] * w_im + im[v] * w_re;
                re[v] = re[u] - t_re;
                im[v] = im[u] - t_im;
                re[u] += t_re;
                im[u] += t_im;
                float next_w_re = w_re * wlen_re - w_im * wlen_im;
                w_im = w_re * wlen_im + w_im * wlen_re;
                w_re = next_w_re;
            }
        }
    }
}

// ===== 核心 1：邊緣運算 DSP 核心任務 =====
void dspTask(void * pvParameters) {
    // 於核心 1 動態配置大型記憶體，避免堆疊溢位
    float* vReal = (float*)malloc(FFT_SIZE * sizeof(float));
    float* vImag = (float*)malloc(FFT_SIZE * sizeof(float));
    float* mag = (float*)malloc(NUM_BINS * sizeof(float));
    float* mag_white = (float*)malloc(NUM_BINS * sizeof(float));
    double* hps = (double*)malloc(NUM_BINS * sizeof(double));

    if (!vReal || !vImag || !mag || !mag_white || !hps) {
        Serial.println("====== [ERROR] Memory Allocation Failed! ======");
        while(1) { vTaskDelay(pdMS_TO_TICKS(1000)); }
    }

    while(true) {
        if (bNewDataAvailable) {
            // 複製快照，釋放鎖定
            memcpy(dsp_input_buffer, rolling_buffer, FFT_SIZE * sizeof(float));
            bNewDataAvailable = false;

            // 1. 加漢寧窗 (Hanning Window) 與初始化複數陣列
            for (int i = 0; i < FFT_SIZE; i++) {
                float window = 0.5f * (1.0f - cos(2.0f * M_PI * i / (FFT_SIZE - 1)));
                vReal[i] = dsp_input_buffer[i] * window;
                vImag[i] = 0.0f;
            }

            // 2. 執行 FFT
            fft(vReal, vImag, FFT_SIZE);

            // 3. 計算振幅 (Magnitude)
            for (int i = 0; i < NUM_BINS; i++) {
                mag[i] = sqrt(vReal[i] * vReal[i] + vImag[i] * vImag[i]);
            }

            // 4. 頻譜白化 (Spectral Whitening) - 滑動視窗大小 51
            int kernel_size = 51;
            int half_k = kernel_size / 2;
            for (int i = 0; i < NUM_BINS; i++) {
                float sum = 0.0f;
                int count = 0;
                for (int j = -half_k; j <= half_k; j++) {
                    int idx = i + j;
                    if (idx >= 0 && idx < NUM_BINS) {
                        sum += mag[idx];
                        count++;
                    }
                }
                float local_avg = sum / count;
                mag_white[i] = mag[i] / (local_avg + 1e-6f);
            }

            // 5. 加權 HPS 計算 (諧波階數: 4)
            for (int i = 0; i < NUM_BINS; i++) {
                hps[i] = (double)mag_white[i];
            }
            for (int h = 2; h <= 4; h++) {
                int L = (NUM_BINS + h - 1) / h;
                for (int i = 0; i < L; i++) {
                    int downsampled_idx = i * h;
                    if (downsampled_idx < NUM_BINS) {
                        double weight = 1.0 / (h * 0.4);
                        hps[i] *= pow((double)mag_white[downsampled_idx], weight);
                    }
                }
            }

            // 6. HPS 最小峰值搜尋與低頻鎖定 (搜尋區間 >= 10Hz)
            float bin_res = (float)SAMPLE_RATE / FFT_SIZE;
            int min_idx = (int)(10.0f / bin_res);
            int max_idx = NUM_BINS - 1;

            double hps_max = 0;
            for (int i = min_idx; i <= max_idx; i++) {
                if (hps[i] > hps_max) hps_max = hps[i];
            }

            int best_idx = -1;
            // 尋找第一個超過最大值 5% 的顯著局部峰值
            for (int i = min_idx + 1; i < max_idx - 1; i++) {
                if (hps[i] > hps[i-1] && hps[i] > hps[i+1]) { // 局部極大值
                    if (hps[i] >= hps_max * 0.05) {
                        // 距離過濾 (周圍 10 個 bin 內必須是最大)
                        bool is_peak = true;
                        for (int d = -10; d <= 10; d++) {
                            if (i + d >= min_idx && i + d < NUM_BINS) {
                                if (hps[i+d] > hps[i]) { is_peak = false; break; }
                            }
                        }
                        if (is_peak) {
                            best_idx = i;
                            break; // 鎖定頻率最低的顯著峰值
                        }
                    }
                }
            }

            // 7. 驗證基頻振幅門檻並利用拋物線內插細估頻率
            if (best_idx > 0 && best_idx < NUM_BINS - 1) {
                float mag0 = mag[best_idx];
                if (mag0 > 1000.0f) {
                    // 拋物線內插 (Parabolic Interpolation)
                    float y1 = mag[best_idx - 1];
                    float y2 = mag[best_idx];
                    float y3 = mag[best_idx + 1];
                    float p = 0.5f * (y1 - y3) / (y1 - 2.0f * y2 + y3);
                    float refined_idx = (float)best_idx + p;

                    current_freq = refined_idx * bin_res;
                    current_rpm = current_freq * 60.0f;
                    signal_detected = true;
                } else {
                    signal_detected = false;
                }
            } else {
                signal_detected = false;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10)); // 避免餵狗事件
    }
}

// ===== 螢幕更新顯示 =====
void updateDisplay() {
    tft.setCursor(10, 80);
    tft.setTextSize(3);
    if (signal_detected) {
        tft.setTextColor(ST77XX_YELLOW, ST77XX_BLACK);
        tft.print("Hz: "); tft.print(current_freq, 2); tft.print("    ");
        
        tft.setCursor(10, 140);
        tft.setTextColor(ST77XX_CYAN, ST77XX_BLACK);
        tft.print("RPM: "); tft.print(current_rpm, 0); tft.print("    ");
    } else {
        tft.setTextColor(ST77XX_RED, ST77XX_BLACK);
        tft.print("No Signal...    ");
        tft.setCursor(10, 140);
        tft.print("RPM: --         ");
    }
}

void setup() {
    Serial.begin(921600);
    delay(1000); // 讓 Serial 穩定，方便你看 Log
    Serial.println("System Initializing...");
    
    pinMode(4, OUTPUT);
    digitalWrite(4, HIGH);
    // ===== TFT init =====
    pinMode(TFT_BLK, OUTPUT); // 【修正】使用新的安全背光腳位 (15)
    digitalWrite(TFT_BLK, HIGH);  
    
    tft.init(240, 320);
    tft.setRotation(1);
    tft.fillScreen(ST77XX_BLACK);

    tft.setTextColor(ST77XX_GREEN);
    tft.setTextSize(2);
    tft.setCursor(10, 20);
    tft.println("Edge RPM Monitor");

    // ===== I2S 初始化 =====
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

    i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pin_config);

    // ===== 建立 FreeRTOS 核心 1 獨立任務 =====
    xTaskCreatePinnedToCore(
        dspTask,            // 任務函數
        "DSP_Task",         // 任務名稱
        10000,              // 配置 Stack 大小
        NULL,               // 參數
        1,                  // 優先權
        &dspTaskHandle,     // 任務控制把手
        1                   // 指定跑在 Core 1
    );
}

void loop() {
    // 核心 0 主要運行 loop：負責 I2S 讀取與 UI 刷新
    int32_t samples[BLOCK_SIZE];
    size_t bytes_read;

    esp_err_t result = i2s_read(I2S_NUM_0, &samples, sizeof(samples), &bytes_read, portMAX_DELAY);

    if (result == ESP_OK && bytes_read > 0) {
        // 滾動移動緩衝區 (向左位移)
        memmove(rolling_buffer, rolling_buffer + BLOCK_SIZE, (FFT_SIZE - BLOCK_SIZE) * sizeof(float));
        
        // 填入全新採樣音訊
        for (int i = 0; i < BLOCK_SIZE; i++) {
            rolling_buffer[FFT_SIZE - BLOCK_SIZE + i] = (float)(samples[i] >> 14);
        }

        // 通知 Core 1 可以動工計算
        if (!bNewDataAvailable) {
            bNewDataAvailable = true;
        }
    }

    // 固定頻率更新 TFT，並同步回傳給電腦端
    if (millis() - lastDisplayMillis > 100) {
        updateDisplay();
        
        // 發送自訂同步通訊協定包回傳電腦 (格式與原架構相同，方便電腦讀取)
        if (signal_detected) {
            uint8_t header[2] = {0xAA, 0x55};
            Serial.write(header, 2);
            Serial.write((uint8_t*)&current_freq, 4);
            Serial.write((uint8_t*)&current_rpm, 4);
        } else {
            uint8_t header[2] = {0xAA, 0x55};
            float zero = 0.0f;
            Serial.write(header, 2);
            Serial.write((uint8_t*)&zero, 4);
            Serial.write((uint8_t*)&zero, 4);
        }
        
        lastDisplayMillis = millis();
    }
}