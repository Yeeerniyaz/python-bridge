import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys

# ================= ⚙️ НАСТРОЙКИ (GOD MODE) =================
# Камера
CAMERA_ID = 0
PROCESS_W, PROCESS_H = 320, 240  # Оптимизация для RPi
CAM_W, CAM_H = 640, 480          # Запрос к железу

# Зона управления (Квадрат перед камерой)
MARGIN_X = 60
MARGIN_Y = 50

# Сглаживание мыши
SMOOTH_FACTOR = 0.2  # 0.1 = Плавно (вязко), 0.3 = Быстро

# Настройки КЛИКА и ЗАМОРОЗКИ
# Логика: Когда пальцы сближаются ближе FREEZE_DIST, курсор ОСТАНАВЛИВАЕТСЯ.
# Ты спокойно дожимаешь до CLICK_DIST, и происходит клик.
FREEZE_DIST = 0.07   # Дистанция начала "заморозки" курсора
CLICK_DIST = 0.035   # Дистанция самого клика (щипок)

# Настройки жестов
NAV_THRESHOLD = 0.06 # Чувствительность свайпов
ESC_HOLD_TIME = 1.5  # Сколько держать кулак для ESC

# PyAutoGUI
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.005

# Логи
logging.basicConfig(level=logging.INFO, format='%(asctime)s | VECTOR | %(message)s')
logger = logging.getLogger("VECTOR_SNIPER")

# ================= 🏎 КАМЕРА (БЕЗ ЛАГОВ) =================
class CameraEngine:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
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
            time.sleep(0.005)

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# ================= 🧠 МОЗГ (СНАЙПЕРСКИЙ РЕЖИМ) =================
class VectorCore:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # Lite для скорости
            min_detection_confidence=0.6, # Чуть строже для точности
            min_tracking_confidence=0.6
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # Координаты
        self.prev_x, self.prev_y = 0, 0
        self.curr_x, self.curr_y = 0, 0
        
        # Таймеры
        self.timer_click = 0
        self.timer_fist = 0
        self.timer_nav = 0
        self.nav_anchor = None 

    def move_cursor(self, raw_x, raw_y):
        # Маппинг координат (из зоны камеры в экран)
        x = np.interp(raw_x * PROCESS_W, (MARGIN_X, PROCESS_W - MARGIN_X), (0, self.scr_w))
        y = np.interp(raw_y * PROCESS_H, (MARGIN_Y, PROCESS_H - MARGIN_Y), (0, self.scr_h))

        # Ограничение
        x = np.clip(x, 0, self.scr_w)
        y = np.clip(y, 0, self.scr_h)

        # Сглаживание
        self.curr_x = self.prev_x + (x - self.prev_x) * SMOOTH_FACTOR
        self.curr_y = self.prev_y + (y - self.prev_y) * SMOOTH_FACTOR
        
        pyautogui.moveTo(self.curr_x, self.curr_y)
        self.prev_x, self.prev_y = self.curr_x, self.curr_y

    def process(self, frame):
        # Подготовка кадра
        small = cv2.resize(frame, (PROCESS_W, PROCESS_H))
        small = cv2.flip(small, 1)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        
        results = self.hands.process(rgb)
        
        if not results.multi_hand_landmarks:
            self.nav_anchor = None
            return

        for hand in results.multi_hand_landmarks:
            lms = hand.landmark
            
            # Точки пальцев
            idx_pt = lms[8]  # Указательный
            thm_pt = lms[4]  # Большой
            palm_pt = lms[9] # Ладонь

            # Считаем поднятые пальцы
            # (Палец поднят, если кончик выше сустава)
            fingers = [
                1 if lms[8].y < lms[6].y else 0,   # Index
                1 if lms[12].y < lms[10].y else 0, # Middle
                1 if lms[16].y < lms[14].y else 0, # Ring
                1 if lms[20].y < lms[18].y else 0  # Pinky
            ]
            count = sum(fingers)
            now = time.time()

            # --- ЛОГИКА ЖЕСТОВ ---

            # 1. 🛑 КУЛАК (ESC) -> 0 пальцев
            if count == 0:
                self.nav_anchor = None
                if self.timer_fist == 0: self.timer_fist = now
                elif now - self.timer_fist > ESC_HOLD_TIME:
                    pyautogui.press('esc')
                    logger.info("🔐 ВЫХОД (ESC)")
                    self.timer_fist = 0
                return

            self.timer_fist = 0 # Сброс

            # 2. 🤫 "Я ЗАНЯТ" (ИГНОР) -> 3, 4, 5 пальцев
            # Если рука просто открыта или машет - мышь НЕ двигается.
            if count >= 3:
                self.nav_anchor = None
                # logger.info("💤 Игнор (Рука занята)") 
                return

            # 3. ✌️ НАВИГАЦИЯ (ДВА ПАЛЬЦА) -> Индекс + Средний
            if fingers[0] and fingers[1] and not fingers[2]:
                pos = np.array([palm_pt.x, palm_pt.y])
                
                if self.nav_anchor is None:
                    self.nav_anchor = pos
                    logger.info("🕹 НАВИГАЦИЯ АКТИВНА")
                    return

                # Считаем сдвиг
                diff = pos - self.nav_anchor
                dx, dy = diff[0], diff[1]

                if now - self.timer_nav > 0.6: # Кулдаун
                    # Блокировка осей (чтобы не путать)
                    if abs(dx) > abs(dy): # Горизонтально
                        if abs(dx) > NAV_THRESHOLD:
                            k = 'right' if dx > 0 else 'left'
                            pyautogui.press(k)
                            logger.info(f"➡️ СВАЙП: {k.upper()}")
                            self.timer_nav = now
                            self.nav_anchor = pos
                    else: # Вертикально
                        if abs(dy) > NAV_THRESHOLD:
                            k = 'down' if dy > 0 else 'up'
                            pyautogui.press(k)
                            logger.info(f"⬇️ СВАЙП: {k.upper()}")
                            self.timer_nav = now
                            self.nav_anchor = pos
                return
            
            self.nav_anchor = None

            # 4. ☝️ УКАЗАТЕЛЬНЫЙ (МЫШЬ + КЛИК) -> 1 палец
            if count == 1 or count == 2: # Иногда большой палец торчит, это ок
                # Считаем дистанцию для клика (Указательный <-> Большой)
                dist = np.hypot(idx_pt.x - thm_pt.x, idx_pt.y - thm_pt.y)

                # === ФИШКА: ЗАМОРОЗКА ПРИЦЕЛА ===
                if dist < FREEZE_DIST:
                    # Мы "входим" в зону клика. Курсор СТОИТ НА МЕСТЕ.
                    # Это позволяет точно нажать, не сдвинув мышь.
                    
                    if dist < CLICK_DIST: # Дожали до клика
                        if now - self.timer_click > 0.4:
                            pyautogui.click()
                            logger.info("🖱 КЛИК!")
                            self.timer_click = now
                    
                    # Если просто близко, но не клик - ничего не делаем (курсор заморожен)
                
                else:
                    # Дистанция большая - обычное движение
                    self.move_cursor(idx_pt.x, idx_pt.y)
                
                return

# ================= 🚀 ЗАПУСК =================
def main():
    logger.info("🚀 VECTOR SNIPER MODE STARTED")
    logger.info("☝️ 1 палец: Мышь (Замирает перед кликом!)")
    logger.info("✌️ 2 пальца: Свайпы")
    logger.info("🖐 Ладонь: ИГНОР (защита от случайных движений)")

    cam = CameraEngine(src=CAMERA_ID).start()
    brain = VectorCore()
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