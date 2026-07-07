import serial
import time
import threading
import sys

# ==================== 🛠️ 雙串口埠與硬體設定 ====================
TACH_PORT = 'COM6'     # ⚠️ 你的「聲音轉速計 (ESP32-S3)」連接埠
MOTOR_PORT = 'COM4'    # ⚠️ 你的「轉速控制平台 (ESP32-E)」連接埠

TACH_BAUD = 921600     # 配合 tachometer.cpp
MOTOR_BAUD = 115200    # 配合 spin-platform.cpp
# ========================================================

# 全局共享數據變數
plat_rpm = 0.0
curr_amp = 0.0
tach_rpm = 0.0
tach_freq = 0.0
last_print_time = 0
_ser_motor_obj = None  # 用於在主執行緒下發指令的串口物件

def parse_tachometer_worker():
    """ 獨立執行緒：監聽聲音轉速計的邊緣運算結果 """
    global tach_rpm, tach_freq
    try:
        ser_tach = serial.Serial(TACH_PORT, TACH_BAUD, timeout=0.1)
        print(f"✅ [通訊建立] 聲音轉速計 ({TACH_PORT}) 已成功連線。")
    except Exception as e:
        print(f"❌ [通訊失敗] 無法開啟轉速計串口: {e}")
        return

    while True:
        if ser_tach.in_waiting:
            try:
                line = ser_tach.readline().decode('utf-8', errors='ignore').strip()
                # 解析格式 TACH_FREQ:xx.xx,TACH_RPM:xxxx
                if "TACH_RPM" in line and "TACH_FREQ" in line:
                    parts = line.split(',')
                    tach_freq = float(parts[0].split(':')[1])
                    tach_rpm = float(parts[1].split(':')[1])
                    trigger_dashboard_print()
            except Exception:
                pass
        time.sleep(0.002) # 微秒級休眠，防止 CPU 空轉

def parse_motor_platform_worker():
    """ 獨立執行緒：監聽馬達平台回報的「當前實時轉速」與「電流」 """
    global plat_rpm, curr_amp, _ser_motor_obj
    try:
        ser_motor = serial.Serial(MOTOR_PORT, MOTOR_BAUD, timeout=0.1)
        _ser_motor_obj = ser_motor
        print(f"✅ [通訊建立] 轉速控制平台 ({MOTOR_PORT}) 已成功連線。")
    except Exception as e:
        print(f"❌ [通訊失敗] 無法開啟馬達平台串口: {e}")
        return

    while True:
        if ser_motor.in_waiting:
            try:
                line = ser_motor.readline().decode('utf-8', errors='ignore').strip()
                
                # 🛡️ 檢查是否有觸發馬達板的硬體保護
                if "OVERCURRENT_STALL" in line:
                    print("\n⚠️ ⚠️ ⚠️ [警告] 轉速平台觸發硬體電流過載保護！馬達已緊急停機！")
                    
                # 解析格式 PLAT_RPM:xxxx.xx,CURR:x.xx
                elif "PLAT_RPM" in line and "CURR" in line:
                    parts = line.split(',')
                    plat_rpm = float(parts[0].split(':')[1])
                    curr_amp = float(parts[1].split(':')[1])
                    trigger_dashboard_print()
            except Exception:
                pass
        time.sleep(0.002)

def trigger_dashboard_print():
    """ 限制刷新頻率的實時對比數據列印 """
    global last_print_time
    current_time = time.time()
    
    # 限制終端機輸出頻率為每 100 毫秒一次 (10 Hz)，避免洗版過快導致電腦卡頓
    if current_time - last_print_time > 0.1:
        # 計算轉速計測量值與平台「當下實際轉速」的絕對誤差
        absolute_error = tach_rpm - plat_rpm
        
        # 輸出具備工程對齊美感的即時數據列印
        log_msg = (
            f"📊 [對比數據] "
            f"平台實際: {plat_rpm:8.1f} RPM | "
            f"轉速計讀數: {tach_rpm:8.1f} RPM | "
            f"絕對誤差: {absolute_error:+6.1f} RPM | "
            f"電流: {curr_amp:.2f} A"
        )
        print(log_msg)
        last_print_time = current_time

if __name__ == '__main__':
    print("=================================================================")
    print(" 🔄 BLDC 轉速控制平台 與 邊緣運算聲音轉速計 自動化中繼控制大腦 ")
    print("=================================================================")
    
    # 啟動雙下位機監聽後台任務
    threading.Thread(target=parse_tachometer_worker, daemon=True).start()
    threading.Thread(target=parse_motor_platform_worker, daemon=True).start()

    # 等待串口初始化與連線穩定
    time.sleep(1.5)

    print("\n💡 系統整合完畢！請輸入你想要測試的目標轉速 (RPM)。")
    print("   馬達會自動遵循 Ramp 限制進行安全滑行升速。")
    print("   (輸入 0 停止馬達，輸入 exit 可安全關閉整個控制系統)")

    try:
        while True:
            # 獲取使用者輸入
            user_input = input().strip()
            
            if user_input.lower() == 'exit':
                if _ser_motor_obj and _ser_motor_obj.is_open:
                    _ser_motor_obj.write(b"0\n") # 停機指令
                print("正在關閉串口，安全退出專案...")
                break
                
            try:
                rpm_command = float(user_input)
                if _ser_motor_obj and _ser_motor_obj.is_open:
                    # 向馬達控制板發送轉速指令，尾端務必加上 \n
                    _ser_motor_obj.write(f"{rpm_command}\n".encode())
                    print(f"🚀 [指令下發] 目標已設定為: {rpm_command} RPM，正在追隨轉速...")
                else:
                    print("❌ [錯誤] 馬達平台尚未建立通訊，無法發送指令！")
            except ValueError:
                print("❌ [錯誤] 輸入格式不正確！請輸入純數字。")
                
    except KeyboardInterrupt:
        print("\n程序被手動中斷，安全終止。")