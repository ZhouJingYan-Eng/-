/* ==============================================================
 *   ESP32-CAM 云台追踪数字人系统 - 硬件端主程序
 *
 *   功能:
 *     1. WiFi 连接
 *     2. MQTT 连接 + 订阅云台控制主题
 *     3. ESP32-CAM 采集图像帧 -> JPEG -> MQTT 上传 (整包/分片)
 *     4. 接收云台控制指令 -> RS485 驱动 X/Y 云台
 *     5. 定时回传云台当前角度
 *     6. 心跳上报
 *
 *   硬件:
 *     - ESP32-CAM AI-Thinker 模块
 *     - MAX485 电平转换 (DE/RE 引脚 GPIO14)
 *     - RS485 二自由度 X/Y 云台
 *
 *   依赖库 (Arduino IDE 库管理器安装):
 *     - PubSubClient (by Nick O'Leary)
 *     - ArduinoJson (by Benoit Blanchon)
 *     - ESP32 Board Package (内置 esp_camera)
 *
 *   编译: 选择开发板 "AI Thinker ESP32-CAM"
 * ============================================================== */

#include <WiFi.h>
#include "config.h"
#include "camera_helper.h"
#include "ptz_driver.h"
#include "mqtt_handler.h"

// ----- 全局对象 -----
PtzDriver ptz;                    // 云台驱动
WiFiClient   net_client;          // WiFi 客户端
MqttHandler mqtt(net_client);     // MQTT 处理器

// ----- 帧采集定时 -----
unsigned long last_frame_ms = 0;
unsigned long last_status_ms = 0;

// ----- 内置 LED (用于状态指示) -----
#define LED_PIN 33   // ESP32-CAM 内置 LED (低有效)
bool led_state = false;

void blink_led(int times, int delay_ms = 100) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, LOW);  // 亮
    delay(delay_ms);
    digitalWrite(LED_PIN, HIGH); // 灭
    delay(delay_ms);
  }
}

// ==============================================================
//   setup / loop
// ==============================================================
void setup() {
  // 串口（调试输出）
  Serial.begin(115200);
  Serial.println();
  Serial.println("===== ESP32-CAM 数字人系统启动 =====");

  // 内置 LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // 默认熄灭

  // 1) 摄像头初始化
  if (!camera_init()) {
    Serial.println("[FATAL] 摄像头初始化失败，重启中...");
    blink_led(5, 200);
    ESP.restart();
  }

  // 2) 云台 RS485 串口
  ptz.begin();
  // 复位云台到中心
  ptz.move_abs(0.0f, 0.0f);

  // 3) WiFi + MQTT
  mqtt.begin();

  Serial.println("[SYS] 启动完成，进入主循环");
  blink_led(2, 100);
}

void loop() {
  // 喂狗: MQTT + WiFi
  mqtt.loop();

  // 周期任务: 采集图像帧 + 上传
  unsigned long now = millis();
  if (mqtt.connected() && (now - last_frame_ms >= FRAME_INTERVAL_MS)) {
    last_frame_ms = now;

    camera_fb_t *fb = camera_capture();
    if (fb) {
      // 帧指示灯亮一下
      digitalWrite(LED_PIN, LOW);

      // 上传图像（含分片回退）
      mqtt.publish_image(fb->buf, fb->len);

      // 释放帧缓冲
      camera_release(fb);

      // 灭灯
      digitalWrite(LED_PIN, HIGH);
    }
  }

  // 周期任务: 查询并回传云台当前角度
  if (mqtt.connected() && (now - last_status_ms >= STATUS_REPORT_INTERVAL_MS)) {
    last_status_ms = now;
    float x = 0.0f, y = 0.0f;
    if (ptz.query(x, y)) {
      mqtt.publish_status(x, y);
      Serial.printf("[PTZ] 当前角度 x=%.2f y=%.2f\n", x, y);
    } else {
      // 查询失败时不阻塞主循环
      Serial.println("[PTZ] 查询无回传");
    }
  }

  // 异步轮询 RS485 串口是否有异步状态
  // 部分云台会主动上报状态，这里被动接收
  float ax, ay;
  if (ptz.poll_response(ax, ay)) {
    mqtt.publish_status(ax, ay);
  }
}
