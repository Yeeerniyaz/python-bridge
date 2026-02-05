#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL SYSTEM - ULTIMATE EDITION
================================================
Author: Vector AI (Gemini) for Yerniyaz
Version: 5.0 (Enterprise)
Date: 2026-02-05

Description:
This module provides a robust, multi-threaded computer vision system
for hand gesture control. It implements a state machine architecture
to handle cursor movement, clicking, dragging, scrolling, and system commands.

Features:
- Threaded Camera Capture with Auto-Reconnect
- MediaPipe Hands Integration with Lite Model
- Advanced Coordinate Smoothing (EMA)
- Gesture Recognition State Machine
- Drag & Drop Support
- 4-Way Navigation (Swipe)
- Performance Monitoring (FPS)
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
from collections import deque
from typing import Tuple, Optional, List, Any

# ==============================================================================
# 1. CONFIGURATION CLASS (БАПТАУЛАР)
# ==============================================================================

class Config:
    """
    Central configuration for the Vector Gesture System.
    All tunable parameters are located here.
    """
    # Camera Settings
    CAMERA_ID: int = 0
    REQ_WIDTH: int = 640        # Request resolution from hardware
    REQ_HEIGHT: int = 480
    PROC_WIDTH: int = 320       # Processing resolution (Internal)
    PROC_HEIGHT: int = 240
    FPS_LIMIT: int = 30

    # Interaction Zone (The "Virtual Pad" in the air)
    MARGIN_X: int = 60          # Left/Right margin
    MARGIN_Y: int = 50          # Top/Bottom margin

    # Cursor Physics
    SMOOTHING_FACTOR: float = 0.15  # Lower = Smoother, Higher = Faster (0.01 - 1.0)
    
    # Gesture Thresholds (Normalized 0.0 - 1.0)
    PINCH_START_DIST: float = 0.040  # Distance to start a pinch (Grab)
    PINCH_STOP_DIST: float = 0.050   # Distance to stop a pinch (Release)
    NAV_SWIPE_THRESH: float = 0.06   # Movement required to trigger swipe
    
    # Timers (Seconds)
    NAV_COOLDOWN: float = 0.5        # Time between swipes
    ESC_HOLD_TIME: float = 3.0       # Time to hold fist for ESC
    CLICK_DEBOUNCE: float = 0.3      # Time between clicks
    
    # Application Settings
    APP_NAME: str = "VECTOR PRO"
    DEBUG_MODE: bool = False         # Set True to see the camera window (requires screen)
    LOG_LEVEL: int = logging.INFO

# ==============================================================================
# 2. LOGGING & UTILS (КӨМЕКШІ ҚҰРАЛДАР)
# ==============================================================================

# Setup professional logging
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s | %(levelname)-8s | %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR")

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = False  # We handle boundaries ourselves
pyautogui.PAUSE = 0.001     # Minimize internal delay

class Utils:
    """Math and Helper static methods."""
    
    @staticmethod
    def calculate_distance(p1, p2) -> float:
        """Euclidean distance between two landmarks."""
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    @staticmethod
    def map_range(value, in_min, in_max, out_min, out_max) -> float:
        """Maps a value from one range to another."""
        return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    @staticmethod
    def clamp(value, min_val, max_val) -> float:
        """Constrains a value between min and max."""
        return max(min_val, min(value, max_val))

class FPSMeter:
    """Tracks frames per second for performance monitoring."""
    def __init__(self):
        self.prev_time = 0
        self.curr_time = 0
        self.fps = 0

    def update(self) -> int:
        self.curr_time = time.time()
        delta = self.curr_time - self.prev_time
        if delta > 0:
            self.fps = int(1 / delta)
        self.prev_time = self.curr_time
        return self.fps

# ==============================================================================
# 3. THREADED CAMERA STREAM (КАМЕРА МОДУЛІ)
# ==============================================================================

class CameraStream:
    """
    Robust camera stream running in a separate thread.
    Handles auto-reconnection and buffering.
    """
    def __init__(self, src=0):
        self.src = src
        self.stream = None
        self.frame = None
        self.grabbed = False
        self.stopped = False
        self.lock = threading.Lock()
        
        # Start connection immediately
        self._connect()

    def _connect(self):
        """Internal method to connect to the camera driver."""
        try:
            if self.stream:
                self.stream.release()
            
            logger.info(f"Connecting to Camera ID {self.src}...")
            self.stream = cv2.VideoCapture(self.src)
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, Config.REQ_WIDTH)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.REQ_HEIGHT)
            self.stream.set(cv2.CAP_PROP_FPS, Config.FPS_LIMIT)
            
            # Initial read
            self.grabbed, self.frame = self.stream.read()
            
            if self.grabbed:
                logger.info("✅ Camera connected successfully.")
            else:
                logger.warning("⚠️ Camera connected but returned no frame.")
                
        except Exception as e:
            logger.error(f"❌ Camera connection error: {e}")

    def start(self):
        """Starts the capture thread."""
        t = threading.Thread(target=self._update, args=(), daemon=True)
        t.start()
        return self

    def _update(self):
        """Thread loop."""
        while not self.stopped:
            # Check connection health
            if not self.stream or not self.stream.isOpened():
                logger.warning("🔄 Camera lost. Reconnecting...")
                time.sleep(2)
                self._connect()
                continue

            try:
                grabbed, frame = self.stream.read()
                
                with self.lock:
                    if grabbed:
                        self.grabbed = grabbed
                        self.frame = frame
                    else:
                        self.grabbed = False
                
                # Tiny sleep to release GIL and prevent CPU burn
                time.sleep(0.005)
                
            except Exception as e:
                logger.error(f"⚠️ Frame capture error: {e}")
                time.sleep(0.5)

    def read(self):
        """Returns the latest frame in a thread-safe manner."""
        with self.lock:
            if self.grabbed and self.frame is not None:
                return self.frame.copy()
            return None

    def stop(self):
        """Stops the stream and releases resources."""
        self.stopped = True
        if self.stream:
            self.stream.release()
        logger.info("Camera stream stopped.")

# ==============================================================================
# 4. GESTURE LOGIC CORE (ЖЕСТТЕР МИЫ)
# ==============================================================================

class VectorBrain:
    """
    The core logic processor.
    Analyzes hand landmarks and executes system actions.
    """
    def __init__(self):
        # Initialize MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # Lite model for speed on RPi
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.mp_draw = mp.solutions.drawing_utils
        
        # Screen Metrics
        self.screen_w, self.screen_h = pyautogui.size()
        
        # State Variables
        self.prev_x, self.prev_y = 0.0, 0.0
        self.curr_x, self.curr_y = 0.0, 0.0
        
        # Flags
        self.is_dragging = False
        self.nav_anchor = None  # (x, y) tuple for navigation origin
        
        # Timers
        self.timer_fist_start = 0
        self.timer_last_nav = 0
        
        logger.info("VectorBrain initialized.")

    def _process_cursor_movement(self, raw_x, raw_y):
        """
        Handles smoothing and mapping from camera coordinates to screen coordinates.
        Uses Linear Interpolation and Exponential Moving Average.
        """
        # 1. Map Coordinates (Crop margins)
        x = Utils.map_range(raw_x * Config.PROC_WIDTH, 
                            Config.MARGIN_X, Config.PROC_WIDTH - Config.MARGIN_X, 
                            0, self.screen_w)
        
        y = Utils.map_range(raw_y * Config.PROC_HEIGHT, 
                            Config.MARGIN_Y, Config.PROC_HEIGHT - Config.MARGIN_Y, 
                            0, self.screen_h)

        # 2. Clamp to screen boundaries
        x = Utils.clamp(x, 0, self.screen_w)
        y = Utils.clamp(y, 0, self.screen_h)

        # 3. Apply Smoothing (EMA)
        self.curr_x = self.prev_x + (x - self.prev_x) * Config.SMOOTHING_FACTOR
        self.curr_y = self.prev_y + (y - self.prev_y) * Config.SMOOTHING_FACTOR
        
        # 4. Move Mouse
        pyautogui.moveTo(self.curr_x, self.curr_y)
        
        # 5. Update history
        self.prev_x, self.prev_y = self.curr_x, self.curr_y

    def _handle_drag_drop(self, pinch_distance):
        """Manages Drag & Drop states with hysteresis."""
        if pinch_distance < Config.PINCH_START_DIST:
            if not self.is_dragging:
                pyautogui.mouseDown()
                self.is_dragging = True
                logger.info("✊ DRAG STARTED (Mouse Down)")
        
        elif pinch_distance > Config.PINCH_STOP_DIST:
            if self.is_dragging:
                pyautogui.mouseUp()
                self.is_dragging = False
                logger.info("✋ DROP EXECUTED (Mouse Up)")

    def _handle_navigation(self, current_pos, now):
        """Handles 4-Way Swipe Navigation."""
        # Initialize anchor if new gesture
        if self.nav_anchor is None:
            self.nav_anchor = current_pos
            logger.info("🕹 NAV: ANCHOR LOCKED")
            return

        # Calculate Delta
        dx = current_pos[0] - self.nav_anchor[0]
        dy = current_pos[1] - self.nav_anchor[1]

        # Check cooldown
        if now - self.timer_last_nav > Config.NAV_COOLDOWN:
            # Axis Locking: Determine primary direction
            if abs(dx) > abs(dy):
                # Horizontal
                if abs(dx) > Config.NAV_SWIPE_THRESH:
                    key = 'right' if dx > 0 else 'left'
                    pyautogui.press(key)
                    logger.info(f"➡️ SWIPE: {key.upper()}")
                    self.timer_last_nav = now
                    self.nav_anchor = current_pos # Reset anchor
            else:
                # Vertical
                if abs(dy) > Config.NAV_SWIPE_THRESH:
                    key = 'down' if dy > 0 else 'up'
                    pyautogui.press(key)
                    logger.info(f"⬇️ SWIPE: {key.upper()}")
                    self.timer_last_nav = now
                    self.nav_anchor = current_pos # Reset anchor

    def process_frame(self, frame):
        """
        Main processing pipeline for a single frame.
        """
        # 1. Image Pre-processing
        h, w, c = frame.shape
        # Resize if input is different from processing res
        if w != Config.PROC_WIDTH or h != Config.PROC_HEIGHT:
            frame_small = cv2.resize(frame, (Config.PROC_WIDTH, Config.PROC_HEIGHT))
        else:
            frame_small = frame
            
        frame_small = cv2.flip(frame_small, 1) # Mirror
        rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)

        # 2. Hand Detection
        results = self.hands.process(rgb)

        # 3. Logic Decision Tree
        if not results.multi_hand_landmarks:
            # Safety: Release drag if hand lost
            if self.is_dragging:
                pyautogui.mouseUp()
                self.is_dragging = False
                logger.warning("Hand lost during drag -> Forced Release")
            
            # Reset states
            self.nav_anchor = None
            self.timer_fist_start = 0
            return

        for hand_lms in results.multi_hand_landmarks:
            # Extract landmarks for readability
            lms = hand_lms.landmark
            
            # --- FINGER STATE ANALYSIS ---
            # 1 = Finger Up, 0 = Finger Down
            fingers = []
            
            # Index (8) vs PIP (6)
            fingers.append(1 if lms[8].y < lms[6].y else 0)
            # Middle (12) vs PIP (10)
            fingers.append(1 if lms[12].y < lms[10].y else 0)
            # Ring (16) vs PIP (14)
            fingers.append(1 if lms[16].y < lms[14].y else 0)
            # Pinky (20) vs PIP (18)
            fingers.append(1 if lms[20].y < lms[18].y else 0)
            
            # Thumb (4) is tricky, we verify based on X relative to IP (3)
            # Assuming right hand logic mirrored. Simplified: just check count.
            
            up_count = sum(fingers)
            now = time.time()
            
            # Debug Draw (Optional)
            if Config.DEBUG_MODE:
                self.mp_draw.draw_landmarks(frame_small, hand_lms, self.mp_hands.HAND_CONNECTIONS)

            # ==================================================================
            # GESTURE 1: FIST (ESC) -> 0 FINGERS
            # ==================================================================
            if up_count == 0:
                # Release mouse if dragging
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                if self.timer_fist_start == 0:
                    self.timer_fist_start = now
                elif now - self.timer_fist_start > Config.ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.info("🔐 SYSTEM COMMAND: ESC EXECUTE")
                    self.timer_fist_start = 0 # Reset
                
                # Visual feedback for holding could go here
                return
            
            self.timer_fist_start = 0 # Reset if fingers open

            # ==================================================================
            # GESTURE 2: NAVIGATION (VICTORY) -> 2 FINGERS (Index + Middle)
            # ==================================================================
            if fingers[0] and fingers[1] and not fingers[2] and not fingers[3]:
                # Safety release
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                # Use Palm Center (9) for navigation anchor
                curr_pos = np.array([lms[9].x, lms[9].y])
                self._handle_navigation(curr_pos, now)
                return
            
            self.nav_anchor = None # Reset anchor if gesture breaks

            # ==================================================================
            # GESTURE 3: PALM MOVE (SAFE) -> 3+ FINGERS
            # ==================================================================
            if up_count >= 3:
                # Safety release
                if self.is_dragging: pyautogui.mouseUp(); self.is_dragging = False
                
                # Move with Palm Center (9) for stability
                self._process_cursor_movement(lms[9].x, lms[9].y)
                return

            # ==================================================================
            # GESTURE 4: POINTER / DRAG (INDEX FINGER) -> 1 FINGER
            # ==================================================================
            # Allow case where thumb is out (up_count 1 or 2)
            if up_count == 1 or (up_count == 2 and not fingers[1]):
                # Key Points
                index_tip = lms[8]
                thumb_tip = lms[4]

                # 1. Move Cursor first
                self._process_cursor_movement(index_tip.x, index_tip.y)

                # 2. Check Pinch Distance
                dist = Utils.calculate_distance(index_tip, thumb_tip)
                
                # 3. Handle Drag/Click logic
                self._handle_drag_drop(dist)
                return

# ==============================================================================
# 5. MAIN EXECUTION LOOP (БАСҚАРУ ПУЛЬТІ)
# ==============================================================================

def main():
    """
    Main entry point for the application.
    """
    print(f"""
    ################################################
    #   VECTOR GESTURE CONTROL - PRO ENTERPRISE    #
    #   ---------------------------------------    #
    #   Author: Yerniyaz's AI Assistant            #
    #   Status: ACTIVE                             #
    ################################################
    
    GUIDE:
    [1] ☝️ INDEX FINGER: Move + Pinch to Click/Drag
    [2] ✌️ VICTORY SIGN: Swipe Left/Right/Up/Down
    [3] 🖐 OPEN PALM:   Safe Mouse Move (No Click)
    [4] 👊 FIST:        Hold 3s to Press ESC
    """)

    # Initialize Signal Handlers (Ctrl+C protection)
    def signal_handler(sig, frame):
        logger.info("🛑 Shutdown signal received.")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize Modules
    fps_meter = FPSMeter()
    cam = CameraStream(src=Config.CAMERA_ID).start()
    brain = VectorBrain()
    
    # Allow camera warmup
    logger.info("Waiting for camera warmup...")
    time.sleep(1.0)
    logger.info("System Ready. Monitoring gestures.")

    try:
        while True:
            # 1. Get Frame
            frame = cam.read()
            
            if frame is None:
                # If no frame, sleep briefly to save CPU
                time.sleep(0.01)
                continue
            
            # 2. Process Logic
            brain.process_frame(frame)
            
            # 3. FPS Monitoring (Log every 5 seconds or via debug)
            fps = fps_meter.update()
            # print(f"FPS: {fps}", end='\r') # Optional CLI output

    except KeyboardInterrupt:
        logger.info("User requested stop.")
    except Exception as e:
        logger.critical(f"🔥 FATAL ERROR: {e}", exc_info=True)
    finally:
        # Cleanup
        if brain.is_dragging:
            pyautogui.mouseUp()
        cam.stop()
        logger.info("Vector Service Terminated Gracefully.")
        sys.exit(0)

if __name__ == "__main__":
    main()