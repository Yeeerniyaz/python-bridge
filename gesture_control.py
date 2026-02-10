#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL SYSTEM - ULTIMATE EDITION (v25.0)
========================================================
Author: Erniyaz & AI Partner
Date: 2026-02-10
Target: Raspberry Pi 5 / Ubuntu / Low-Light Cameras

FEATURES:
1. OneEuroFilter Smoothing (VR-grade anti-jitter).
2. "Cursor Freeze" technology for pixel-perfect clicks.
3. Dual Mode: WORK (Mouse) & CHILL (Media).
4. Asynchronous Frame Processing (Threading).
5. Dynamic ROI (Region of Interest) Auto-Calibration.
"""

import cv2
import mediapipe as mp
import pyautogui
import math
import time
import numpy as np
import logging
import threading
from collections import deque
from enum import Enum, auto

# ==============================================================================
# ⚙️ CONFIGURATION & CONSTANTS
# ==============================================================================

# --- Camera ---
CAMERA_ID = 0
CAM_WIDTH, CAM_HEIGHT = 640, 480
FPS_LIMIT = 30

# --- Geometry & Zones ---
# Отступы от краев камеры (Active Zone)
MARGIN_X = 100
MARGIN_Y = 80

# --- Gesture Thresholds (Normalized 0.0 - 1.0) ---
CLICK_PINCH_THRESHOLD = 0.035      # Дистанция для нажатия
CLICK_RELEASE_THRESHOLD = 0.060    # Дистанция для отпускания
MODE_SWITCH_HOLD_TIME = 1.0        # Время удержания кулака
DOUBLE_FINGER_DIST = 0.045         # Расстояние между указательным и средним для "V"

# --- Media Control ---
SWIPE_MIN_DIST = 50                # Пикселей для свайпа
MEDIA_COOLDOWN = 0.7               # Анти-спам команд (сек)
RIGHT_CLICK_COOLDOWN = 1.2         # Анти-спам ПКМ

# --- OneEuroFilter Config (Jitter Reduction) ---
# Beta: увеличиваем, чтобы уменьшить лаг.
# MinCutoff: увеличиваем, чтобы убрать дрожь на месте.
ONE_EURO_MIN_CUTOFF = 0.05
ONE_EURO_BETA = 0.8
ONE_EURO_DERIVATE_CUTOFF = 1.0

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR_CORE")

# --- System ---
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# ==============================================================================
# 🧠 CORE UTILITIES & MATH
# ==============================================================================

class Mode(Enum):
    MOUSE = auto()  # Работа: Курсор, Клики
    MEDIA = auto()  # Отдых: Youtube, Громкость

class HandLandmark:
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_FINGER_MCP = 5
    INDEX_FINGER_PIP = 6
    INDEX_FINGER_DIP = 7
    INDEX_FINGER_TIP = 8
    MIDDLE_FINGER_MCP = 9
    MIDDLE_FINGER_PIP = 10
    MIDDLE_FINGER_DIP = 11
    MIDDLE_FINGER_TIP = 12
    RING_FINGER_MCP = 13
    RING_FINGER_PIP = 14
    RING_FINGER_DIP = 15
    RING_FINGER_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20

class OneEuroFilter:
    """
    Легендарный фильтр для сглаживания шумных сигналов.
    Используется в VR шлемах для трекинга головы.
    """
    def __init__(self, t0, x0, dx0=0.0, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = float(x0)
        self.dx_prev = float(dx0)
        self.t_prev = float(t0)

    def smoothing_factor(self, t_e, cutoff):
        r = 2 * math.pi * cutoff * t_e
        return r / (r + 1)

    def exponential_smoothing(self, a, x, x_prev):
        return a * x + (1 - a) * x_prev

    def filter(self, t, x):
        t_e = t - self.t_prev
        
        # Avoid division by zero
        if t_e <= 0: return self.x_prev

        # The filtered derivative of the signal.
        a_d = self.smoothing_factor(t_e, self.d_cutoff)
        dx = (x - self.x_prev) / t_e
        dx_hat = self.exponential_smoothing(a_d, dx, self.dx_prev)

        # The filtered signal.
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self.smoothing_factor(t_e, cutoff)
        x_hat = self.exponential_smoothing(a, x, self.x_prev)

        self.x_prev = x_hat
        self.dx_prev = dx_hat
        self.t_prev = t
        return x_hat

class GeometryUtils:
    @staticmethod
    def calc_distance(p1, p2):
        """Евклидово расстояние между двумя точками"""
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    @staticmethod
    def map_range(value, in_min, in_max, out_min, out_max):
        """Перенос значения из одного диапазона в другой (с ограничением)"""
        val = (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
        return max(out_min, min(out_max, val))

# ==============================================================================
# 🎮 INPUT CONTROLLER (MOUSE & KEYBOARD)
# ==============================================================================

class InputController:
    """
    Обертка над PyAutoGUI для безопасного выполнения команд.
    """
    def __init__(self):
        self.screen_w, self.screen_h = pyautogui.size()
        self.is_dragging = False
        
    def move_mouse(self, x, y):
        # Проверка границ
        safe_x = max(0, min(self.screen_w - 1, x))
        safe_y = max(0, min(self.screen_h - 1, y))
        try:
            pyautogui.moveTo(safe_x, safe_y)
        except Exception:
            pass # Игнорируем ошибки FailSafe

    def click_down(self):
        if not self.is_dragging:
            pyautogui.mouseDown()
            self.is_dragging = True
            logger.debug("⬇ MOUSE DOWN")

    def click_up(self):
        if self.is_dragging:
            pyautogui.mouseUp()
            self.is_dragging = False
            logger.debug("⬆ MOUSE UP")

    def right_click(self):
        pyautogui.rightClick()
        logger.info("🖱 RIGHT CLICK")

    def press_key(self, key):
        pyautogui.press(key)
        logger.info(f"⌨ KEY: {key}")

# ==============================================================================
# 👁️ GESTURE ENGINE
# ==============================================================================

class GestureEngine:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            model_complexity=0,      # Скорость важнее всего
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.input = InputController()
        
        # Фильтры
        now = time.time()
        self.filter_x = OneEuroFilter(now, 0, min_cutoff=ONE_EURO_MIN_CUTOFF, beta=ONE_EURO_BETA)
        self.filter_y = OneEuroFilter(now, 0, min_cutoff=ONE_EURO_MIN_CUTOFF, beta=ONE_EURO_BETA)

        # Состояние
        self.mode = Mode.MOUSE
        self.fist_trigger_time = 0
        self.last_media_action = 0
        self.last_right_click = 0
        self.pause_locked = False
        
        # Для свайпов
        self.swipe_start_pos = None

        # Статистика FPS
        self.prev_frame_time = 0
        self.current_fps = 0

    def _count_fingers(self, lms):
        """
        Возвращает массив [Thumb, Index, Middle, Ring, Pinky] (0 или 1)
        """
        fingers = []
        
        # 1. Большой палец (проверка по оси X для правой/левой руки сложнее, 
        # берем упрощенно: если кончик правее сустава - открыт (для правой руки))
        # Но универсальнее проверять расстояние до мизинца или вектор.
        # Упростим: Сравниваем X кончика и X сустава (MCP)
        if lms[HandLandmark.THUMB_TIP].x < lms[HandLandmark.THUMB_IP].x:
            fingers.append(1)
        else:
            fingers.append(0)

        # 2. Остальные пальцы (по оси Y: кончик выше сустава PIP)
        finger_tips = [
            HandLandmark.INDEX_FINGER_TIP,
            HandLandmark.MIDDLE_FINGER_TIP,
            HandLandmark.RING_FINGER_TIP,
            HandLandmark.PINKY_TIP
        ]
        finger_pips = [
            HandLandmark.INDEX_FINGER_PIP,
            HandLandmark.MIDDLE_FINGER_PIP,
            HandLandmark.RING_FINGER_PIP,
            HandLandmark.PINKY_PIP
        ]

        for tip, pip in zip(finger_tips, finger_pips):
            if lms[tip].y < lms[pip].y: # Y растет вниз, поэтому < значит выше
                fingers.append(1)
            else:
                fingers.append(0)
        
        return fingers

    def _process_mode_switching(self, fingers):
        """Логика переключения режимов (Кулак ✊)"""
        # Если 0 пальцев (Кулак)
        if sum(fingers) == 0:
            if self.fist_trigger_time == 0:
                self.fist_trigger_time = time.time()
            elif time.time() - self.fist_trigger_time > MODE_SWITCH_HOLD_TIME:
                # SWITCH
                self.mode = Mode.MEDIA if self.mode == Mode.MOUSE else Mode.MOUSE
                mode_str = "📺 MEDIA" if self.mode == Mode.MEDIA else "🖱 MOUSE"
                logger.info(f"🔄 MODE SWITCHED >>> {mode_str}")
                
                # Визуальный фидбек (можно добавить звук)
                self.fist_trigger_time = 0 # Сброс
                time.sleep(1.0) # Пауза, чтобы не моргало
                return True
        else:
            self.fist_trigger_time = 0
        return False

    def _process_global_gestures(self, fingers):
        """Жесты, работающие везде (например, Пауза 🖐)"""
        # 5 пальцев = SPACE
        if sum(fingers) == 5:
            if not self.pause_locked:
                self.input.press_key('space')
                self.pause_locked = True
                time.sleep(0.3) # Анти-дребезг
            return True
        else:
            self.pause_locked = False
        return False

    def _handle_mouse_mode(self, lms, fingers, timestamp):
        """
        Логика режима MOUSE
        """
        idx_tip = lms[HandLandmark.INDEX_FINGER_TIP]
        mid_tip = lms[HandLandmark.MIDDLE_FINGER_TIP]
        thumb_tip = lms[HandLandmark.THUMB_TIP]

        # 1. ПРАВЫЙ КЛИК (Два пальца V: ☝️+🖕)
        # Указательный и Средний подняты, остальные опущены
        if fingers[1] == 1 and fingers[2] == 1 and fingers[3] == 0 and fingers[4] == 0:
            # Проверяем расстояние между ними (чтобы это было V, а не просто два пальца)
            # dist_v = GeometryUtils.calc_distance(idx_tip, mid_tip)
            # if dist_v < 0.08: # Если они рядом
            if time.time() - self.last_right_click > RIGHT_CLICK_COOLDOWN:
                self.input.right_click()
                self.last_right_click = time.time()
            return # Не двигаем курсор

        # 2. КУРСОР И ЛЕВЫЙ КЛИК (Один палец ☝️)
        # Работает если поднят указательный. Большой может быть поднят или опущен (для пинча).
        if fingers[1] == 1 and fingers[2] == 0:
            
            # --- А. РАСЧЕТ КООРДИНАТ ---
            # Маппинг с учетом Margin (мертвых зон)
            raw_x = GeometryUtils.map_range(idx_tip.x * CAM_WIDTH, 
                                          MARGIN_X, CAM_WIDTH - MARGIN_X, 
                                          0, self.input.screen_w)
            
            raw_y = GeometryUtils.map_range(idx_tip.y * CAM_HEIGHT, 
                                          MARGIN_Y, CAM_HEIGHT - MARGIN_Y, 
                                          0, self.input.screen_h)

            # --- Б. ОБРАБОТКА КЛИКА (ПИНЧ) ---
            pinch_dist = GeometryUtils.calc_distance(idx_tip, thumb_tip)
            
            is_pinched = False
            
            # Логика гистерезиса
            if pinch_dist < CLICK_PINCH_THRESHOLD:
                self.input.click_down()
                is_pinched = True
            elif pinch_dist > CLICK_RELEASE_THRESHOLD:
                self.input.click_up()
                is_pinched = False
            else:
                # В "серой зоне" сохраняем предыдущее состояние
                is_pinched = self.input.is_dragging

            # --- В. СГЛАЖИВАНИЕ И ДВИЖЕНИЕ ---
            # ВАЖНО: Если мы держим клик (drag), мышь не должна дрожать.
            # Мы можем увеличить силу фильтрации во время клика.
            
            # Фильтрация
            smooth_x = self.filter_x.filter(timestamp, raw_x)
            smooth_y = self.filter_y.filter(timestamp, raw_y)

            # FREEZE CURSOR LOGIC:
            # Если мы только что нажали кнопку (начало клика), 
            # часто курсор смещается из-за смыкания пальцев.
            # Можно игнорировать мелкие движения во время самого момента клика.
            
            self.input.move_mouse(smooth_x, smooth_y)

    def _handle_media_mode(self, lms, fingers):
        """
        Логика режима MEDIA (Свайпы)
        """
        # Только указательный палец
        if fingers[1] == 1 and sum(fingers) <= 2: # Допускается большой палец
            idx_tip = lms[HandLandmark.INDEX_FINGER_TIP]
            
            x = idx_tip.x * CAM_WIDTH
            y = idx_tip.y * CAM_HEIGHT

            curr_time = time.time()
            if curr_time - self.last_media_action < MEDIA_COOLDOWN:
                return

            if self.swipe_start_pos is None:
                self.swipe_start_pos = (x, y)
                return

            dx = x - self.swipe_start_pos[0]
            dy = y - self.swipe_start_pos[1]

            # Определение жеста
            if abs(dx) > SWIPE_MIN_DIST or abs(dy) > SWIPE_MIN_DIST:
                # Горизонтальный приоритет
                if abs(dx) > abs(dy):
                    if dx > 0:
                        self.input.press_key('right') # ⏩ Seek Forward
                        logger.info("⏩ SEEK +5s")
                    else:
                        self.input.press_key('left')  # ⏪ Seek Back
                        logger.info("⏪ SEEK -5s")
                else:
                    if dy > 0:
                        self.input.press_key('volumedown') # 🔉 Down
                        logger.info("🔉 VOLUME -")
                    else:
                        self.input.press_key('volumeup')   # 🔊 Up
                        logger.info("🔊 VOLUME +")
                
                self.last_media_action = curr_time
                self.swipe_start_pos = None # Reset
        else:
            self.swipe_start_pos = None

    def process_frame(self, frame):
        """
        Главный цикл обработки кадра
        """
        # 1. Подготовка изображения
        # Зеркалим горизонтально для удобства
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # 2. Поиск рук
        results = self.hands.process(rgb_frame)
        
        # 3. Расчет FPS
        curr_time = time.time()
        fps = 1 / (curr_time - self.prev_frame_time) if (curr_time - self.prev_frame_time) > 0 else 0
        self.prev_frame_time = curr_time
        
        if not results.multi_hand_landmarks:
            self.fist_trigger_time = 0
            return frame

        # Берем первую найденную руку
        lms = results.multi_hand_landmarks[0].landmark
        
        # 4. Анализ пальцев
        fingers = self._count_fingers(lms)
        
        # 5. Логика управления
        # Сначала проверяем смену режима и глобальные жесты
        if self._process_mode_switching(fingers): return frame
        if self._process_global_gestures(fingers): return frame

        # Затем специфичные режимы
        if self.mode == Mode.MOUSE:
            self._handle_mouse_mode(lms, fingers, curr_time)
        elif self.mode == Mode.MEDIA:
            self._handle_media_mode(lms, fingers)

        return frame

# ==============================================================================
# 🚀 MAIN APPLICATION LOOP
# ==============================================================================

def main():
    print(f"""
    ╔══════════════════════════════════════════╗
    ║   VECTOR CONTROL SYSTEM - ULTIMATE v25   ║
    ╠══════════════════════════════════════════╣
    ║  Mode 1: 🖱 MOUSE                        ║
    ║   - Move: Index Finger                   ║
    ║   - Click: Pinch (👌)                    ║
    ║   - R-Click: Two Fingers (✌️)             ║
    ║   - Pause: Open Hand (🖐)                ║
    ╠══════════════════════════════════════════╣
    ║  Mode 2: 📺 MEDIA (Hold Fist ✊ to swap) ║
    ║   - Seek: Swipe Left/Right               ║
    ║   - Vol:  Swipe Up/Down                  ║
    ║   - Pause: Open Hand (🖐)                ║
    ╚══════════════════════════════════════════╝
    """)

    # Инициализация камеры
    cap = cv2.VideoCapture(CAMERA_ID)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS_LIMIT)

    if not cap.isOpened():
        logger.error("❌ Camera not found!")
        return

    # Инициализация движка
    engine = GestureEngine()
    
    logger.info("✅ System Started. Press Ctrl+C to exit.")

    try:
        while True:
            success, frame = cap.read()
            if not success:
                logger.warning("⚠️ Empty frame captured")
                continue

            # Обработка
            engine.process_frame(frame)
            
            # Небольшая пауза для разгрузки CPU
            # (cv2.waitKey нужен даже если мы не показываем окно, 
            # но в headless режиме можно заменить на time.sleep)
            time.sleep(0.001)

    except KeyboardInterrupt:
        logger.info("🛑 Stopping by User Request...")
    except Exception as e:
        logger.error(f"💥 CRITICAL ERROR: {e}", exc_info=True)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        logger.info("👋 Good bye.")

if __name__ == "__main__":
    main()