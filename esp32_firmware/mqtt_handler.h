/* ==========================================
 * MQTT 处理封装
 * - WiFi 连接
 * - MQTT 连接/订阅/重连
 * - JPEG 图像分片上传
 * - 接收上位机云台控制指令
 * - 状态/心跳回传
 * ========================================== */
#pragma once
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config.h"

extern PtzDriver ptz;  // 由主 .ino 提供

class MqttHandler {
public:
  MqttHandler(WiFiClient &net) : _net(net), _client(_net) {}

  void begin() {
    _client.setServer(MQTT_BROKER, MQTT_PORT);
    _client.setBufferSize(MQTT_BUFFER_SIZE);
    _client.setKeepAlive(60);   // 心跳 60 秒
    _client.setCallback([this](char *t, byte *p, unsigned int l) {
      this->onMessage(t, p, l);
    });
  }

  /**
   * 在 loop 中调用
   */
  void loop() {
    if (WiFi.status() != WL_CONNECTED) {
      _reconnect_wifi();
    }
    if (!_client.connected()) {
      _reconnect_mqtt();
    }
    if (_client.connected()) {
      _client.loop();
      _heartbeat();
    }
  }

  bool connected() const { return _client.connected(); }

  /**
   * 分片上传图像帧
   * @param buf JPEG 字节缓冲
   * @param len 长度
   */
  void publish_image(const uint8_t *buf, size_t len) {
    if (!_client.connected()) return;

    // 方案 A：直接整包发布（适合 MQTT buffer 足够大）
    if (len <= MQTT_BUFFER_SIZE - 128) {
      _client.publish(TOPIC_IMAGE_UPLOAD, (const char *)buf, len);
      return;
    }

    // 方案 B：分片上传
    // 每片 IMAGE_CHUNK_SIZE 字节，base64 后发布 JSON
    // 格式: {"seq":0,"total":3,"data":"base64..."}
    size_t total = (len + IMAGE_CHUNK_SIZE - 1) / IMAGE_CHUNK_SIZE;
    size_t offset = 0;
    for (size_t seq = 0; seq < total; seq++) {
      size_t chunk_len = (offset + IMAGE_CHUNK_SIZE > len) ? (len - offset) : IMAGE_CHUNK_SIZE;
      String payload = "{\"seq\":" + String(seq) + ",\"total\":" + String(total) + ",\"data\":\"";
      payload += _base64_encode(buf + offset, chunk_len);
      payload += "\"}";
      _client.publish(TOPIC_IMAGE_UPLOAD, payload.c_str());
      offset += chunk_len;
      delay(CHUNK_DELAY_MS);
    }
  }

  /**
   * 发布云台当前角度
   */
  void publish_status(float x, float y) {
    if (!_client.connected()) return;
    StaticJsonDocument<128> doc;
    doc["x"] = x;
    doc["y"] = y;
    doc["t"] = millis();
    String s;
    serializeJson(doc, s);
    _client.publish(TOPIC_PTZ_STATUS, s.c_str());
  }

  /**
   * 发布心跳
   */
  void publish_heartbeat() {
    if (!_client.connected()) return;
    StaticJsonDocument<128> doc;
    doc["ip"] = WiFi.localIP().toString();
    doc["uptime"] = millis() / 1000;
    doc["rssi"] = WiFi.RSSI();
    doc["free_heap"] = ESP.getFreeHeap();
    String s;
    serializeJson(doc, s);
    _client.publish(TOPIC_HEARTBEAT, s.c_str());
  }

private:
  WiFiClient &_net;
  PubSubClient _client;
  unsigned long _last_heartbeat = 0;
  unsigned long _last_status_report = 0;

  void onMessage(char *topic, byte *payload, unsigned int length) {
    String t(topic);
    String msg;
    msg.reserve(length);
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

    if (t == TOPIC_PTZ_CONTROL) {
      _handle_ptz_control(msg);
    }
  }

  void _handle_ptz_control(const String &msg) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, msg);
    if (err) {
      Serial.println("[MQTT] PTZ 控制消息解析失败");
      return;
    }
    float x = doc["x"] | 0.0f;
    float y = doc["y"] | 0.0f;
    const char *mode = doc["mode"] | "auto";
    // 立即驱动云台
    ptz.move_abs(x, y);
    Serial.printf("[PTZ] 收到指令 x=%.2f y=%.2f mode=%s\n", x, y, mode);
  }

  void _reconnect_wifi() {
    Serial.print("[WIFI] 连接中 ");
    Serial.println(WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
      delay(500);
      Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.print("\n[WIFI] 已连接, IP: ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("\n[WIFI] 连接失败，重试");
    }
  }

  void _reconnect_mqtt() {
    Serial.println("[MQTT] 连接中...");
    bool ok;
    if (strlen(MQTT_USERNAME) > 0) {
      ok = _client.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD);
    } else {
      ok = _client.connect(MQTT_CLIENT_ID);
    }
    if (ok) {
      Serial.println("[MQTT] 已连接");
      _client.subscribe(TOPIC_PTZ_CONTROL);
      Serial.print("[MQTT] 订阅: ");
      Serial.println(TOPIC_PTZ_CONTROL);
    } else {
      Serial.print("[MQTT] 连接失败，rc=");
      Serial.println(_client.state());
      delay(2000);
    }
  }

  void _heartbeat() {
    unsigned long now = millis();
    if (now - _last_heartbeat >= HEARTBEAT_INTERVAL_MS) {
      _last_heartbeat = now;
      publish_heartbeat();
    }
  }

  // 简单 base64
  static const char _B64_TAB[];
  static String _base64_encode(const uint8_t *data, size_t len) {
    static const char tab[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    String out;
    int val = 0, valb = -6;
    for (size_t i = 0; i < len; i++) {
      val = (val << 8) + data[i];
      valb += 8;
      while (valb >= 0) {
        out += tab[(val >> valb) & 0x3F];
        valb -= 6;
      }
    }
    if (valb > -6) {
      out += tab[((val << 8) >> (valb + 8)) & 0x3F];
    }
    while (out.length() % 4) out += '=';
    return out;
  }
};

const char MqttHandler::_B64_TAB[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
