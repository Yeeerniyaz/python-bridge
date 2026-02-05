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

# ================= CONFIGURATION =================
CAMERA_ID = 0
FRAME_WIDTH = 320   # Низкое разрешение для скорости RPi
FRAME_HEIGHT = 240
SMOOTHING = 5       # Коэффициент сглаживания (чем больше, тем плавнее, но медленнее)
CLICK_THRESHOLD = 0.04
SCROLL_THRESHOLD = 0.05  # Чувствительность для жестов стрелок

# Настройки PyAutoGUI
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [VECTOR] - %(message)s')
logger = logging.getLogger("GESTURE_CORE")

# ================= THREADED CAMERA =================
class WebcamStream:
    """
    Захват видео в отдельном потоке. 
    Это критично для RPi, чтобы обработка кадров не тормозила чтение с камеры.
    """
    def __init__(self, src=0, width=320, height=240):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.stream.set(cv2.CAP_PROP_FPS, 30)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            grabbed, frame = self.stream.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.005) # Небольшая пауза, чтобы не грузить CPU вхолостую

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# ================= GESTURE ENGINE =================
class VectorGestureEngine:
    def __init__(self):
        # Инициализация MediaPipe с оптимизацией для CPU RPi
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # 0 = Lite (самый быстрый), 1 = Full
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Переменные для сглаживания
        self.prev_x, self.prev_y = 0, 0
        self.curr_x, self.curr_y = 0, 0
        
        # Состояние кликов (защита от дребезга)
        self.last_click_time = 0
        self.click_cooldown = 0.4
        
        # Состояние свайпов/стрелок
        self.last_nav_time = 0
        self.nav_cooldown = 0.3
        self.nav_center_x = None
        self.nav_center_y = None

    def get_dist(self, p1, p2):
        return np.linalg.norm(np.array([p1.x, p1.y]) - np.array([p2.x, p2.y]))

    def process_frame(self, frame):
        # Отражаем и конвертируем
        frame = cv2.flip(frame, 1)
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)
        
        action_log = None

        if results.multi_hand_landmarks:
            for hand_lms in results.multi_hand_landmarks:
                # Ключевые точки
                wrist = hand_lms.landmark[0]
                thumb_tip = hand_lms.landmark[4]
                index_tip = hand_lms.landmark[8]
                middle_tip = hand_lms.landmark[12]
                ring_tip = hand_lms.landmark[16]
                pinky_tip = hand_lms.landmark[20]

                # --- РАСПОЗНАВАНИЕ ЖЕСТОВ ---

                # 1. Проверка на КУЛАК (Fist) -> ESC
                # Логика: кончики пальцев ниже суставов или близко к ладони
                fingers_folded = (
                    index_tip.y > hand_lms.landmark[6].y and
                    middle_tip.y > hand_lms.landmark[10].y and
                    ring_tip.y > hand_lms.landmark[14].y and
                    pinky_tip.y > hand_lms.landmark[18].y
                )

                if fingers_folded:
                    if time.time() - self.last_click_time > 1.0: # Долгий кулдаун для ESC
                        pyautogui.press('esc')
                        self.last_click_time = time.time()
                        return "🔐 ESCAPE"
                    return "✊ FIST (Wait)"

                # 2. Режим НАВИГАЦИИ (Victory/Peace sign) -> Стрелки
                # Указательный и Средний подняты, остальные согнуты
                is_nav_mode = (
                    index_tip.y < hand_lms.landmark[6].y and
                    middle_tip.y < hand_lms.landmark[10].y and
                    ring_tip.y > hand_lms.landmark[14].y and
                    pinky_tip.y > hand_lms.landmark[18].y
                )

                if is_nav_mode:
                    # Центр ладони для трекинга движения
                    cx, cy = wrist.x, wrist.y
                    
                    if self.nav_center_x is None:
                        self.nav_center_x, self.nav_center_y = cx, cy
                        return "🕹 NAV START"
                    
                    dx = cx - self.nav_center_x
                    dy = cy - self.nav_center_y
                    
                    if time.time() - self.last_nav_time > self.nav_cooldown:
                        if dx > SCROLL_THRESHOLD:
                            pyautogui.press('right')
                            action_log = "➡️ RIGHT"
                            self.last_nav_time = time.time()
                        elif dx < -SCROLL_THRESHOLD:
                            pyautogui.press('left')
                            action_log = "⬅️ LEFT"
                            self.last_nav_time = time.time()
                        elif dy > SCROLL_THRESHOLD:
                            pyautogui.press('down')
                            action_log = "⬇️ DOWN"
                            self.last_nav_time = time.time()
                        elif dy < -SCROLL_THRESHOLD:
                            pyautogui.press('up')
                            action_log = "⬆️ UP"
                            self.last_nav_time = time.time()
                    
                    return action_log if action_log else "🕹 NAVIGATING..."

                else:
                    self.nav_center_x = None # Сброс центра навигации

                # 3. Режим КУРСОРА (только указательный палец поднят)
                # Двигаем курсор
                x = int(index_tip.x * self.screen_w)
                y = int(index_tip.y * self.screen_h)

                # Сглаживание (Linear Interpolation)
                self.curr_x = self.prev_x + (x - self.prev_x) / SMOOTHING
                self.curr_y = self.prev_y + (y - self.prev_y) / SMOOTHING
                
                # Ограничение экрана
                self.curr_x = np.clip(self.curr_x, 0, self.screen_w - 1)
                self.curr_y = np.clip(self.curr_y, 0, self.screen_h - 1)

                pyautogui.moveTo(self.curr_x, self.curr_y)
                self.prev_x, self.prev_y = self.curr_x, self.curr_y

                # --- КЛИКИ ---
                
                # Левый клик: Указательный + Большой
                dist_l = self.get_dist(index_tip, thumb_tip)
                if dist_l < CLICK_THRESHOLD:
                    if time.time() - self.last_click_time > self.click_cooldown:
                        pyautogui.click()
                        self.last_click_time = time.time()
                        return "🖱 LEFT CLICK"

                # Правый клик: Средний + Большой
                dist_r = self.get_dist(middle_tip, thumb_tip)
                if dist_r < CLICK_THRESHOLD:
                    if time.time() - self.last_click_time > self.click_cooldown:
                        pyautogui.rightClick()
                        self.last_click_time = time.time()
                        return "🖱 RIGHT CLICK"
        
        return None

# ================= MAIN LOOP =================
def run_vector_vision():
    logger.info("🚀 VECTOR Vision Engine Starting...")
    logger.info("   -> Mode: Optimized for RPi 4/5")
    logger.info("   -> Gestures: Pointer, Pinches(L/R), Victory(Nav), Fist(Esc)")

    try:
        # Запуск камеры в потоке
        cam = WebcamStream(src=CAMERA_ID, width=FRAME_WIDTH, height=FRAME_HEIGHT).start()
        # Инициализация движка жестов
        engine = VectorGestureEngine()
        
        # Даем камере прогреться
        time.sleep(1.0)
        
        running = True
        
        while running:
            frame = cam.read()
            if frame is None:
                time.sleep(0.1)
                continue

            # Обработка
            status = engine.process_frame(frame)
            if status:
                logger.info(f"Action: {status}")

            # Небольшой сон для разгрузки CPU, если FPS слишком высок (опционально)
            # time.sleep(0.001)

    except KeyboardInterrupt:
        logger.info("🛑 Stopping by user request...")
    except Exception as e:
        logger.error(f"💥 CRITICAL ERROR: {e}")
    finally:
        if 'cam' in locals():
            cam.stop()
        logger.info("👋 System Shutdown")
        sys.exit(0)

# Обработчик сигналов для systemd
def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    run_vector_vision()