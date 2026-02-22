#include <Arduino.h>
#include "driver/i2s.h"
#include <arduinoFFT.h>

#define I2S_PORT I2S_NUM_0
#define PIN_I2S_BCLK 26
#define PIN_I2S_LRCL 25
#define PIN_I2S_DOUT 33

#define SAMPLE_RATE 40000
#define N_SAMPLES 1024

int32_t i2s_buffer[N_SAMPLES];
double vReal[N_SAMPLES];
double vImag[N_SAMPLES];

arduinoFFT FFT(vReal, vImag, N_SAMPLES, SAMPLE_RATE);

void setup_i2s() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = N_SAMPLES,
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
    i2s_zero_dma_buffer(I2S_PORT);
}

void setup() {
    Serial.begin(115200);
    delay(500);
    setup_i2s();
}

void loop() {
    size_t bytes_read;
    i2s_read(I2S_PORT, i2s_buffer, sizeof(i2s_buffer),
             &bytes_read, portMAX_DELAY);

    int samples = bytes_read / sizeof(int32_t);
    if (samples != N_SAMPLES) return;

    // ========= 時域資料處理 =========
    Serial.print("TD,");
    for (int i = 0; i < N_SAMPLES; i++) {
        int16_t sample = i2s_buffer[i] >> 14;  // 取有效音訊
        Serial.print(sample);
        if (i < N_SAMPLES - 1) Serial.print(",");
        vReal[i] = sample;
        vImag[i] = 0;
    }
    Serial.println();

    // ========= FFT =========
    FFT.Windowing(FFT_WIN_TYP_HAMMING, FFT_FORWARD);
    FFT.Compute(FFT_FORWARD);
    FFT.ComplexToMagnitude();

    double peakFreq = FFT.MajorPeak();

    // ========= 傳送頻譜 =========
    Serial.print("SPEC,");

    int maxBin = (20000.0 * N_SAMPLES) / SAMPLE_RATE;

    for (int i = 1; i <= maxBin; i++) {
        Serial.print(vReal[i], 2);
        if (i < maxBin) Serial.print(",");
    }
    Serial.println();

    // ========= 傳送主頻 =========
    Serial.print("MF,");
    Serial.println(peakFreq, 2);

    delay(20);  // 約 50 FPS
}
