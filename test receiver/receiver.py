import sys
import serial
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer

# 參數設定 (請確保與 ESP32 一致)
COM_PORT = 'COM6'
BAUD_RATE = 921600
SAMPLE_RATE = 8000
FFT_SIZE = 16384

class SpectrumAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP32 自適應 HPS 轉速分析儀 (含 HPS 頻譜顯示)")
        self.resize(1200, 950)

        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # 頂部數值顯示欄
        label_layout = QHBoxLayout()
        self.freq_label = QLabel("頻率: -- Hz")
        self.freq_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #00FF00; background-color: #111; padding: 10px;")
        self.rpm_label = QLabel("RPM: --")
        self.rpm_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #FFA500; background-color: #111; padding: 10px;")
        label_layout.addWidget(self.freq_label)
        label_layout.addWidget(self.rpm_label)
        self.layout.addLayout(label_layout)

        # 1. 時域波形圖
        self.pw1 = pg.PlotWidget(title="1. 時域波形 (Time Domain)")
        self.curve1 = self.pw1.plot(pen='c')
        self.pw1.setYRange(-10000, 10000)
        self.layout.addWidget(self.pw1)

        # 2. 原始頻域圖 (Raw FFT)
        self.pw2 = pg.PlotWidget(title="2. 原始頻譜 (Raw FFT Spectrum) - 顯示真實諧波")
        self.pw2.setLabel('bottom', 'Frequency', units='Hz')
        self.pw2.setXRange(0, SAMPLE_RATE / 2)
        self.pw2.showGrid(x=True, y=True)
        self.curve2 = self.pw2.plot(pen='m')
        # 基頻標記點
        self.peak_marker = pg.ScatterPlotItem(size=12, pen=pg.mkPen('w'), brush=pg.mkBrush(255, 255, 0))
        self.pw2.addItem(self.peak_marker)
        self.layout.addWidget(self.pw2)

        # 3. HPS 處理後頻譜 (新功能)
        self.pw3 = pg.PlotWidget(title="3.  HPS 頻譜 (用於鎖定基頻)")
        self.pw3.setLabel('bottom', 'Frequency', units='Hz')
        self.pw3.setXRange(0, SAMPLE_RATE / 2)
        self.pw3.showGrid(x=True, y=True)
        self.curve3 = self.pw3.plot(pen='y') # 用黃色區分
        self.layout.addWidget(self.pw3)

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
                    # 緩衝區邏輯
                    if len(ints) >= FFT_SIZE:
                        self.data_buffer = ints[-FFT_SIZE:]
                    else:
                        self.data_buffer = np.roll(self.data_buffer, -len(ints))
                        self.data_buffer[-len(ints):] = ints

                    self.curve1.setData(self.data_buffer[-1024:])

                    # 1. FFT 計算
                    window = np.hanning(FFT_SIZE)
                    yf = np.fft.rfft(self.data_buffer * window)
                    xf = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
                    mag = np.abs(yf)
                    
                    # --- 優化 A: 頻譜白化 (Spectral Whitening) ---
                    # 透過將頻譜除以其移動平均，強化突出的尖峰，壓低寬帶雜訊
                    # 這對於找出淹沒在雜訊中的無刷馬達基頻非常有效
                    kernel_size = 51 # 平滑窗口大小
                    if len(mag) > kernel_size:
                        local_avg = np.convolve(mag, np.ones(kernel_size)/kernel_size, mode='same')
                        mag_white = mag / (local_avg + 1e-6)
                    else:
                        mag_white = mag

                    # --- 優化 B: 加權 HPS (不再使用幾何平均) ---
                    # 直接相乘會讓倍頻關係強大的點爆發式成長
                    hps = np.copy(mag_white).astype(np.float64)
                    num_harmonics = 4 
                    max_idx = len(mag_white)
                    
                    for i in range(2, num_harmonics + 1):
                        L = int(np.ceil(max_idx / i))
                        downsampled = mag_white[::i][:L]
                        # 給予諧波適度的加權，避免高階諧波雜訊干擾
                        weight = 1.0 / (i * 0.4) 
                        hps[:L] *= (downsampled ** weight)
                    
                    # 這裡不再執行 np.power(hps, 1/counts)，保留相乘後的巨大差異

                    # 2. 更新圖表 (圖 2 畫原始，圖 3 畫白化後的 HPS)
                    self.curve2.setData(xf, mag)
                    self.curve3.setData(xf, hps)

                    # --- 優化 C: HPS 最小峰值搜尋 ---
                    # 無刷馬達的基頻即便在 HPS 之後可能還是比某些強大的電磁諧波弱
                    # 因此我們找「第一個超過最大值 30% 的峰值」
                    mask = (xf >= 10) & (xf <= (SAMPLE_RATE / 2))
                    hps_search = hps[mask]
                    xf_search = xf[mask]
                    
                    if len(hps_search) > 0:
                        hps_max = np.max(hps_search)
                        # 尋找所有顯著峰值
                        from scipy.signal import find_peaks
                        peaks, _ = find_peaks(hps_search, height=hps_max * 0.25, distance=20)
                        
                        if len(peaks) > 0:
                            # 核心關鍵：選取頻率最低的那個顯著峰值
                            best_idx = peaks[0] 
                            f0 = xf_search[best_idx]
                            
                            orig_idx = (np.abs(xf - f0)).argmin()
                            mag0 = mag[orig_idx]
                            
                            if mag0 > 1000: # 基本門檻
                                rpm = f0 * 60
                                self.freq_label.setText(f"基頻: {f0:.2f} Hz")
                                self.rpm_label.setText(f"RPM: {rpm:,.0f}")
                                self.peak_marker.setData([f0], [mag0])
                            else:
                                self.info_reset()
                        else:
                            self.info_reset()

            def info_reset(self):
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