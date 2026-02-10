#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL - PURE EDITION (v10.0)
=============================================
- Removed: Bridge, LED, Network calls
- Added: Adaptive Smoothing (Anti-Jitter)
- Added: Click Hysteresis (Reliable Clicking)
- Optimized for: Low Light / Noisy Cameras
"""

import cv2
import mediapipe as mp
import pyautogui
import math
import time
import numpy as np
import logging

# --- CONFIGURATION ---
CAMERA_ID = 0
WIDTH, HEIGHT = 640, 480  # Standard resolution for speed

# Hysteresis for Clicking (Anti-bounce)
CLICK_START = 0.040   # Pinch closer than this -> CLICK DOWN
CLICK_STOP  = 0.070   # Open wider than this -> CLICK UP

# Gestures
MODE_HOLD_TIME = 1.0  # Time to hold Like/Dislike to switch
SWIPE_THRESH = 50     # Pixels for swipe
VOL_EDGE_X = 0.92     # Right edge for volume

# Smoothing Config
MIN_ALPHA = 0.15      # Max smoothing (slow movement)
MAX_ALPHA = 0.7       # Min smoothing (fast movement)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger("VECTOR")

pyautogui.FAILSAFE = False

class GestureMode:
    COMPUTER = "COMPUTER"  # Cursor + Pinch
    CINEMA = "CINEMA"      # Swipes + Fist

class AdaptiveSmoother:
    """Filters jitter from bad cameras while keeping speed."""
    def __init__(self):
        self.prev_x = 0
        self.prev_y = 0
        
    def get_pos(self, target_x, target_y):
        # Calculate speed (distance from last frame)
        dist = math.hypot(target_x - self.prev_x, target_y - self.prev_y)
        
        # Map speed to alpha: 
        # Low speed (0-10px) -> Low Alpha (0.1) -> Very Smooth
        # High speed (50px+) -> High Alpha (0.7) -> Very Responsive
        alpha = np.interp(dist, [0, 50], [MIN_ALPHA, MAX_ALPHA])
        
        # Apply smoothing
        smooth_x = self.prev_x + (target_x - self.prev_x) * alpha
        smooth_y = self.prev_y + (target_y - self.prev_y) * alpha
        
        self.prev_x, self.prev_y = smooth_x, smooth_y
        return int(smooth_x), int(smooth_y)

class VectorBrain:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        # Model Complexity 0 is fastest, 1 is better accuracy. 
        # We use 0 but rely on filtering for quality.
        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.scr_w, self.scr_h = pyautogui.size()
        self.smoother = AdaptiveSmoother()
        
        # State
        self.mode = GestureMode.COMPUTER
        self.is_dragging = False
        self.mode_timer = 0
        self.swipe_cooldown = 0
        self.vol_active = False
        self.last_vol_y = 0

    def get_dist(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def process(self, frame):
        # Optimization: Resize if camera sends huge frames
        if frame.shape[1] != WIDTH:
             frame = cv2.resize(frame, (WIDTH, HEIGHT))

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.hands.process(rgb)

        if not res.multi_hand_landmarks:
            return frame

        lms = res.multi_hand_landmarks[0].landmark
        
        # Fingers state (Rough estimation)
        # 1=Open, 0=Closed (Based on Tip Y vs Pip Y)
        fingers = []
        for id in [4, 8, 12, 16, 20]:
            if id == 4: # Thumb: check X
                fingers.append(1 if lms[4].x < lms[3].x else 0)
            else:       # Others: check Y
                fingers.append(1 if lms[id].y < lms[id-2].y else 0)

        # Key Points
        idx_pt = lms[8]   # Index Tip
        thumb_pt = lms[4] # Thumb Tip
        
        # --- 1. GLOBAL GESTURES ---
        
        # CHANGE MODE (Like 👍)
        if fingers == [1, 0, 0, 0, 0] or fingers == [1, 1, 0, 0, 0]: 
            # Allow index to be loosely open/closed to help bad cameras
            if self.mode_timer == 0: self.mode_timer = time.time()
            elif time.time() - self.mode_timer > MODE_HOLD_TIME:
                self.mode = GestureMode.CINEMA if self.mode == GestureMode.COMPUTER else GestureMode.COMPUTER
                logger.info(f"🔄 SWITCH MODE -> {self.mode}")
                self.mode_timer = 0
                time.sleep(0.5)
        else:
            self.mode_timer = 0

        # PAUSE (Palm 🖐️)
        if sum(fingers) >= 4:
            if time.time() - self.swipe_cooldown > 1.0:
                pyautogui.press('space')
                logger.info("⏸ PAUSE/PLAY")
                self.swipe_cooldown = time.time()
            return frame

        # VOLUME (Edge Slider)
        if idx_pt.x > VOL_EDGE_X:
            if not self.vol_active:
                self.vol_active = True
                self.last_vol_y = idx_pt.y
            else:
                diff = self.last_vol_y - idx_pt.y
                if abs(diff) > 0.04: # Sensitivity threshold
                    if diff > 0: pyautogui.press('volumeup')
                    else: pyautogui.press('volumedown')
                    self.last_vol_y = idx_pt.y
            return frame
        else:
            self.vol_active = False

        # --- 2. COMPUTER MODE ---
        if self.mode == GestureMode.COMPUTER:
            # Move Cursor (Index Up)
            if fingers[1] == 1:
                # Mapping with margin
                margin = 60
                screen_x = np.interp(idx_pt.x * WIDTH, [margin, WIDTH-margin], [0, self.scr_w])
                screen_y = np.interp(idx_pt.y * HEIGHT, [margin, HEIGHT-margin], [0, self.scr_h])
                
                # Adaptive Smooth Move
                final_x, final_y = self.smoother.get_pos(screen_x, screen_y)
                pyautogui.moveTo(final_x, final_y)

                # Click Logic (Hysteresis)
                dist = self.get_dist(thumb_pt, idx_pt)
                
                # HYSTERESIS: Harder to click, Harder to release
                if dist < CLICK_START: 
                    if not self.is_dragging:
                        pyautogui.mouseDown()
                        self.is_dragging = True
                        logger.info("mb_down")
                elif dist > CLICK_STOP:
                    if self.is_dragging:
                        pyautogui.mouseUp()
                        self.is_dragging = False
                        logger.info("mb_up")

        # --- 3. CINEMA MODE ---
        elif self.mode == GestureMode.CINEMA:
            # Enter (Fist ✊)
            if sum(fingers) == 0:
                if time.time() - self.swipe_cooldown > 1.5:
                    pyautogui.press('enter')
                    logger.info("✊ ENTER")
                    self.swipe_cooldown = time.time()
            
            # Swipes (Movement analysis)
            # Simplified: track Index Finger movement
            if fingers[1] == 1:
                cx, cy = int(idx_pt.x * WIDTH), int(idx_pt.y * HEIGHT)
                if not hasattr(self, 'last_sw_x'): 
                    self.last_sw_x, self.last_sw_y = cx, cy

                dx = cx - self.last_sw_x
                dy = cy - self.last_sw_y
                
                if time.time() - self.swipe_cooldown > 0.5:
                    if abs(dx) > SWIPE_THRESH:
                        key = 'right' if dx > 0 else 'left'
                        pyautogui.press(key)
                        logger.info(f"SWIPE {key.upper()}")
                        self.swipe_cooldown = time.time()
                    elif abs(dy) > SWIPE_THRESH:
                        key = 'down' if dy > 0 else 'up'
                        pyautogui.press(key)
                        logger.info(f"SWIPE {key.upper()}")
                        self.swipe_cooldown = time.time()
                
                self.last_sw_x, self.last_sw_y = cx, cy

        return frame

def main():
    cap = cv2.VideoCapture(CAMERA_ID)
    cap.set(3, WIDTH)
    cap.set(4, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30) # Try to force 30 FPS
    
    brain = VectorBrain()
    print("VECTOR PURE: Started.")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        brain.process(frame)
        # No imshow() needed for production
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()

if __name__ == "__main__":
    main()