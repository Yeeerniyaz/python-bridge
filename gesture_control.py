#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL - ENTERPRISE EDITION (v7.0)
==================================================
Target:     Raspberry Pi / Linux / Production
Author:     Vector AI (Gemini) for Yerniyaz
Mechanic:   "Independent Trigger" (Index to Aim, Middle+Thumb to Shoot)
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
from typing import Tuple, Optional, List
from dataclasses import dataclass

# ==============================================================================
# 1. SYSTEM CONFIGURATION (НАСТРОЙКИ)
# ==============================================================================

@dataclass
class SystemConfig:
    """Production configuration parameters."""
    
    # --- Camera ---
    CAMERA_ID: int = 0
    WIDTH: int = 640
    HEIGHT: int = 480
    FPS: int = 30
    
    # --- Interaction Zone (Virtual Pad) ---
    # Отступы от краев кадра (чтобы не тянуться в самые углы)
    MARGIN_X: int = 70
    MARGIN_Y: int = 60
    
    # --- Smoothing & Physics ---
    # Deadzone: Игнорировать микродвижения меньше 3 пикселей (бетонная стабилизация)
    DEADZONE: float = 3.0
    # Alpha: 0.01 (очень плавно) -> 1.0 (мгновенно)
    SMOOTH_ALPHA: float = 0.15 
    
    # --- Gesture Thresholds (Normalized 0.0 - 1.0) ---
    # Trigger: Дистанция между БОЛЬШИМ и СРЕДНИМ пальцами
    TRIGGER_START: float = 0.045  # Нажатие (касание)
    TRIGGER_STOP: float = 0.065   # Отпускание (разрыв)
    
    # --- Timers ---
    NAV_COOLDOWN: float = 0.5
    ESC_HOLD_TIME: float = 2.5

config = SystemConfig()

# ==============================================================================
# 2. LOGGING & MATH UTILS
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR_CORE")

# Disable PyAutoGUI failsafe (we handle boundaries manually)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.001

class MathUtils:
    """Geometric calculations helper."""
    
    @staticmethod
    def calc_distance(p1, p2) -> float:
        """Euclidean distance between two landmarks."""
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    @staticmethod
    def map_coords(val_x: float, val_y: float, scr_w: int, scr_h: int) -> Tuple[int, int]:
        """Maps normalized camera coords to screen pixels with margins."""
        # 1. Remap range (Camera -> Screen with Margins)
        x = np.interp(val_x * config.WIDTH, 
                      [config.MARGIN_X, config.WIDTH - config.MARGIN_X], 
                      [0, scr_w])
        y = np.interp(val_y * config.HEIGHT, 
                      [config.MARGIN_Y, config.HEIGHT - config.MARGIN_Y], 
                      [0, scr_h])
        
        # 2. Clamp (Prevent going out of bounds)
        return int(np.clip(x, 0, scr_w)), int(np.clip(y, 0, scr_h))

# ==============================================================================
# 3. THREADED CAMERA (OPTIMIZED)
# ==============================================================================

class CameraThread:
    """Dedicated thread for non-blocking frame capture."""
    
    def __init__(self, src: int = 0):
        self.src = src
        self.cap = cv2.VideoCapture(self.src)
        self._set_props()
        
        self.frame = None
        self.grabbed = False
        self.stopped = False
        self.lock = threading.Lock()
        
        threading.Thread(target=self._update, daemon=True).start()

    def _set_props(self):
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, config.FPS)

    def _update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                time.sleep(1)
                self.cap.open(self.src)
                continue
                
            grabbed, frame = self.cap.read()
            with self.lock:
                if grabbed:
                    self.grabbed = True
                    self.frame = frame
                else:
                    self.grabbed = False
            time.sleep(0.005) # Yield to CPU

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed and self.frame is not None else None

    def stop(self):
        self.stopped = True
        self.cap.release()

# ==============================================================================
# 4. GESTURE ENGINE (THE BRAIN)
# ==============================================================================

class VectorEngine:
    def __init__(self):
        # Initialize MediaPipe (Lite model for RPi speed)
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, 
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Cursor State
        self.prev_x, self.prev_y = 0.0, 0.0
        self.is_dragging = False
        
        # Logic State
        self.nav_anchor = None
        self.nav_timer = 0
        self.fist_timer = 0
        
        logger.info(f"Engine Started. Resolution: {self.screen_w}x{self.screen_h}")

    def _update_cursor(self, raw_x: float, raw_y: float):
        """Calculates cursor position with Smoothing & Deadzone."""
        # 1. Map Coordinates
        tx, ty = MathUtils.map_coords(raw_x, raw_y, self.screen_w, self.screen_h)
        
        # 2. Smooth (Exponential Moving Average)
        sx = self.prev_x + (tx - self.prev_x) * config.SMOOTH_ALPHA
        sy = self.prev_y + (ty - self.prev_y) * config.SMOOTH_ALPHA
        
        # 3. Deadzone (Anti-Jitter)
        # Если движение меньше N пикселей, не двигаем курсор вообще
        if abs(sx - self.prev_x) > config.DEADZONE or abs(sy - self.prev_y) > config.DEADZONE:
            pyautogui.moveTo(sx, sy)
            self.prev_x, self.prev_y = sx, sy

    def process_frame(self, frame: np.ndarray):
        # Resize & Color Convert
        if frame.shape[1] != config.WIDTH:
            frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))
        
        frame = cv2.flip(frame, 1) # Mirror effect
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        # --- No Hands Safety ---
        if not results.multi_hand_landmarks:
            if self.is_dragging: 
                pyautogui.mouseUp()
                self.is_dragging = False
            return

        for hand_lms in results.multi_hand_landmarks:
            lms = hand_lms.landmark
            now = time.time()

            # --- Finger States (0=Folded, 1=Straight) ---
            # Indices: 8(Idx), 12(Mid), 16(Rng), 20(Pnk)
            fingers = [1 if lms[tip].y < lms[tip-2].y else 0 for tip in [8, 12, 16, 20]]
            up_count = sum(fingers)
            
            # --- CRITICAL MEASUREMENTS ---
            # 1. Cursor Source: Index Finger Tip (8)
            cursor_source = lms[8]
            
            # 2. Trigger Source: Thumb (4) <-> Middle (12)
            trigger_dist = MathUtils.calc_distance(lms[4], lms[12])

            # ==================================================================
            # MODE 1: CURSOR & CLICK (Index Up)
            # ==================================================================
            # Логика: Если указательный палец поднят, мы управляем курсором.
            # Клик происходит НЕЗАВИСИМО от указательного пальца (Большой + Средний).
            
            if fingers[0]: # Index is UP
                # A. Move Cursor (Always active if index is up)
                self._update_cursor(cursor_source.x, cursor_source.y)

                # B. Handle Trigger (Thumb + Middle)
                if trigger_dist < config.TRIGGER_START:
                    if not self.is_dragging:
                        pyautogui.mouseDown()
                        self.is_dragging = True
                        logger.info("💥 CLICK (Triggered)")
                
                elif trigger_dist > config.TRIGGER_STOP:
                    if self.is_dragging:
                        pyautogui.mouseUp()
                        self.is_dragging = False
                        logger.info("💨 RELEASE")
                
                return

            # ==================================================================
            # MODE 2: NAVIGATION (Victory Sign)
            # ==================================================================
            # Только если средний палец прямой (fingers[1]==1)
            # И дистанция триггера большая (чтобы не путать с кликом)
            
            if fingers[0] and fingers[1] and trigger_dist > 0.1:
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                curr = (lms[9].x, lms[9].y)
                if self.nav_anchor is None: self.nav_anchor = curr
                else:
                    dx = curr[0] - self.nav_anchor[0]
                    dy = curr[1] - self.nav_anchor[1]
                    
                    if now - self.nav_timer > config.NAV_COOLDOWN:
                        if abs(dx) > 0.05:
                            key = 'right' if dx > 0 else 'left'
                            pyautogui.press(key)
                            self.nav_timer = now; self.nav_anchor = curr
                        elif abs(dy) > 0.05:
                            key = 'down' if dy > 0 else 'up'
                            pyautogui.press(key)
                            self.nav_timer = now; self.nav_anchor = curr
                return
            else:
                self.nav_anchor = None

            # ==================================================================
            # MODE 3: SYSTEM EXIT (Fist)
            # ==================================================================
            if up_count == 0:
                if self.fist_timer == 0: self.fist_timer = now
                elif now - self.fist_timer > config.ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.warning("🔐 ESC EXECUTE")
                    self.fist_timer = 0
            else:
                self.fist_timer = 0

# ==============================================================================
# 5. RUNTIME
# ==============================================================================

def main():
    print("------------------------------------------------")
    print("   VECTOR GESTURE CONTROL | SEPARATE TRIGGER")
    print("------------------------------------------------")
    print(" GUIDE:")
    print(" [1] ☝️ MOVE:   Index Finger Up")
    print(" [2] 👌 CLICK:  Touch Thumb to Middle Finger")
    print(" [3] ✌️ SCROLL: Victory Sign + Move Hand")
    print(" [4] 👊 EXIT:   Hold Fist (2.5s)")
    print("------------------------------------------------")

    def shutdown(sig, frame):
        logger.info("Exiting...")
        cam.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    
    cam = CameraThread(src=config.CAMERA_ID)
    engine = VectorEngine()
    
    time.sleep(1.0) # Warmup

    try:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
            engine.process_frame(frame)
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cam.stop()

if __name__ == "__main__":
    main()