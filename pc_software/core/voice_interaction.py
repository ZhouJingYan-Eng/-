"""
语音交互模块
- 麦克风录音 + VAD 静音检测
- 百度 ASR 语音转文字
- 智能问答 (自定义 API 或回退)
- 百度 TTS 文字转语音，播放 + 实时音量回调供数字人唇形同步
"""
import io
import json
import math
import os
import tempfile
import threading
import time
import wave
from typing import Optional, Callable

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import ConfigLoader
from core.logger import logger

# 百度 AIP SDK
try:
    from aip import AipSpeech
    _HAS_AIP = True
except Exception:
    AipSpeech = None
    _HAS_AIP = False

# pyaudio
try:
    import pyaudio
    _HAS_PYAUDIO = True
except Exception:
    pyaudio = None
    _HAS_PYAUDIO = False


class VoiceSignalHub(QObject):
    # 录音状态
    recording_started = pyqtSignal()
    recording_finished = pyqtSignal()
    # ASR 结果
    asr_result = pyqtSignal(str)
    # TTS 播放
    tts_play_started = pyqtSignal()
    tts_play_finished = pyqtSignal()
    tts_play_error = pyqtSignal(str)
    # 实时音量（用于唇形同步）
    audio_volume = pyqtSignal(float)
    # 问答回复
    qa_reply = pyqtSignal(str)
    # 状态
    status_changed = pyqtSignal(str)


class VoiceInteraction(QObject):
    """语音交互总控"""

    def __init__(self):
        super().__init__()
        self._cfg = ConfigLoader.get("voice", {})
        self._asr_cfg = self._cfg.get("asr", {})
        self._tts_cfg = self._cfg.get("tts", {})
        self._rec_cfg = self._cfg.get("record", {})
        self._qa_cfg = self._cfg.get("qa", {})
        self.signal = VoiceSignalHub()

        # AIP 客户端
        self._client = None
        if _HAS_AIP and self._asr_cfg.get("app_id"):
            self._client = AipSpeech(
                self._asr_cfg.get("app_id"),
                self._asr_cfg.get("api_key"),
                self._asr_cfg.get("secret_key"),
            )

        # pyaudio
        self._pa = None
        if _HAS_PYAUDIO:
            try:
                self._pa = pyaudio.PyAudio()
            except Exception as e:
                logger.warning(f"PyAudio 初始化失败: {e}")

        self._recording = False
        self._playing = False
        self._stop_flag = False
        self._record_thread: Optional[threading.Thread] = None

    # ---------- 录音 + ASR ----------
    def start_recording(self) -> bool:
        """开始录音，自动 VAD 检测静音后结束"""
        if not _HAS_PYAUDIO:
            self.signal.status_changed.emit("no_pyaudio")
            logger.error("PyAudio 未安装，无法录音")
            return False
        if not self._client:
            self.signal.status_changed.emit("no_baidu_key")
            logger.error("百度语音 AppID/Key 未配置")
            return False

        if self._recording:
            return False
        self._stop_flag = False
        self._recording = True
        self.signal.recording_started.emit()
        self.signal.status_changed.emit("recording")
        self._record_thread = threading.Thread(target=self._record_and_asr, daemon=True)
        self._record_thread.start()
        return True

    def stop_recording(self) -> None:
        self._stop_flag = True
        self._recording = False

    def _record_and_asr(self) -> None:
        try:
            audio_data = self._record_with_vad()
            if not audio_data:
                self.signal.status_changed.emit("recording_empty")
                self.signal.recording_finished.emit()
                return

            # ASR
            self.signal.status_changed.emit("asr")
            text = self._run_asr(audio_data)
            self.signal.asr_result.emit(text or "")
            self.signal.recording_finished.emit()
            if not text:
                self.signal.status_changed.emit("asr_empty")
                return

            logger.info(f"ASR 结果: {text}")

            # 智能问答
            self.signal.status_changed.emit("qa")
            reply = self._run_qa(text)
            self.signal.qa_reply.emit(reply)

            # TTS + 播放
            self.signal.status_changed.emit("tts")
            self._run_tts_and_play(reply)

        except Exception as e:
            logger.exception(f"语音交互异常: {e}")
            self.signal.status_changed.emit("error")
        finally:
            self._recording = False

    def _record_with_vad(self) -> bytes:
        """VAD 录音：检测静音自动结束"""
        chunk = int(self._rec_cfg.get("chunk", 1024))
        channels = int(self._rec_cfg.get("channels", 1))
        rate = int(self._rec_cfg.get("rate", 16000))
        fmt_width = int(self._rec_cfg.get("format_width", 2))
        silence_threshold = float(self._rec_cfg.get("silence_threshold", 500))
        silence_duration = float(self._rec_cfg.get("silence_duration", 1.5))
        max_dur = float(self._rec_cfg.get("max_record_duration", 10))

        stream = self._pa.open(
            format=self._pa.getFormatFromWidth(fmt_width),
            channels=channels,
            rate=rate,
            input=True,
            frames_per_buffer=chunk,
        )
        frames = []
        silence_count = 0
        silence_frames_needed = int(silence_duration * rate / chunk)
        total_frames_needed = int(max_dur * rate / chunk)
        has_speech = False

        try:
            for i in range(total_frames_needed):
                if self._stop_flag:
                    break
                data = stream.read(chunk, exception_on_overflow=False)
                frames.append(data)
                # 实时音量 (RMS)
                audio = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
                # 归一化到 0~1，经验值
                vol = min(1.0, rms / 3000.0)
                self.signal.audio_volume.emit(vol)

                if rms > silence_threshold:
                    silence_count = 0
                    has_speech = True
                else:
                    if has_speech:
                        silence_count += 1
                        if silence_count >= silence_frames_needed:
                            break
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

        if not has_speech:
            return b""

        # 写入 WAV 临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wf = wave.open(tmp.name, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(fmt_width)
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
        wf.close()
        with open(tmp.name, "rb") as f:
            data = f.read()
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return data

    def _run_asr(self, audio_data: bytes) -> str:
        if not self._client:
            return ""
        try:
            res = self._client.asr(
                audio_data, "wav",
                int(self._asr_cfg.get("sample_rate", 16000)),
                {"dev_pid": int(self._asr_cfg.get("dev_pid", 1537))},
            )
            if isinstance(res, dict) and res.get("err_no", 0) == 0:
                result = res.get("result", [])
                return "".join(result) if result else ""
            logger.warning(f"ASR 失败: {res}")
        except Exception as e:
            logger.error(f"ASR 异常: {e}")
        return ""

    # ---------- 智能问答 ----------
    def _run_qa(self, question: str) -> str:
        """对接自定义问答 API，无 API 则使用本地规则回退"""
        api_url = self._qa_cfg.get("api_url", "")
        api_key = self._qa_cfg.get("api_key", "")
        fallback = self._qa_cfg.get("fallback", "您好，我暂时无法回答这个问题。")

        if api_url:
            try:
                import requests
                resp = requests.post(
                    api_url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"question": question},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("answer") or data.get("text") or fallback
            except Exception as e:
                logger.warning(f"问答 API 调用失败: {e}")

        # 本地规则回退
        return self._local_qa_fallback(question, fallback)

    def _local_qa_fallback(self, question: str, fallback: str) -> str:
        q = question.strip()
        if "你好" in q or "您好" in q or "hi" in q.lower() or "hello" in q.lower():
            return "您好，我是基于 ESP32 云台追踪的数字人系统，很高兴为您服务。"
        if "你是谁" in q or "介绍" in q:
            return "我是一套实时交互数字人系统，可以识别人脸姿态，控制云台追踪，并同步驱动虚拟数字人。"
        if "功能" in q or "能做什么" in q or "什么" in q:
            return "我可以进行人脸姿态识别、自动云台追踪、数字人动作同步和语音对话。"
        if "关闭" in q or "停止" in q:
            return "好的，已为您停止当前操作。"
        return fallback

    # ---------- TTS + 播放 ----------
    def _run_tts_and_play(self, text: str) -> None:
        if not text or not self._client:
            return
        try:
            tts_result = self._client.synthesis(
                text, "zh", 1,
                {
                    "per": int(self._tts_cfg.get("per", 4)),
                    "spd": int(self._tts_cfg.get("spd", 5)),
                    "pit": int(self._tts_cfg.get("pit", 5)),
                    "vol": int(self._tts_cfg.get("vol", 9)),
                },
            )
            if isinstance(tts_result, dict):
                logger.error(f"TTS 失败: {tts_result}")
                self.signal.tts_play_error.emit(str(tts_result))
                return

            # 播放 mp3 字节流
            self.signal.tts_play_started.emit()
            self._play_audio(tts_result)
            self.signal.tts_play_finished.emit()
        except Exception as e:
            logger.exception(f"TTS 异常: {e}")
            self.signal.tts_play_error.emit(str(e))

    def _play_audio(self, audio_bytes: bytes) -> None:
        """播放 mp3 字节流并实时反馈音量"""
        if not _HAS_PYAUDIO:
            return
        try:
            from io import BytesIO
            # 解码 mp3 -> pcm
            try:
                from pydub import AudioSegment
                seg = AudioSegment.from_mp3(BytesIO(audio_bytes))
                pcm = io.BytesIO()
                seg.export(pcm, format="wav")
                pcm.seek(0)
                wav_data = pcm.read()
            except Exception:
                # 回退：直接当作 wav 处理
                wav_data = audio_bytes

            # 解析 wav
            wf = wave.open(BytesIO(wav_data), "rb")
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            n_frames = wf.getnframes()

            stream = self._pa.open(
                format=self._pa.getFormatFromWidth(sample_width),
                channels=channels,
                rate=sample_rate,
                output=True,
            )
            chunk = 1024
            self._playing = True
            for i in range(0, n_frames, chunk):
                if self._stop_flag:
                    break
                data = wf.readframes(chunk)
                if not data:
                    break
                stream.write(data)
                # 计算实时音量
                arr = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(np.square(arr.astype(np.float32)))) if arr.size else 0.0)
                vol = min(1.0, rms / 3000.0)
                self.signal.audio_volume.emit(vol)
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            self._playing = False
        except Exception as e:
            logger.exception(f"音频播放异常: {e}")
            self._playing = False

    def stop_speaking(self) -> None:
        self._stop_flag = True
        self._playing = False
        self._recording = False

    def close(self) -> None:
        self._stop_flag = True
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
