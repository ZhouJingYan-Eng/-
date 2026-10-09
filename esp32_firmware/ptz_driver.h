/* ==========================================
 * RS485 二自由度云台驱动
 * 使用 MAX485 + 硬件 Serial2（GPIO16/17）
 * 兼容 Pelco-D 风格的自定义 ASCII 协议
 *
 * 协议格式（ASCII 文本，回车结束）:
 *   $<addr>,<cmd>,<x>,<y>\r\n     绝对移动
 *   $<addr>,R,<dx>,<dy>\r\n       相对移动
 *   $<addr>,Q\r\n                 查询
 *   $<addr>,S\r\n                 急停
 *
 * 回传格式:
 *   #<addr>,<x>,<y>\r\n           当前角度
 * ========================================== */
#pragma once
#include <Arduino.h>
#include "config.h"

class PtzDriver {
public:
  PtzDriver() : _de_pin(RS485_DE_PIN), _addr(PTZ_BROADCAST_ADDR) {}

  void begin() {
    pinMode(_de_pin, OUTPUT);
    digitalWrite(_de_pin, !RS485_DE_ACTIVE);  // 默认接收
    RS485_SERIAL.begin(RS485_BAUDRATE);
    Serial.println("[PTZ] RS485 串口已启动");
  }

  /**
   * 移动到绝对角度
   * @param x X 轴角度 (度)
   * @param y Y 轴角度 (度)
   */
  void move_abs(float x, float y) {
    x = constrain_float(x, PTZ_X_MIN, PTZ_X_MAX);
    y = constrain_float(y, PTZ_Y_MIN, PTZ_Y_MAX);
    String cmd = String("$") + _addr + ",A," + String(x, 2) + "," + String(y, 2) + "\r\n";
    send(cmd);
  }

  /**
   * 相对移动
   */
  void move_rel(float dx, float dy) {
    String cmd = String("$") + _addr + ",R," + String(dx, 2) + "," + String(dy, 2) + "\r\n";
    send(cmd);
  }

  /**
   * 急停
   */
  void stop() {
    send(String("$") + _addr + ",S\r\n");
  }

  /**
   * 查询当前角度
   * @return true 收到回传，cur_x/cur_y 被填充
   */
  bool query(float &cur_x, float &cur_y) {
    send(String("$") + _addr + ",Q\r\n");
    // 等待回传
    unsigned long t0 = millis();
    String buf;
    while (millis() - t0 < 200) {
      while (RS485_SERIAL.available()) {
        char c = RS485_SERIAL.read();
        buf += c;
        if (c == '\n') {
          return parse_response(buf, cur_x, cur_y);
        }
      }
      delay(1);
    }
    return false;
  }

  /**
   * 异步轮询串口是否有回传
   * @return true 若解析到状态
   */
  bool poll_response(float &cur_x, float &cur_y) {
    while (RS485_SERIAL.available()) {
      char c = RS485_SERIAL.read();
      _rx_buf += c;
      if (c == '\n') {
        bool ok = parse_response(_rx_buf, cur_x, cur_y);
        _rx_buf = "";
        if (ok) return true;
      }
      // 缓冲过长则丢弃
      if (_rx_buf.length() > 128) _rx_buf = "";
    }
    return false;
  }

private:
  int _de_pin;
  uint8_t _addr;
  String _rx_buf;

  void send(const String &s) {
    digitalWrite(_de_pin, RS485_DE_ACTIVE);   // 使能发送
    delay(2);
    RS485_SERIAL.print(s);
    RS485_SERIAL.flush();
    digitalWrite(_de_pin, !RS485_DE_ACTIVE);  // 切回接收
  }

  bool parse_response(const String &s, float &x, float &y) {
    // 期望: #01,12.34,-45.67\r\n
    if (s.length() < 6 || s.charAt(0) != '#') return false;
    int p1 = s.indexOf(',');
    int p2 = s.indexOf(',', p1 + 1);
    if (p1 < 0 || p2 < 0) return false;
    String x_str = s.substring(p1 + 1, p2);
    String y_str = s.substring(p2 + 1);
    y_str.trim();
    x = x_str.toFloat();
    y = y_str.toFloat();
    return true;
  }

  static float constrain_float(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
  }
};
