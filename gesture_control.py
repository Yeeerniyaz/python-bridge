#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL - TITAN EDITION (v8.0)
=============================================
Target:     Raspberry Pi 4/5 / Linux / Production
Author:     Vector AI (Gemini) for Yerniyaz
Mechanic:   "The Gunner" (Index to Aim, Thumb+Middle to Click)
Status:     Production Ready
"""

import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys
import math
from dataclasses import dataclass
from typing import Tuple, Optional, Any

# ==============================================================================
# 1. SYSTEM CONFIGURATION (НАСТРОЙКИ ЯДРА)
# ==============================================================================

@dataclass
class SystemConfig:
    """Immutable system configuration."""
    
    # --- Camera & Hardware ---
    CAMERA_ID: int = 0
    WIDTH: int = 640        # Input Resolution
    HEIGHT: int = 480
    FPS: int = 30
    
    # --- Interaction Zone (Virtual Pad) ---
    # Отступы, чтобы курсор долетал до углов экрана без напряжения руки
    MARGIN_X: int = 80      
    MARGIN_Y: int = 70
    
    # --- Physics & Stabilization ---
    # Мертвая зона: движение меньше 3px игнорируется (бетонная устойчивость)
    DEADZONE: float = 3.0   
    # Сглаживание: 0.1 (плавно) -> 0.5 (резко)
    SMOOTH_ALPHA: float = 0.15 
    
    # --- GESTURE THRESHOLDS (Самое важное!) ---
    # TRIGGER = Расстояние между БОЛЬШИМ (4) и СРЕДНИМ (12) пальцами
    # Я увеличил пороги, чтобы клик срабатывал легче!
    TRIGGER_START: float = 0.055  # Клик, когда пальцы почти коснулись
    TRIGGER_STOP: float = 0.080   # Отпускание, когда пальцы разошлись
    
    # --- Timers ---
    NAV_COOLDOWN: float = 0.5     # Задержка между свайпами
    ESC_HOLD_TIME: float = 2.5    # Время удержания кулака

config = SystemConfig()

# ==============================================================================
# 2. LOGGING & MATH UTILS (ИНСТРУМЕНТАРИЙ)
# ==============================================================================

# Professional Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s | %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR")

# PyAutoGUI Safety Off (Kiosk Mode)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.001

class MathUtils:
    """Geometric calculations library."""
    
    @staticmethod
    def calc_distance(p1, p2) -> float:
        """Euclidean distance between two landmarks."""
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    @staticmethod
    def map_coords(val_x: float, val_y: float, scr_w: int, scr_h: int) -> Tuple[int, int]:
        """
        Maps normalized camera coordinates (0.0-1.0) to screen pixels.
        Applies margins to allow reaching screen corners easily.
        """
        # 1. Remap (Interpolate)
        x = np.interp(val_x * config.WIDTH, 
                      [config.MARGIN_X, config.WIDTH - config.MARGIN_X], 
                      [0, scr_w])
        y = np.interp(val_y * config.HEIGHT, 
                      [config.MARGIN_Y, config.HEIGHT - config.MARGIN_Y], 
                      [0, scr_h])
        
        # 2. Clamp (Safety bounds)
        return int(np.clip(x, 0, scr_w)), int(np.clip(y, 0, scr_h))

class FPSMeter:
    """Performance monitoring tool."""
    def __init__(self):
        self.prev = 0
        self.fps = 0
    
    def tick(self):
        curr = time.time()
        delta = curr - self.prev
        if delta > 1.0: # Update every second
            self.fps = int(1 / (curr - self.prev + 0.0001)) # avoid div/0
            self.prev = curr
        return self.fps

# ==============================================================================
# 3. THREADED CAMERA DRIVER (ДРАЙВЕР КАМЕРЫ)
# ==============================================================================

class CameraThread:
    """
    Runs video capture in a separate CPU thread.
    This prevents the AI processing from slowing down the camera feed.
    """
    def __init__(self, src: int = 0):
        self.src = src
        self.cap = cv2.VideoCapture(self.src)
        self._configure()
        
        self.frame = None
        self.grabbed = False
        self.stopped = False
        self.lock = threading.Lock()
        
        # Start background thread
        threading.Thread(target=self._update, daemon=True).start()

    def _configure(self):
        """Hardware configuration."""
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, config.FPS)

    def _update(self):
        """Thread loop."""
        while not self.stopped:
            if not self.cap.isOpened():
                time.sleep(1) # Wait before retry
                self.cap.open(self.src)
                continue
                
            grabbed, frame = self.cap.read()
            with self.lock:
                if grabbed:
                    self.grabbed = True
                    self.frame = frame
                else:
                    self.grabbed = False
            
            # Yield execution to allow other threads to run
            time.sleep(0.002)

    def read(self):
        """Thread-safe read."""
        with self.lock:
            return self.frame.copy() if self.grabbed and self.frame is not None else None

    def stop(self):
        self.stopped = True
        self.cap.release()
        logger.info("Camera Service Stopped.")

# ==============================================================================
# 4. VECTOR ENGINE (МОЗГ СИСТЕМЫ)
# ==============================================================================

class VectorEngine:
    """
    The central logic processor.
    Implements the 'Separate Trigger' mechanic.
    """
    def __init__(self):
        # MediaPipe Initialization (Lite model for RPi optimization)
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, 
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Cursor Physics State
        self.prev_x, self.prev_y = 0.0, 0.0
        self.is_dragging = False
        
        # Gesture Logic State
        self.nav_anchor = None
        self.nav_timer = 0
        self.fist_timer = 0
        
        logger.info(f"Engine Online. Screen: {self.screen_w}x{self.screen_h}")

    def _move_cursor(self, raw_x: float, raw_y: float):
        """
        Calculates screen position with Smoothing and Deadzone.
        """
        # 1. Convert Camera -> Screen
        target_x, target_y = MathUtils.map_coords(
            raw_x, raw_y, self.screen_w, self.screen_h
        )
        
        # 2. Exponential Moving Average (Smoothing)
        smooth_x = self.prev_x + (target_x - self.prev_x) * config.SMOOTH_ALPHA
        smooth_y = self.prev_y + (target_y - self.prev_y) * config.SMOOTH_ALPHA
        
        # 3. Deadzone Filter (Anti-Jitter)
        # Если рука дрожит меньше чем на DEADZONE пикселей — курсор стоит.
        dx = abs(smooth_x - self.prev_x)
        dy = abs(smooth_y - self.prev_y)
        
        if dx > config.DEADZONE or dy > config.DEADZONE:
            pyautogui.moveTo(smooth_x, smooth_y)
            self.prev_x, self.prev_y = smooth_x, smooth_y

    def process(self, frame: np.ndarray):
        """Main recognition loop."""
        
        # Pre-process image
        if frame.shape[1] != config.WIDTH:
            frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))
        
        frame = cv2.flip(frame, 1) # Mirror effect
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Inference
        results = self.hands.process(rgb)

        # --- No Hands Safety ---
        if not results.multi_hand_landmarks:
            if self.is_dragging:
                pyautogui.mouseUp()
                self.is_dragging = False
                logger.warning("Tracking Lost -> Drag Released")
            self.fist_timer = 0
            return

        # --- Hand Detected ---
        for hand_lms in results.multi_hand_landmarks:
            lms = hand_lms.landmark
            now = time.time()

            # Finger States (1=Up, 0=Down)
            # 8=Index, 12=Middle, 16=Ring, 20=Pinky
            # Note: We compare Y coordinates (lower Y is higher on screen)
            fingers = [1 if lms[tip].y < lms[tip-2].y else 0 for tip in [8, 12, 16, 20]]
            up_count = sum(fingers)
            
            # --- CRITICAL VARIABLES ---
            # 1. Aiming Point: Index Finger Tip (8)
            aim_point = lms[8]
            
            # 2. Trigger Distance: Thumb (4) <-> Middle Finger (12)
            trigger_dist = MathUtils.calc_distance(lms[4], lms[12])

            # ==================================================================
            # MODE 1: AIM & SHOOT (Index Up)
            # ==================================================================
            # Указательный палец управляет курсором.
            # Большой + Средний управляют кликом.
            
            if fingers[0]: # Если Указательный поднят
                
                # A. Двигаем курсор (Всегда!)
                self._move_cursor(aim_point.x, aim_point.y)

                # B. Проверяем Триггер (Клик)
                if trigger_dist < config.TRIGGER_START:
                    if not self.is_dragging:
                        pyautogui.mouseDown()
                        self.is_dragging = True
                        logger.info("💥 CLICK (Trigger Active)")
                
                elif trigger_dist > config.TRIGGER_STOP:
                    if self.is_dragging:
                        pyautogui.mouseUp()
                        self.is_dragging = False
                        logger.info("💨 RELEASE (Trigger Reset)")
                
                return # Выходим, чтобы другие жесты не мешали

            # ==================================================================
            # MODE 2: NAVIGATION (Victory Sign)
            # ==================================================================
            # Указательный и Средний подняты. 
            # ВАЖНО: Триггер должен быть разомкнут (дистанция > 0.1), иначе это клик
            
            if fingers[0] and fingers[1] and trigger_dist > 0.1:
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                curr = (lms[9].x, lms[9].y) # Центр ладони
                if self.nav_anchor is None: self.nav_anchor = curr
                else:
                    dx = curr[0] - self.nav_anchor[0]
                    dy = curr[1] - self.nav_anchor[1]
                    
                    if now - self.nav_timer > config.NAV_COOLDOWN:
                        if abs(dx) > 0.05: # Порог свайпа по X
                            key = 'right' if dx > 0 else 'left'
                            pyautogui.press(key)
                            logger.info(f"Nav: {key.upper()}")
                            self.nav_timer = now; self.nav_anchor = curr
                        elif abs(dy) > 0.05: # Порог свайпа по Y
                            key = 'down' if dy > 0 else 'up'
                            pyautogui.press(key)
                            logger.info(f"Nav: {key.upper()}")
                            self.nav_timer = now; self.nav_anchor = curr
                return
            else:
                self.nav_anchor = None

            # ==================================================================
            # MODE 3: SYSTEM EXIT (Fist / 0 Fingers)
            # ==================================================================
            if up_count == 0:
                if self.fist_timer == 0: self.fist_timer = now
                elif now - self.fist_timer > config.ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.warning("🔐 SYSTEM: ESCAPE EXECUTED")
                    self.fist_timer = 0
            else:
                self.fist_timer = 0

            # ==================================================================
            # MODE 4: IDLE (Palm Open / 3+ Fingers)
            # ==================================================================
            if up_count >= 3:
                # Просто двигаем курсор, без кликов
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                self._move_cursor(lms[9].x, lms[9].y)

# ==============================================================================
# 5. RUNNER (ЗАПУСК)
# ==============================================================================

def main():
    print("------------------------------------------------")
    print("   VECTOR GESTURE CONTROL | TITAN EDITION v8.0")
    print("------------------------------------------------")
    print(" GUIDE:")
    print(" [1] ☝️ CURSOR:  Index Finger (Aim)")
    print(" [2] 👌 CLICK:   Thumb + Middle Finger (Trigger)")
    print(" [3] ✌️ SCROLL:  Victory Sign + Move Hand")
    print(" [4] 👊 EXIT:    Hold Fist (2.5s)")
    print("------------------------------------------------")

    # Graceful Shutdown Handler
    def shutdown_handler(sig, frame):
        logger.info("Shutdown sequence initiated...")
        cam.stop()
        if engine.is_dragging: pyautogui.mouseUp()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Init Components
    fps_meter = FPSMeter()
    cam = CameraThread(src=config.CAMERA_ID)
    engine = VectorEngine()
    
    # Warmup
    logger.info("Warming up camera...")
    time.sleep(1.0)
    logger.info("System ACTIVE.")

    try:
        while True:
            # 1. Get Frame (Threaded)
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
            
            # 2. Process
            engine.process(frame)
            
            # 3. Monitor
            # fps = fps_meter.tick() 
            # if fps > 0 and fps % 30 == 0: print(f"FPS: {fps}")

    except Exception as e:
        logger.critical(f"Runtime Crash: {e}", exc_info=True)
    finally:
        cam.stop()

if __name__ == "__main__":
    main()