import serial
import tkinter as tk
from tkinter import messagebox
import time

# --- 設定 ---
SERIAL_PORT = 'COM3' 
BAUD_RATE = 115200

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0) # timeout=0 代表非阻塞讀取
    time.sleep(2)
except Exception as e:
    print(f"Serial Error: {e}")
    exit()

last_send_time = 0

def send_pulse(val):
    global last_send_time
    current_time = time.time()
    
    # 限制發送頻率，每 50ms 最多發送一次，除非是緊急停止
    if (current_time - last_send_time > 0.05) or int(val) == 1000:
        try:
            msg = f"{val}\n"
            ser.write(msg.encode())
            ser.flush() # 強制清空緩衝區
            last_send_time = current_time
            status_label.config(text=f"目前發送: {val} us")
        except Exception as e:
            print(f"Write Error: {e}")

def emergency_stop(event=None):
    slider.set(1000)
    entry_var.set("1000")
    send_pulse(1000)
    status_label.config(text="!!! STOP !!!", fg="red")

def on_slider_move(val):
    send_pulse(val)

def on_button_set():
    val = entry_var.get()
    send_pulse(val)

# --- GUI 介面 (與之前相同，僅修改 command 呼叫方式) ---
root = tk.Tk()
root.title("ESC穩定控制版")
root.geometry("400x400")

entry_var = tk.StringVar(value="1000")

tk.Label(root, text="ESC 精確控制", font=("Arial", 14)).pack(pady=10)

slider = tk.Scale(root, from_=1000, to_=2000, orient=tk.HORIZONTAL, 
                  length=300, command=on_slider_move)
slider.set(1000)
slider.pack(pady=10)

frame = tk.Frame(root)
frame.pack(pady=10)
tk.Entry(frame, textvariable=entry_var, width=10).pack(side=tk.LEFT)
tk.Button(frame, text="設定", command=on_button_set).pack(side=tk.LEFT, padx=5)

status_label = tk.Label(root, text="等待操作...", fg="blue")
status_label.pack(pady=10)

btn_stop = tk.Button(root, text="STOP (Space)", command=emergency_stop, 
                     bg="red", fg="white", font=("Arial", 12, "bold"), height=2, width=15)
btn_stop.pack(pady=20)

root.bind('<space>', emergency_stop)

def on_closing():
    emergency_stop()
    ser.close()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()