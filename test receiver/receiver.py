import sys
import serial
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont
from scipy.signal import find_peaks

# 參數設定
COM_PORT = 'COM6'
BAUD_RATE = 921600
SAMPLE_RATE = 8000
FFT_SIZE = 32768  # 解析度 = 16000 / 16384 = 0.976 Hz

class SpectrumAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP32 右聲道 RPM & 基頻分析儀")
        self.resize(1200, 850)

        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # 文字顯示區域 (使用水平佈局放兩組資訊)
        label_layout = QHBoxLayout()
        
        # 頻率顯示
        self.freq_label = QLabel("頻率: -- Hz")
        self.freq_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00FF00; background-color: #111; padding: 15px; border-radius: 5px;")
        
        # RPM 顯示 (更醒目的顏色)
        self.rpm_label = QLabel("RPM: --")
        self.rpm_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFA500; background-color: #111; padding: 15px; border-radius: 5px;")
        
        label_layout.addWidget(self.freq_label)
        label_layout.addWidget(self.rpm_label)
        self.layout.addLayout(label_layout)

        # 時域圖
        self.pw1 = pg.PlotWidget(title="時域波形 (Time Domain)")
        self.curve1 = self.pw1.plot(pen='c')
        self.pw1.setYRange(-10000, 10000)
        self.layout.addWidget(self.pw1)

        # 頻域圖
        self.pw2 = pg.PlotWidget(title=f"頻域分析 (FFT Spectrum) - 解析度: {SAMPLE_RATE/FFT_SIZE:.3f} Hz")
        self.pw2.setLabel('bottom', 'Frequency', units='Hz')
        self.pw2.setXRange(0, SAMPLE_RATE / 2) 
        self.pw2.showGrid(x=True, y=True)
        self.curve2 = self.pw2.plot(pen='m')
        
        # 峰值標記
        self.peak_marker = pg.ScatterPlotItem(size=12, pen=pg.mkPen('w'), brush=pg.mkBrush(255, 255, 0))
        self.pw2.addItem(self.peak_marker)
        self.layout.addWidget(self.pw2)

        try:
            self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        except Exception as e:
            print(f"無法開啟串口: {e}")
            sys.exit()

        self.data_buffer = np.zeros(FFT_SIZE)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(50) 

    def update(self):
        if self.ser.in_waiting > 0:
            raw_data = self.ser.read(self.ser.in_waiting)
            ints = np.frombuffer(raw_data, dtype=np.int16)
            
            if len(ints) > 0:
                if len(ints) >= FFT_SIZE:
                    self.data_buffer = ints[-FFT_SIZE:]
                else:
                    self.data_buffer = np.roll(self.data_buffer, -len(ints))
                    self.data_buffer[-len(ints):] = ints

                # 1. 更新時域波形 (顯示最近 1024 點)
                self.curve1.setData(self.data_buffer[-1024:])

                # 2. 計算 FFT
                window = np.hanning(FFT_SIZE)
                yf = np.fft.rfft(self.data_buffer * window)
                xf = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
                mag = np.abs(yf)
                
                # 預處理 mag 避免數值為 0 導致運算錯誤 (log 或 power)
                # 確保數值夠大以便運算，但不影響視覺
                mag_comp = np.maximum(mag, 1e-6)

                # 3. 執行「自適應幾何平均 HPS」演算法
                # 使用 float64 以避免大數相乘溢位
                hps = np.copy(mag_comp).astype(np.float64)
                
                # 建立計數陣列，紀錄每個頻率點目前乘了幾階諧波
                counts = np.ones_like(mag_comp, dtype=int)
                
                num_harmonics = 4 # 目標最高階數
                max_idx = len(mag_comp)
                
                for i in range(2, num_harmonics + 1):
                    # 動態計算：在此階數下，哪些頻率點的諧波還在頻譜範圍內
                    # L 是當前階數 i 下能容納的最大索引長度
                    L = int(np.ceil(max_idx / i))
                    
                    # 取得下採樣頻譜：mag[0], mag[i], mag[2i]...
                    downsampled = mag_comp[::i][:L]
                    
                    # 執行相乘：只針對「諧波還在範圍內」的低頻部分進行
                    hps[:L] *= downsampled
                    
                    # 更新這些點的相乘次數計數
                    counts[:L] += 1
                
                # 重要優化：幾何平均補償
                # 由於低頻點乘了 4 次，高頻點可能只乘了 1 或 2 次
                # 取 n 次方根 (n=counts) 讓不同頻段的數值具備可比性
                hps = np.power(hps, 1.0 / counts)

                # 4. 更新頻域圖 (繪圖維持顯示原始 mag)
                self.curve2.setData(xf, mag)

                # 5. 在自適應 HPS 頻譜中尋找主頻 (基頻 f0)
                # 排除 10Hz 以下雜訊，上限設為 Nyquist 頻率
                mask = (xf >= 10) & (xf <= (SAMPLE_RATE / 2))
                hps_search = hps[mask]
                xf_search = xf[mask]
                
                if len(hps_search) > 0:
                    # 經過幾何平均補償後，最強點即為正確基頻
                    best_idx = np.argmax(hps_search)
                    f0 = xf_search[best_idx]
                    
                    # 取得原始振幅用於標記與門檻判斷
                    orig_idx = (np.abs(xf - f0)).argmin()
                    mag0 = mag[orig_idx]
                    
                    # 設定門檻：原始訊號強度需大於 2000 才顯示
                    if mag0 > 2000:
                        rpm = f0 * 60
                        self.freq_label.setText(f"基頻(自適應HPS): {f0:.2f} Hz")
                        self.rpm_label.setText(f"RPM: {rpm:,.0f}")
                        self.peak_marker.setData([f0], [mag0])
                    else:
                        self.freq_label.setText("未偵測到顯著信號")
                        self.rpm_label.setText("RPM: --")
                        self.peak_marker.setData([], [])
    def closeEvent(self, event):
        self.ser.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SpectrumAnalyzer()
    window.show()
    sys.exit(app.exec_())