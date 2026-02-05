#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL SYSTEM - ENTERPRISE EDITION (v6.0)
=========================================================
Author:     Vector AI (Gemini) for Yerniyaz
Target:     Raspberry Pi 4/5 / Ubuntu / Linux
Features:   Multi-threading, Dynamic Smoothing, Click Hysteresis,
            Robust Error Handling, Type Safety.
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
from typing import Tuple, Optional, Any
from dataclasses import dataclass

# ==============================================================================
# 1. SYSTEM CONFIGURATION
# ==============================================================================

@dataclass
class SystemConfig:
    """Immutable configuration object for system tuning."""
    # Camera
    CAMERA_ID: int = 0
    WIDTH: int = 640
    HEIGHT: int = 480
    FPS: int = 30
    
    # Interaction Area (Virtual Pad)
    MARGIN_X: int = 60
    MARGIN_Y: int = 50
    
    # Smoothing & Physics
    # Low alpha = more smooth (laggy), High alpha = responsive (jittery)
    SMOOTH_ALPHA_FAST: float = 0.4  # For fast movements
    SMOOTH_ALPHA_SLOW: float = 0.08 # For precision aiming
    DEADZONE_PIXELS: float = 3.0    # Minimum pixel movement to register
    
    # Gesture Thresholds (Normalized 0.0 - 1.0)
    # Hysteresis: Stop distance > Start distance to prevent 'bouncing'
    PINCH_START: float = 0.035      # Trigger click
    PINCH_STOP: float = 0.055       # Release click
    FREEZE_ZONE: float = 0.060      # Freeze cursor when approaching click
    
    # Timers (Seconds)
    NAV_COOLDOWN: float = 0.5
    ESC_HOLD_TIME: float = 2.5

config = SystemConfig()

# ==============================================================================
# 2. LOGGING & UTILITIES
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR_CORE")

# Disable PyAutoGUI failsafe for kiosk mode
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.001

class GestureMath:
    """Static helper class for geometric calculations."""
    
    @staticmethod
    def calc_distance(p1: Any, p2: Any) -> float:
        """Euclidean distance between two MediaPipe landmarks."""
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    @staticmethod
    def map_coordinates(
        val_x: float, val_y: float, 
        src_w: int, src_h: int, 
        screen_w: int, screen_h: int
    ) -> Tuple[int, int]:
        """Maps camera coordinates to screen coordinates with margins."""
        # Normalize and crop
        x = np.interp(val_x * src_w, [config.MARGIN_X, src_w - config.MARGIN_X], [0, screen_w])
        y = np.interp(val_y * src_h, [config.MARGIN_Y, src_h - config.MARGIN_Y], [0, screen_h])
        return int(np.clip(x, 0, screen_w)), int(np.clip(y, 0, screen_h))

    @staticmethod
    def dynamic_smoothing(
        curr: float, prev: float, alpha_slow: float, alpha_fast: float
    ) -> float:
        """Adaptive EMA smoothing based on speed."""
        diff = abs(curr - prev)
        # If moving fast, use fast alpha. If slow, use slow alpha.
        alpha = alpha_fast if diff > 20 else alpha_slow 
        return prev + alpha * (curr - prev)

# ==============================================================================
# 3. THREADED CAMERA DRIVER
# ==============================================================================

class CameraThread:
    """
    Dedicated thread for frame capturing.
    Prevents I/O blocking in the main processing loop.
    """
    def __init__(self, src: int = 0):
        self.src = src
        self.cap = cv2.VideoCapture(self.src)
        self._configure_camera()
        
        self.frame: Optional[np.ndarray] = None
        self.grabbed: bool = False
        self.stopped: bool = False
        self.lock = threading.Lock()
        
        # Start the thread
        self.thread = threading.Thread(target=self._update, args=(), daemon=True)
        self.thread.start()

    def _configure_camera(self):
        """Sets hardware parameters."""
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, config.FPS)

    def _update(self):
        """Main thread loop."""
        while not self.stopped:
            if not self.cap.isOpened():
                logger.warning("Camera disconnected. Reconnecting...")
                time.sleep(2)
                self.cap.open(self.src)
                self._configure_camera()
                continue
            
            grabbed, frame = self.cap.read()
            with self.lock:
                if grabbed:
                    self.grabbed = True
                    self.frame = frame
                else:
                    self.grabbed = False
            time.sleep(0.005) # Yield to CPU

    def read(self) -> Optional[np.ndarray]:
        """Thread-safe frame retrieval."""
        with self.lock:
            return self.frame.copy() if self.grabbed and self.frame is not None else None

    def stop(self):
        self.stopped = True
        self.thread.join()
        self.cap.release()

# ==============================================================================
# 4. INTELLIGENT PROCESSING CORE
# ==============================================================================

class VectorEngine:
    """
    The Brain. Handles state machine, gesture logic, and mouse physics.
    """
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # 0 for Speed, 1 for Accuracy
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Physics State
        self.prev_x, self.prev_y = 0.0, 0.0
        self.curr_x, self.curr_y = 0.0, 0.0
        
        # Logic State
        self.is_dragging: bool = False
        self.nav_anchor: Optional[Tuple[float, float]] = None
        self.fist_timer: float = 0.0
        self.nav_timer: float = 0.0

        logger.info(f"Engine Initialized. Screen: {self.screen_w}x{self.screen_h}")

    def _move_cursor_safe(self, raw_x: float, raw_y: float, freeze: bool = False):
        """
        Calculates cursor position with:
        1. Coordinate Mapping
        2. Dynamic Smoothing
        3. Deadzone filtering
        4. Freeze logic
        """
        if freeze: return # Absolute lock

        # 1. Map to screen
        tx, ty = GestureMath.map_coordinates(
            raw_x, raw_y, config.WIDTH, config.HEIGHT, self.screen_w, self.screen_h
        )

        # 2. Dynamic Smoothing (Adaptive)
        sx = GestureMath.dynamic_smoothing(tx, self.prev_x, config.SMOOTH_ALPHA_SLOW, config.SMOOTH_ALPHA_FAST)
        sy = GestureMath.dynamic_smoothing(ty, self.prev_y, config.SMOOTH_ALPHA_SLOW, config.SMOOTH_ALPHA_FAST)

        # 3. Deadzone Check (Anti-Jitter)
        dx = abs(sx - self.prev_x)
        dy = abs(sy - self.prev_y)

        if dx > config.DEADZONE_PIXELS or dy > config.DEADZONE_PIXELS:
            pyautogui.moveTo(sx, sy)
            self.prev_x, self.prev_y = sx, sy
            self.curr_x, self.curr_y = sx, sy

    def process(self, frame: np.ndarray):
        # Pre-processing
        # Resize to improve inference speed if frame is large
        if frame.shape[1] != config.WIDTH:
            frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))
            
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Inference
        results = self.hands.process(rgb)

        # --- No Hands Detected ---
        if not results.multi_hand_landmarks:
            if self.is_dragging:
                pyautogui.mouseUp()
                self.is_dragging = False
                logger.info("Lost tracking -> Release Drag")
            return

        # --- Hands Logic ---
        for hand_lms in results.multi_hand_landmarks:
            lms = hand_lms.landmark
            now = time.time()

            # Finger States (1=Open, 0=Closed)
            # IDs: 8=Index, 12=Middle, 16=Ring, 20=Pinky
            fingers = [1 if lms[tip].y < lms[tip-2].y else 0 for tip in [8, 12, 16, 20]]
            up_count = sum(fingers)
            
            # Distance: Thumb (4) to Index (8)
            pinch_dist = GestureMath.calc_distance(lms[8], lms[4])

            # ------------------------------------------------------------------
            # STATE 1: POINTER / CLICK (Index Finger Up)
            # ------------------------------------------------------------------
            if up_count == 1 or (up_count == 2 and not fingers[1]):
                # LOGIC: FREEZE CURSOR
                # Freeze if we are close to clicking OR currently dragging
                # This prevents the cursor from "jumping" when the thumb muscles move
                should_freeze = (pinch_dist < config.FREEZE_ZONE)
                
                # Move
                self._move_cursor_safe(lms[8].x, lms[8].y, freeze=should_freeze)

                # Click / Drag Logic (Hysteresis)
                if pinch_dist < config.PINCH_START:
                    if not self.is_dragging:
                        pyautogui.mouseDown()
                        self.is_dragging = True
                        # logger.debug("Event: Mouse Down")
                
                elif pinch_dist > config.PINCH_STOP:
                    if self.is_dragging:
                        pyautogui.mouseUp()
                        self.is_dragging = False
                        # logger.debug("Event: Mouse Up")
                
                return

            # ------------------------------------------------------------------
            # STATE 2: NAVIGATION (Index + Middle Up)
            # ------------------------------------------------------------------
            if fingers[0] and fingers[1] and not fingers[2]:
                # Safety Release
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                curr_pos = (lms[9].x, lms[9].y) # Use Palm Center
                
                if self.nav_anchor is None:
                    self.nav_anchor = curr_pos
                else:
                    dx = curr_pos[0] - self.nav_anchor[0]
                    dy = curr_pos[1] - self.nav_anchor[1]
                    
                    if now - self.nav_timer > config.NAV_COOLDOWN:
                        # Swipe Threshold Check
                        if abs(dx) > 0.05 or abs(dy) > 0.05:
                            if abs(dx) > abs(dy):
                                key = 'right' if dx > 0 else 'left'
                            else:
                                key = 'down' if dy > 0 else 'up'
                            
                            pyautogui.press(key)
                            logger.info(f"Gesture: Swipe {key.upper()}")
                            self.nav_timer = now
                            self.nav_anchor = curr_pos # Reset anchor

                return
            else:
                self.nav_anchor = None

            # ------------------------------------------------------------------
            # STATE 3: SYSTEM COMMAND (Fist / Closed Hand)
            # ------------------------------------------------------------------
            if up_count == 0:
                if self.fist_timer == 0:
                    self.fist_timer = now
                elif now - self.fist_timer > config.ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.warning("System Command: ESC Triggered")
                    self.fist_timer = 0
            else:
                self.fist_timer = 0

            # ------------------------------------------------------------------
            # STATE 4: IDLE / PALM (All Open)
            # ------------------------------------------------------------------
            if up_count >= 3:
                # Just move, no clicks allowed
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                self._move_cursor_safe(lms[9].x, lms[9].y)

# ==============================================================================
# 5. MAIN ENTRY POINT
# ==============================================================================

def main():
    print("------------------------------------------------")
    print("   VECTOR GESTURE CONTROL | ENTERPRISE v6.0")
    print("   Status: ONLINE")
    print("------------------------------------------------")
    
    # Graceful Shutdown
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received.")
        cam.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize Components
    try:
        cam = CameraThread(src=config.CAMERA_ID)
        engine = VectorEngine()
        
        # Warmup
        time.sleep(1.0)
        logger.info("System Ready.")

        # Main Loop
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
            
            engine.process(frame)

    except Exception as e:
        logger.critical(f"Critical Failure: {e}", exc_info=True)
    finally:
        try:
            cam.stop()
        except:
            pass
        logger.info("Service Terminated.")

if __name__ == "__main__":
    main()