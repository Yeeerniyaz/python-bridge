import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys
from collections import deque

# ================= ⚙️ CONFIGURATION (PROFESSIONAL TUNING) =================
# Camera & Performance
CAMERA_ID = 0
PROCESS_W, PROCESS_H = 320, 240  # Low res for max FPS on RPi
cam_width, cam_height = 640, 480 # Hardware request

# Interaction Zone (Comfort Box)
MARGIN_X = 60
MARGIN_Y = 50

# Smoothing (Cursor Stability)
# 0.0 = Frozen, 1.0 = No smoothing. 0.15 is best for RPi.
SMOOTH_FACTOR = 0.15 

# Gestures Sensitivity
CLICK_PINCH_DIST = 0.040   # Щипок (Меньше = сложнее кликнуть)
NAV_THRESHOLD = 0.08       # Насколько сдвинуть руку для свайпа (0.05 = чувствительно, 0.15 = туго)
NAV_COOLDOWN = 0.8         # Пауза между свайпами (сек)
ESC_HOLD_DURATION = 1.2    # Время удержания кулака (сек)

# PyAutoGUI Setup
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.005

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s | VECTOR | %(message)s')
logger = logging.getLogger("VECTOR_PRO")

# ================= 🏎 THREADED CAMERA ENGINE =================
class CameraEngine:
    """
    Захватывает кадры в отдельном потоке (Non-blocking I/O).
    Гарантирует, что CV2 не тормозит вычисления жестов.
    """
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, cam_width)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, cam_height)
        self.stream.set(cv2.CAP_PROP_FPS, 30)
        
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._update, args=(), daemon=True).start()
        return self

    def _update(self):
        while not self.stopped:
            grabbed, frame = self.stream.read()
            with self.lock:
                if grabbed:
                    self.grabbed = grabbed
                    self.frame = frame
            time.sleep(0.005) # Prevent CPU burn

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# ================= 🧠 INTELLIGENT GESTURE CORE =================
class VectorGestureCore:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # Lite model for RPi speed
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # State Vectors
        self.cursor = np.array([0.0, 0.0]) # [x, y]
        self.prev_cursor = np.array([0.0, 0.0])
        
        # Gesture Timers & States
        self.timers = {
            'fist': 0.0,
            'click': 0.0,
            'nav': 0.0
        }
        self.nav_anchor = None # Центр навигации (где начался жест)

    def _smooth_coordinates(self, target_x, target_y):
        """
        Экспоненциальное скользящее среднее (EMA) для плавности курсора.
        """
        # Mapping from Process Zone to Screen Zone
        screen_x = np.interp(target_x * PROCESS_W, (MARGIN_X, PROCESS_W - MARGIN_X), (0, self.scr_w))
        screen_y = np.interp(target_y * PROCESS_H, (MARGIN_Y, PROCESS_H - MARGIN_Y), (0, self.scr_h))

        # Clamp to screen bounds
        screen_x = np.clip(screen_x, 0, self.scr_w - 1)
        screen_y = np.clip(screen_y, 0, self.scr_h - 1)

        # Smoothing Math
        self.cursor[0] = self.prev_cursor[0] + (screen_x - self.prev_cursor[0]) * SMOOTH_FACTOR
        self.cursor[1] = self.prev_cursor[1] + (screen_y - self.prev_cursor[1]) * SMOOTH_FACTOR
        
        self.prev_cursor = self.cursor.copy()
        return int(self.cursor[0]), int(self.cursor[1])

    def process_frame(self, frame):
        # 1. Pre-processing
        small_frame = cv2.resize(frame, (PROCESS_W, PROCESS_H))
        small_frame = cv2.flip(small_frame, 1) # Mirror effect
        rgb = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        
        results = self.hands.process(rgb)
        
        if not results.multi_hand_landmarks:
            self.nav_anchor = None # Reset navigation if hand lost
            return

        for hand in results.multi_hand_landmarks:
            # 2. Extract Landmarks (Normalized 0.0 - 1.0)
            lms = hand.landmark
            
            # Key Points
            wrist = lms[0]
            thumb = lms[4]
            index = lms[8]
            middle = lms[12]
            palm_center = lms[9]

            # 3. Finger States (1 = Up, 0 = Down)
            fingers = [
                1 if lms[8].y < lms[6].y else 0,  # Index
                1 if lms[12].y < lms[10].y else 0, # Middle
                1 if lms[16].y < lms[14].y else 0, # Ring
                1 if lms[20].y < lms[18].y else 0  # Pinky
            ]
            fingers_count = sum(fingers)
            
            now = time.time()

            # ================= LOGIC TREE =================
            
            # [A] ✊ FIST (ESCAPE) -> 0 Fingers
            if fingers_count == 0:
                self.nav_anchor = None # Reset Nav
                if self.timers['fist'] == 0:
                    self.timers['fist'] = now
                elif now - self.timers['fist'] > ESC_HOLD_DURATION:
                    pyautogui.press('esc')
                    logger.info("🔐 SYSTEM: ESCAPE EXECUTED")
                    self.timers['fist'] = 0 # Reset
                return

            self.timers['fist'] = 0 # Reset fist timer if fingers open

            # [B] ✌️ VICTORY (NAVIGATION) -> 2 Fingers (Index + Middle)
            if fingers == [1, 1, 0, 0]:
                current_pos = np.array([palm_center.x, palm_center.y])
                
                # Инициализация якоря (где жест начался)
                if self.nav_anchor is None:
                    self.nav_anchor = current_pos
                    logger.info("🕹 NAV: LOCKED (Waiting for swipe)")
                    return

                # Вектор движения от якоря
                delta = current_pos - self.nav_anchor
                dx, dy = delta[0], delta[1]
                
                # Check Cooldown
                if now - self.timers['nav'] > NAV_COOLDOWN:
                    # Logic: Axis Locking (Блокировка оси)
                    # Если движение по X больше чем по Y, считаем это горизонтальным свайпом
                    if abs(dx) > abs(dy): 
                        if abs(dx) > NAV_THRESHOLD:
                            if dx > 0:
                                pyautogui.press('right')
                                logger.info("➡️ SWIPE: RIGHT")
                            else:
                                pyautogui.press('left')
                                logger.info("⬅️ SWIPE: LEFT")
                            self.timers['nav'] = now
                            # Не сбрасываем якорь полностью, чтобы можно было делать серию свайпов?
                            # Нет, лучше сбросить для точности следующего движения.
                            self.nav_anchor = current_pos 
                    
                    # Vertical Axis
                    else: 
                        if abs(dy) > NAV_THRESHOLD:
                            if dy > 0: # Y grows downwards
                                pyautogui.press('down')
                                logger.info("⬇️ SWIPE: DOWN")
                            else:
                                pyautogui.press('up')
                                logger.info("⬆️ SWIPE: UP")
                            self.timers['nav'] = now
                            self.nav_anchor = current_pos
                return

            self.nav_anchor = None # Reset nav anchor if gesture changes

            # [C] 🖐 PALM (SAFE MOVE) -> 4 or 5 Fingers
            if fingers_count >= 4:
                # Use Palm Center for stability
                x, y = self._smooth_coordinates(palm_center.x, palm_center.y)
                pyautogui.moveTo(x, y)
                return

            # [D] ☝️ POINTER (PRECISION + CLICK) -> 1 Finger
            if fingers_count == 1:
                # Use Index Tip for precision
                x, y = self._smooth_coordinates(index.x, index.y)
                pyautogui.moveTo(x, y)

                # Pinch Check (Thumb to Index)
                # Euclidean distance
                dist = np.hypot(index.x - thumb.x, index.y - thumb.y)
                
                if dist < CLICK_PINCH_DIST:
                    if now - self.timers['click'] > 0.4: # Debounce
                        pyautogui.click()
                        logger.info("🖱 MOUSE: CLICK")
                        self.timers['click'] = now
                return

# ================= 🚀 SYSTEM LAUNCHER =================
def run_service():
    logger.info("🚀 VECTOR GESTURE CONTROL: PROFESSIONAL EDITION")
    logger.info(f"   Resolution: {PROCESS_W}x{PROCESS_H} (Anti-Lag)")
    logger.info("   Gestures: [1]Point [2]Swipe [4]Move [0]Esc")

    cam = CameraEngine(src=CAMERA_ID).start()
    brain = VectorGestureCore()
    
    # Warmup
    time.sleep(1.0)

    try:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
            
            brain.process_frame(frame)

    except KeyboardInterrupt:
        logger.info("🛑 Stopping service...")
    except Exception as e:
        logger.error(f"💥 CRITICAL: {e}")
    finally:
        cam.stop()
        sys.exit(0)

if __name__ == "__main__":
    # Handle systemd signals
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    run_service()