import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys

# ================= ⚙️ НАСТРОЙКИ (TWEAK ME) =================
CAMERA_ID = 0
FRAME_WIDTH = 320    # Низкое разрешение для скорости RPi (не меняй)
FRAME_HEIGHT = 240

# Зона комфорта (чем меньше число, тем меньше махать рукой)
# 100 = отступ от краев кадра. Мышь будет работать только в центре.
FRAME_REDUCTION = 60 

# Настройки клика и скролла
CLICK_THRESHOLD = 0.035  # Чувствительность щипка (меньше = сложнее кликнуть)
SCROLL_SENSITIVITY = 15  # Скорость скролла

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

# Отключаем защиту PyAutoGUI (чтобы мышь могла биться в углы)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.005 # Минимальная задержка

# ================= 🏎 КАМЕРА В ПОТОКЕ (NO LAG) =================
class FastWebcam:
    def __init__(self, src=0, w=320, h=240):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        self.stream.set(cv2.CAP_PROP_FPS, 30)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self.update, args=(), daemon=True)
        t.start()
        return self

    def update(self):
        while not self.stopped:
            grabbed, frame = self.stream.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.005) # Даем дышать CPU

    def read(self):
        with self.lock:
            return self.frame.copy() if self.grabbed else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# ================= 🧠 МОЗГ ЖЕСТОВ =================
class VectorBrain:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # 0 = Lite (Быстро!), 1 = Full (Точно)
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # Координаты для сглаживания
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        
        # Таймеры
        self.last_click = 0
        self.last_esc = 0

    def smooth_move(self, target_x, target_y, speed_factor):
        """Динамическое сглаживание: быстро двигаешь - мало лага, медленно - высокая точность"""
        # Вычисляем расстояние
        dist = np.hypot(target_x - self.plocX, target_y - self.plocY)
        
        # Если движение быстрое (>50 пикселей), уменьшаем сглаживание (быстрая реакция)
        # Если движение медленное, увеличиваем сглаживание (стабильность)
        if dist > 50:
            alpha = 0.7  # Быстро
        elif dist > 20:
            alpha = 0.4  # Средне
        else:
            alpha = 0.15 # Очень плавно (прицеливание)

        self.clocX = self.plocX + (target_x - self.plocX) * alpha
        self.clocY = self.plocY + (target_y - self.plocY) * alpha
        
        # Ограничиваем экраном
        self.clocX = np.clip(self.clocX, 0, self.scr_w)
        self.clocY = np.clip(self.clocY, 0, self.scr_h)
        
        pyautogui.moveTo(self.clocX, self.clocY)
        self.plocX, self.plocY = self.clocX, self.clocY

    def process(self, frame):
        # Отражаем зеркально (чтобы право было правом)
        frame = cv2.flip(frame, 1)
        h, w, c = frame.shape
        
        # Отрисовка "Зоны комфорта" (для отладки можно включить imshow, но на RPi не увидишь)
        # cv2.rectangle(frame, (FRAME_REDUCTION, FRAME_REDUCTION), 
        #               (w - FRAME_REDUCTION, h - FRAME_REDUCTION), (255, 0, 255), 2)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        status = "IDLE"

        if results.multi_hand_landmarks:
            for hand_lms in results.multi_hand_landmarks:
                # Точки
                idx_tip = hand_lms.landmark[8]   # Указательный
                mid_tip = hand_lms.landmark[12]  # Средний
                thumb_tip = hand_lms.landmark[4] # Большой
                wrist = hand_lms.landmark[0]     # Запястье
                
                # Координаты кончика указательного пальца (0.0 - 1.0)
                x1, y1 = idx_tip.x, idx_tip.y
                
                # Проверка пальцев (поднят или нет)
                # Если кончик пальца выше сустава (y меньше, т.к. 0 вверху)
                idx_up = idx_tip.y < hand_lms.landmark[6].y
                mid_up = mid_tip.y < hand_lms.landmark[10].y
                ring_down = hand_lms.landmark[16].y > hand_lms.landmark[14].y
                pinky_down = hand_lms.landmark[20].y > hand_lms.landmark[18].y
                
                # 1. 🛑 ЖЕСТ: КУЛАК (ESC)
                # Все пальцы согнуты
                if not idx_up and not mid_up and ring_down and pinky_down:
                    if time.time() - self.last_esc > 2.0: # Раз в 2 секунды
                        pyautogui.press('esc')
                        self.last_esc = time.time()
                        logger.info("🔐 ESCAPE PRESSED")
                    return "FIST (ESC)"

                # 2. ↕️ ЖЕСТ: ДВА ПАЛЬЦА (СКРОЛЛ / СТРЕЛКИ)
                # Указательный и Средний подняты (Victory sign)
                if idx_up and mid_up and ring_down:
                    # Конвертируем координаты в скролл
                    # Используем относительное положение пальцев в кадре
                    # Центр кадра = покой. Выше центра = скролл вверх.
                    
                    dy = y1 - 0.5 # Отклонение от центра по Y
                    dx = x1 - 0.5 # Отклонение от центра по X
                    
                    if abs(dy) > 0.1: # Мертвая зона
                        scroll_amount = int(dy * SCROLL_SENSITIVITY * -10) # -10 инверсия
                        # Скролл вертикальный
                        pyautogui.scroll(scroll_amount)
                        status = "SCROLL V"
                    
                    if abs(dx) > 0.15: # Для горизонтальных стрелок (влево/вправо)
                         if time.time() - self.last_click > 0.3:
                            if dx > 0: pyautogui.press('right')
                            else: pyautogui.press('left')
                            self.last_click = time.time()
                            status = "SWIPE H"
                    
                    return status

                # 3. 🖱 ЖЕСТ: УКАЗАТЕЛЬНЫЙ (МЫШЬ)
                # Только указательный поднят (или указательный+большой)
                if idx_up and not mid_up:
                    # Преобразование координат с учетом "Зоны комфорта"
                    # Interpolate: from (Reduction, W-Reduction) to (0, ScreenW)
                    mapped_x = np.interp(x1 * w, (FRAME_REDUCTION, w - FRAME_REDUCTION), (0, self.scr_w))
                    mapped_y = np.interp(y1 * h, (FRAME_REDUCTION, h - FRAME_REDUCTION), (0, self.scr_h))

                    # Двигаем мышь (с динамическим сглаживанием)
                    self.smooth_move(mapped_x, mapped_y, 0)

                    # 4. 🤏 ЖЕСТ: КЛИК (ЩИПОК)
                    # Расстояние между большим и указательным
                    dist = np.hypot(idx_tip.x - thumb_tip.x, idx_tip.y - thumb_tip.y)
                    
                    if dist < CLICK_THRESHOLD:
                        if time.time() - self.last_click > 0.3: # Анти-дребезг
                            pyautogui.click()
                            self.last_click = time.time()
                            logger.info("🖱 CLICK")
                            return "CLICK"
                    
                    return "CURSOR"

        return status

# ================= 🚀 ЗАПУСК =================
def main():
    logger.info("🚀 VECTOR GESTURE PRO STARTED")
    cam = FastWebcam(src=CAMERA_ID, w=FRAME_WIDTH, h=FRAME_HEIGHT).start()
    brain = VectorBrain()
    
    # Ждем прогрева камеры
    time.sleep(1)

    try:
        while True:
            frame = cam.read()
            if frame is None: continue
            
            brain.process(frame)
            
            # Небольшой sleep не нужен, так как FastWebcam регулирует FPS, 
            # но для разгрузки CPU на 100% загрузке добавим мизер
            # time.sleep(0.001) 

    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        logger.info("🛑 STOPPED")

# Обработчик убийства процесса (для systemd)
def signal_handler(sig, frame):
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()