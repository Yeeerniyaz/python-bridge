import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys

# ================= ⚙️ НАСТРОЙКИ (КОНФИГ) =================
CAMERA_ID = 0
PROCESS_WIDTH = 320     # Низкое разрешение для скорости RPi
PROCESS_HEIGHT = 240
MARGIN_X = 50           # Отступы (Зона комфорта)
MARGIN_Y = 40

CLICK_DIST = 0.04       # Расстояние щипка для клика
SCROLL_THRESH = 0.1     # Чувствительность для стрелок/скролла
SMOOTHING = 0.2         # Сглаживание мыши (0.1 - вязко, 0.5 - резко)
ESC_HOLD_TIME = 1.0     # Время удержания кулака

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

logging.basicConfig(level=logging.INFO, format='%(asctime)s | VECTOR: %(message)s')
logger = logging.getLogger("VECTOR")

# ================= 🏎 АДАПТИВНАЯ КАМЕРА =================
class AdaptiveStream:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
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
                if grabbed:
                    self.grabbed = grabbed
                    self.frame = frame
            time.sleep(0.005)

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# ================= 🧠 МОЗГ VECTOR =================
class VectorBrain:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # Lite для скорости
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # Переменные состояния
        self.curr_x, self.curr_y = 0, 0
        self.prev_x, self.prev_y = 0, 0
        self.fist_time = 0
        self.last_click = 0
        self.last_nav = 0
        self.nav_center = None # Центр для жестов навигации

    def move_mouse(self, x_norm, y_norm):
        # Преобразование координат (с учетом полей)
        x = np.interp(x_norm * PROCESS_WIDTH, (MARGIN_X, PROCESS_WIDTH - MARGIN_X), (0, self.scr_w))
        y = np.interp(y_norm * PROCESS_HEIGHT, (MARGIN_Y, PROCESS_HEIGHT - MARGIN_Y), (0, self.scr_h))

        # Сглаживание
        self.curr_x = self.prev_x + (x - self.prev_x) * SMOOTHING
        self.curr_y = self.prev_y + (y - self.prev_y) * SMOOTHING
        
        self.curr_x = np.clip(self.curr_x, 0, self.scr_w)
        self.curr_y = np.clip(self.curr_y, 0, self.scr_h)
        
        pyautogui.moveTo(self.curr_x, self.curr_y)
        self.prev_x, self.prev_y = self.curr_x, self.curr_y

    def process(self, frame):
        # Подготовка кадра (быстро)
        small = cv2.resize(frame, (PROCESS_WIDTH, PROCESS_HEIGHT))
        small = cv2.flip(small, 1)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        if not results.multi_hand_landmarks:
            return

        for hand in results.multi_hand_landmarks:
            # Анализ пальцев (поднят/опущен)
            tips = [8, 12, 16, 20] # Указ, Сред, Безым, Мизинец
            pips = [6, 10, 14, 18] # Суставы ниже
            
            fingers = []
            # Указательный
            fingers.append(1 if hand.landmark[8].y < hand.landmark[6].y else 0)
            # Средний
            fingers.append(1 if hand.landmark[12].y < hand.landmark[10].y else 0)
            # Безымянный
            fingers.append(1 if hand.landmark[16].y < hand.landmark[14].y else 0)
            # Мизинец
            fingers.append(1 if hand.landmark[20].y < hand.landmark[18].y else 0)
            
            total = sum(fingers)
            
            # Координаты ключевых точек
            idx_pt = hand.landmark[8]  # Указательный
            thm_pt = hand.landmark[4]  # Большой
            palm_pt = hand.landmark[9] # Центр ладони

            # ---------------------------------------------------------
            # 1. 🛑 ЖЕСТ: КУЛАК (ESC) [0 пальцев]
            # ---------------------------------------------------------
            if total == 0:
                if self.fist_time == 0: self.fist_time = time.time()
                elif time.time() - self.fist_time > ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.info("🔐 ESCAPE")
                    self.fist_time = 0
                return

            self.fist_time = 0 # Сброс таймера кулака

            # ---------------------------------------------------------
            # 2. ✌️ ЖЕСТ: МИР (НАВИГАЦИЯ/СТРЕЛКИ) [2 пальца]
            # ---------------------------------------------------------
            if fingers[0] and fingers[1] and not fingers[2]:
                # Фиксируем точку старта, если только вошли в режим
                if self.nav_center is None:
                    self.nav_center = (palm_pt.x, palm_pt.y)
                    logger.info("🕹 NAV START")
                    return

                # Считаем отклонение от точки старта
                dx = palm_pt.x - self.nav_center[0]
                dy = palm_pt.y - self.nav_center[1]

                if time.time() - self.last_nav > 0.4: # Скорость повтора
                    if dx > SCROLL_THRESH:
                        pyautogui.press('right')
                        logger.info("➡️ RIGHT")
                        self.last_nav = time.time()
                    elif dx < -SCROLL_THRESH:
                        pyautogui.press('left')
                        logger.info("⬅️ LEFT")
                        self.last_nav = time.time()
                    elif dy > SCROLL_THRESH:
                        pyautogui.press('down') # или pyautogui.scroll(-50)
                        logger.info("⬇️ DOWN")
                        self.last_nav = time.time()
                    elif dy < -SCROLL_THRESH:
                        pyautogui.press('up')   # или pyautogui.scroll(50)
                        logger.info("⬆️ UP")
                        self.last_nav = time.time()
                return 

            self.nav_center = None # Сброс центра навигации

            # ---------------------------------------------------------
            # 3. 🖐 ЖЕСТ: ЛАДОНЬ (БЕЗОПАСНАЯ МЫШЬ) [>=3 пальцев]
            # ---------------------------------------------------------
            if total >= 3:
                # Двигаем центром ладони. КЛИКИ ЗАПРЕЩЕНЫ.
                self.move_mouse(palm_pt.x, palm_pt.y)
                return

            # ---------------------------------------------------------
            # 4. ☝️ ЖЕСТ: УКАЗАТЕЛЬНЫЙ (СНАЙПЕР + КЛИК) [1 палец]
            # ---------------------------------------------------------
            if total == 1:
                # Двигаем кончиком пальца
                self.move_mouse(idx_pt.x, idx_pt.y)

                # Проверка щипка (Клик)
                dist = np.hypot(idx_pt.x - thm_pt.x, idx_pt.y - thm_pt.y)
                if dist < CLICK_DIST:
                    if time.time() - self.last_click > 0.4:
                        pyautogui.click()
                        logger.info("🖱 CLICK")
                        self.last_click = time.time()
                return

# ================= 🚀 ЗАПУСК =================
def main():
    logger.info("🚀 VECTOR GESTURE SYSTEM: FULL CONTROL")
    cam = AdaptiveStream(src=CAMERA_ID).start()
    brain = VectorBrain()
    time.sleep(1)

    try:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
            brain.process(frame)
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    main()