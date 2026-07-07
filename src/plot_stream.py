import sys
import struct
import serial
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer

# 參數設定
COM_PORT = 'COM9'  # 請根據你的 S3 實際埠號修改
BAUD_RATE = 921600

class DataMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP32-S3 邊緣運算轉速計 - 電腦同步看板")
        self.resize(600, 200)

        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # 頂部數值顯示欄
        label_layout = QHBoxLayout()
        self.freq_label = QLabel("基頻: -- Hz")
        self.freq_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #00FF00; background-color: #111; padding: 20px; border-radius: 5px;")
        
        self.rpm_label = QLabel("RPM: --")
        self.rpm_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFA500; background-color: #111; padding: 20px; border-radius: 5px;")
        
        label_layout.addWidget(self.freq_label)
        label_layout.addWidget(self.rpm_label)
        self.layout.addLayout(label_layout)

        try:
            self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
            print(f"成功連線至 {COM_PORT}")
        except Exception as e:
            print(f"無法開啟串口: {e}")
            sys.exit()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(30)  # 高頻監聽串口

    def update_data(self):
        # 尋找前導標頭 0xAA 0x55 且後面至少有 8 位元組的資料 (float*2)
        while self.ser.in_waiting >= 10:
            if self.ser.read(1) == b'\xAA':
                if self.ser.read(1) == b'\x55':
                    raw_payload = self.ser.read(8)
                    f0, rpm = struct.unpack('ff', raw_payload)
                    
                    if f0 > 0:
                        self.freq_label.setText(f"基頻: {f0:.2f} Hz")
                        self.rpm_label.setText(f"RPM: {rpm:,.0f}")
                    else:
                        self.info_reset()

    def info_reset(self):
        self.freq_label.setText("未偵測到訊號")
        self.rpm_label.setText("RPM: --")

    def closeEvent(self, event):
        if self.ser.is_open:
            self.ser.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DataMonitor()
    window.show()
    sys.exit(app.exec_())