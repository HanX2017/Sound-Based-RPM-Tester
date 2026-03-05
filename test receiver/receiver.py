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
FFT_SIZE = 16384  # 解析度 = 16000 / 16384 = 0.976 Hz

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

                # 1. 更新時域波形
                self.curve1.setData(self.data_buffer[-1024:])

                # 2. 計算 FFT
                window = np.hanning(FFT_SIZE)
                yf = np.fft.rfft(self.data_buffer * window)
                xf = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
                mag = np.abs(yf)

                # 3. 更新頻域圖
                self.curve2.setData(xf, mag)

                # 4. 尋找最小主頻 (基頻) 並計算 RPM
                mask = (xf > 10) 
                search_mag = mag[mask]
                search_xf = xf[mask]
                
                if len(search_mag) > 0:
                    max_val = np.max(search_mag)
                    peaks, _ = find_peaks(search_mag, height=max_val * 0.4, distance=10)
                    
                    if len(peaks) > 0:
                        # 選取最低頻率的峰值
                        fundamental_idx = peaks[0] 
                        f0 = search_xf[fundamental_idx] # 基頻 Hz
                        mag0 = search_mag[fundamental_idx]
                        
                        # 計算 RPM
                        rpm = f0 * 60

                        # 更新顯示文字
                        self.freq_label.setText(f"基頻: {f0:.2f} Hz")
                        self.rpm_label.setText(f"RPM: {rpm:,.0f}") # 使用千分位格式
                        self.peak_marker.setData([f0], [mag0])
                    else:
                        self.freq_label.setText("未偵測到信號")
                        self.rpm_label.setText("RPM: --")
                        self.peak_marker.setData([], [])

    def closeEvent(self, event):
        self.ser.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SpectrumAnalyzer()
    window.show()
    sys.exit(app.exec_())