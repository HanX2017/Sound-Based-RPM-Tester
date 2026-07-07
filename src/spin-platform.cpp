#include <SimpleFOC.h>

// 1. 設定馬達的「極對數」(Pole Pairs)
// 請根據你的無刷馬達實際極對數修改 (例如：2212馬達通常是 7，雲台馬達可能是 11 或 14)
BLDCMotor motor = BLDCMotor(7); 

// 2. L6234PD 驅動器引腳配置 (成功轉起來的組合 2)
#define PWM_A  16  // 對應 L6234PD IN1
#define PWM_B  17  // 對應 L6234PD IN2
#define PWM_C  5   // 對應 L6234PD IN3
#define EN_PIN 4   // 對應 L6234PD EN (高電平使能)

// 這裡把 driver 初始化中的 EN 引腳留空，改由我們在 setup 中手動精確控制
BLDCDriver3PWM driver = BLDCDriver3PWM(PWM_A, PWM_B, PWM_C);

// 串口指令解析（用於在 Monitor 動態給定轉速）
Commander command = Commander(Serial);
void doTarget(char* cmd) { command.scalar(&motor.target, cmd); }

void setup() {
  Serial.begin(115200);
  delay(1500); // 延長上電延時，讓電源與系統穩定
  Serial.println("--- System Booting (Open-Loop Test) ---");

  // 3. 驅動器初始化
  driver.voltage_power_supply = 12.0f; // 填入你的實際供電電壓 (V)
  driver.init();
  motor.linkDriver(&driver);

  // 4. 安全限制設定
  // 開環模式下馬達發熱較快，初次測試保持在 1.5V ~ 2.5V 較安全
  motor.voltage_limit = 2.0f;   // 限制輸出電壓在 2.0V
  motor.velocity_limit = 20.0f; // 限制最大速度 (rad/s)

  // 5. 設定為開環轉速模式
  motor.controller = MotionControlType::velocity_openloop;

  // 初始化馬達核心
  motor.init();

  // 6. 硬體完全初始化後，再手動拉高使能腳喚醒 L6234PD
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, HIGH); // 高電平使能

  // 增加串口指令
  command.add('T', doTarget, "target velocity");

  Serial.println("Open-loop test ready!");
  Serial.println("Use Serial Monitor to set speed, e.g., send 'T5' for 5 rad/s.");
}

void loop() {
  // 開環控制核心函數：持續計算並輸出 SVPWM 波形
  motor.move();

  // 處理串口指令 (如 T2, T5, T0)
  command.run();
}