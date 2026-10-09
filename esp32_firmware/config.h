/* ==========================================
 * ESP32-CAM 云台追踪数字人系统 - 硬件端
 * 配置文件
 * ========================================== */
#pragma once

// ============ WiFi 配置 ============
#define WIFI_SSID       "Your-WiFi-SSID"
#define WIFI_PASSWORD   "Your-WiFi-Password"

// ============ MQTT 配置 ============
#define MQTT_BROKER     "192.168.1.100"   // 上位机 MQTT 服务器地址
#define MQTT_PORT       1883
#define MQTT_USERNAME   ""
#define MQTT_PASSWORD   ""
#define MQTT_CLIENT_ID "esp32-cam-ptz-001"

// 主题定义（必须与上位机 config.yaml 一致）
#define TOPIC_IMAGE_UPLOAD   "esp32/cam/image"
#define TOPIC_PTZ_CONTROL    "esp32/ptz/control"
#define TOPIC_PTZ_STATUS     "esp32/ptz/status"
#define TOPIC_HEARTBEAT      "esp32/heartbeat"

// ============ 摄像头配置 ============
#define CAMERA_MODEL_AI_THINKER   // ESP32-CAM 模块
#define FRAME_SIZE        FRAMESIZE_VGA   // 640x480
#define JPEG_QUALITY      12             // 0-63, 越小质量越高
#define FRAME_INTERVAL_MS 80             // 帧间隔 ≈ 12.5 FPS

// ============ MQTT 大包配置 ============
#define MQTT_MAX_PACKET_SIZE  60000      // PubSubClient 最大包
#define MQTT_BUFFER_SIZE      60000
#define IMAGE_CHUNK_SIZE      4096      // 分片上传每片大小
#define CHUNK_DELAY_MS        5         // 分片发送间隔

// ============ RS485 云台驱动配置 ============
#define RS485_SERIAL       Serial2
#define RS485_BAUDRATE     9600
#define RS485_DE_PIN       14           // MAX485 DE/RE 共阳使能引脚（驱动发送）
#define RS485_DE_ACTIVE    HIGH         // 使能有效电平

// 云台协议（自定义 ASCII，按需修改）
#define PTZ_BROADCAST_ADDR 0x01         // 云台地址
#define PTZ_CMD_ABS        'A'         // 绝对角度移动
#define PTZ_CMD_REL        'R'         // 相对角度移动
#define PTZ_CMD_QUERY      'Q'         // 查询当前角度
#define PTZ_CMD_STOP       'S'         // 急停

// ============ 物理限位 ============
#define PTZ_X_MIN    (-90.0f)
#define PTZ_X_MAX    ( 90.0f)
#define PTZ_Y_MIN    (-45.0f)
#define PTZ_Y_MAX    ( 45.0f)

// ============ 状态回传 ============
#define STATUS_REPORT_INTERVAL_MS  500  // 状态回传间隔

// ============ 心跳 ============
#define HEARTBEAT_INTERVAL_MS  3000
