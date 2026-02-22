import serial
import numpy as np
import matplotlib.pyplot as plt

# ======================
# Serial 設定
# ======================
ser = serial.Serial('COM6', 115200, timeout=0.1)

# ======================
# 系統參數（需與 ESP32 相同）
# ======================
SAMPLE_RATE = 40000
N_SAMPLES = 1024
FREQ_MAX = 20000

freq_res = SAMPLE_RATE / N_SAMPLES
N_BINS = int(FREQ_MAX / freq_res)
freq_axis = np.arange(1, N_BINS + 1) * freq_res

# ======================
# Buffers
# ======================
raw_buffer = np.zeros(N_SAMPLES)
spectrum = np.zeros(N_BINS)
peak_freq = 0.0

# ======================
# Matplotlib init
# ======================
plt.ion()
fig, (ax_time, ax_freq, ax_info) = plt.subplots(
    3, 1, figsize=(9, 8),
    gridspec_kw={'height_ratios': [2, 2, 1]}
)

# 畫空圖，啟動 GUI
ax_time.plot(raw_buffer)
ax_time.set_title("Time Domain")
ax_freq.plot(freq_axis, spectrum)
ax_freq.set_title("Frequency Spectrum")
ax_info.axis("off")
plt.show(block=False)

print("Waiting for data...")

# ======================
# Main loop
# ======================
while True:
    try:
        line = ser.readline().decode(errors='ignore').strip()
        if not line:
            plt.pause(0.01)
            continue

        # ---------- 時域資料 ----------
        if line.startswith("TD"):
            parts = line.split(",")[1:]
            if len(parts) != N_SAMPLES:
                continue
            raw_buffer = np.array(parts, dtype=np.int16)

            ax_time.cla()
            ax_time.plot(raw_buffer)
            ax_time.set_ylim(-10000, 10000)
            ax_time.set_title("Time Domain (Raw)")
            ax_time.set_xlabel("Sample")
            ax_time.set_ylabel("Amplitude")
            ax_time.grid(True)

        # ---------- 頻譜 ----------
        elif line.startswith("SPEC"):
            parts = line.split(",")[1:]
            if len(parts) != N_BINS:
                continue
            spectrum = np.array(parts, dtype=np.float32)

            ax_freq.cla()
            ax_freq.plot(freq_axis, spectrum)
            ax_freq.set_xlim(0, FREQ_MAX)
            ax_freq.set_title("Frequency Spectrum (ESP32 FFT)")
            ax_freq.set_xlabel("Frequency (Hz)")
            ax_freq.set_ylabel("Magnitude")
            ax_freq.grid(True)

        # ---------- 主頻 ----------
        elif line.startswith("MF"):
            try:
                peak_freq = float(line.split(",")[1])
            except:
                pass

        # ---------- 更新 info ----------
        ax_info.cla()
        ax_info.axis("off")
        ax_info.text(
            0.05, 0.5,
            f"Main Frequency: {peak_freq:.2f} Hz\n"
            f"Frequency Resolution: {freq_res:.2f} Hz/bin",
            fontsize=14
        )

        # 更新圖表
        plt.pause(0.01)

    except KeyboardInterrupt:
        print("Stopped by user")
        break
    except Exception as e:
        print("Error:", e)
        plt.pause(0.01)
