"""
人脸姿态识别模块
基于 MediaPipe Face Mesh 468 关键点 + OpenCV solvePnP
输出:
    - 人脸框 (x, y, w, h)
    - 头部三维姿态: yaw(左右转头)、pitch(俯仰)、roll(侧倾)  单位:度
    - 距相机距离估算（米）
    - 画面中心偏移比例 offset_x, offset_y ∈ [-1, 1]
多人场景: 锁定面积最大 / 距离最近的人脸
"""
import math
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np
import mediapipe as mp
from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import ConfigLoader
from core.logger import logger


@dataclass
class FacePoseResult:
    detected: bool = False
    bbox: tuple = (0, 0, 0, 0)            # x, y, w, h
    yaw: float = 0.0                       # 左右转头 (度)
    pitch: float = 0.0                     # 俯仰 (度)
    roll: float = 0.0                      # 侧倾 (度)
    offset_x: float = 0.0                  # 画面中心水平偏移 [-1, 1]
    offset_y: float = 0.0                  # 画面中心垂直偏移 [-1, 1]
    distance: float = 1.0                  # 距相机距离 (米)
    confidence: float = 0.0


class FacePoseSignalHub(QObject):
    # 姿态结果
    pose_result_ready = pyqtSignal(object)  # FacePoseResult
    # 调试画面（带人脸框、姿态轴）
    debug_frame_ready = pyqtSignal(object)  # ndarray
    # 状态
    status_changed = pyqtSignal(str)


class FacePoseEstimator:
    """人脸姿态识别器"""

    # 3D 人脸模型点（通用参考），单位毫米
    # 6 个关键点对应 2D-3D PnP 求解
    _MODEL_POINTS = np.array([
        (0.0, 0.0, 0.0),             # 鼻尖 (1)
        (0.0, -63.6, -12.5),         # 下颌 (152)
        (-43.3, 32.7, -26.0),        # 右眼外 (334)
        (43.3, 32.7, -26.0),         # 左眼外 (33)
        (-28.9, -28.9, -24.1),       # 右嘴角 (61)
        (28.9, -28.9, -24.1),        # 左嘴角 (291)
    ], dtype=np.float64)

    # MediaPipe 关键点索引
    _LMK_INDICES = [1, 152, 334, 33, 61, 291]

    def __init__(self):
        self._cfg = ConfigLoader.get("face_pose", {})
        self._min_det = float(self._cfg.get("min_detection_confidence", 0.6))
        self._min_trk = float(self._cfg.get("min_tracking_confidence", 0.5))
        self._focal = float(self._cfg.get("focal_length", 600))
        self._max_face_distance = float(self._cfg.get("max_face_distance", 1.2))

        self.signal = FacePoseSignalHub()

        # MediaPipe FaceMesh
        self._mp_face = mp.solutions.face_mesh
        self._mp_drawing = mp.solutions.drawing_utils
        self._face_mesh = self._mp_face.FaceMesh(
            static_image_mode=False,
            max_num_faces=3,
            refine_landmarks=True,
            min_detection_confidence=self._min_det,
            min_tracking_confidence=self._min_trk,
        )

        # 相机内参（用估算焦距）
        self._camera_matrix = None
        self._dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    def process_frame(self, frame: np.ndarray) -> FacePoseResult:
        """处理一帧 BGR 图像"""
        h, w = frame.shape[:2]
        # 初始化内参
        if self._camera_matrix is None:
            self._camera_matrix = np.array([
                [self._focal, 0, w / 2.0],
                [0, self._focal, h / 2.0],
                [0, 0, 1.0],
            ], dtype=np.float64)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)
        result = FacePoseResult()

        if not results.multi_face_landmarks:
            self.signal.status_changed.emit("no_face")
            self.signal.pose_result_ready.emit(result)
            return result

        # 选最大脸 / 最近脸
        lmk_list = self._select_primary_face(results.multi_face_landmarks, w, h)
        if lmk_list is None:
            self.signal.status_changed.emit("no_face")
            self.signal.pose_result_ready.emit(result)
            return result

        # 计算 2D 关键点
        image_points = np.array([
            (lmk_list[i].x * w, lmk_list[i].y * h) for i in self._LMK_INDICES
        ], dtype=np.float64)

        # 人脸框
        xs = [p.x for p in lmk_list]
        ys = [p.y for p in lmk_list]
        x_min, x_max = min(xs) * w, max(xs) * w
        y_min, y_max = min(ys) * h, max(ys) * h
        bbox = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

        # solvePnP 求解姿态
        success, rvec, tvec, _ = cv2.solvePnPRansac(
            self._MODEL_POINTS, image_points, self._camera_matrix, self._dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )

        if not success:
            self.signal.status_changed.emit("pnp_fail")
            self.signal.pose_result_ready.emit(result)
            return result

        # 旋转向量 -> 旋转矩阵 -> 欧拉角
        rmat, _ = cv2.Rodrigues(rvec)
        # 透视投影: 旋转矩阵分解为欧拉角
        # 参考 OpenCV solvePnP 的标准做法
        angles = self._rotation_matrix_to_euler(rmat)
        yaw, pitch, roll = angles

        # 距离估算 (Z 轴平移)
        distance = abs(tvec[2, 0]) / 1000.0  # 毫米 -> 米

        # 中心偏移比例
        face_center_x = (x_min + x_max) / 2.0
        face_center_y = (y_min + y_max) / 2.0
        offset_x = (face_center_x - w / 2.0) / (w / 2.0)   # -1 ~ 1
        offset_y = (face_center_y - h / 2.0) / (h / 2.0)

        result.detected = True
        result.bbox = bbox
        result.yaw = float(np.clip(yaw, -90.0, 90.0))
        result.pitch = float(np.clip(pitch, -90.0, 90.0))
        result.roll = float(np.clip(roll, -90.0, 90.0))
        result.offset_x = float(np.clip(offset_x, -1.0, 1.0))
        result.offset_y = float(np.clip(offset_y, -1.0, 1.0))
        result.distance = float(max(0.1, distance))
        result.confidence = 1.0  # 简化

        self.signal.status_changed.emit("tracking")
        self.signal.pose_result_ready.emit(result)
        return result

    def _select_primary_face(self, faces, w: int, h: int):
        """多人场景: 选面积最大 / 距离最近的人脸"""
        best = None
        best_score = -1.0
        for face in faces:
            xs = [p.x for p in face]
            ys = [p.y for p in face]
            area = (max(xs) - min(xs)) * (max(ys) - min(ys))
            if area > best_score:
                best_score = area
                best = face
        return best

    @staticmethod
    def _rotation_matrix_to_euler(rmat: np.ndarray):
        """旋转矩阵 -> 欧拉角 (yaw, pitch, roll)，单位度"""
        # 使用 OpenCV decomposeProjectionMatrix 更稳定
        _, _, _, _, _, _, eulerAngles = cv2.decomposeProjectionMatrix(
            np.hstack([rmat, np.zeros((3, 1), dtype=np.float64)])
        )
        yaw = eulerAngles[1, 0]
        pitch = eulerAngles[0, 0]
        roll = eulerAngles[2, 0]
        # 角度规整化到 -180~180
        yaw = (yaw + 180.0) % 360.0 - 180.0
        pitch = (pitch + 180.0) % 360.0 - 180.0
        roll = (roll + 180.0) % 360.0 - 180.0
        return yaw, pitch, roll

    def draw_debug(self, frame: np.ndarray, result: FacePoseResult) -> np.ndarray:
        """绘制人脸框 + 姿态轴"""
        if not result.detected:
            return frame
        x, y, w, h = result.bbox
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # 姿态文本
        text = f"Y:{result.yaw:+.1f} P:{result.pitch:+.1f} R:{result.roll:+.1f} d:{result.distance:.2f}m"
        cv2.putText(frame, text, (x, max(0, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

        # 画面中心十字
        h_img, w_img = frame.shape[:2]
        cv2.line(frame, (w_img // 2 - 10, h_img // 2), (w_img // 2 + 10, h_img // 2), (255, 255, 0), 1)
        cv2.line(frame, (w_img // 2, h_img // 2 - 10), (w_img // 2, h_img // 2 + 10), (255, 255, 0), 1)
        return frame

    def release(self) -> None:
        try:
            self._face_mesh.close()
        except Exception:
            pass
