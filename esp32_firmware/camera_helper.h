/* ==========================================
 * 摄像头初始化封装
 * 基于 esp_camera driver，支持 ESP32-CAM AI-Thinker
 * ========================================== */
#pragma once
#include "esp_camera.h"
#include "config.h"

// ============ 引脚映射 (AI-Thinker ESP32-CAM) ============
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

/**
 * 初始化摄像头
 * @return true 成功
 */
bool camera_init() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAME_SIZE;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count      = 2;

  // 初始化
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] 初始化失败: 0x%x\n", err);
    return false;
  }

  // 自动曝光、白平衡
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_framesize(s, FRAME_SIZE);
    s->set_quality(s, JPEG_QUALITY);
    s->set_brightness(s, 1);
    s->set_saturation(s, 0);
  }

  Serial.println("[CAM] 摄像头初始化成功");
  return true;
}

/**
 * 捕获一帧 JPEG
 * @return camera_fb_t* 帧缓冲（需 esp_camera_fb_return 释放），失败返回 nullptr
 */
camera_fb_t* camera_capture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] 捕获失败");
    return nullptr;
  }
  return fb;
}

/**
 * 释放帧缓冲
 */
void camera_release(camera_fb_t *fb) {
  if (fb) {
    esp_camera_fb_return(fb);
  }
}
