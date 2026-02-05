import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import threading
import logging
import signal
import sys

# ================= ⚙️ БАПТАУЛАР (PRO SETTINGS) =================

# 📷 Камера параметрлері
CAMERA_ID = 0
REQ_W, REQ_H = 640, 480     # Камерадан сұраймыз (Hardware)
FRAME_W, FRAME_H = 320, 240 # Өңдеу үшін кішірейтеміз (RPi Speed)

# 🖐 Сезімталдық шектері
CLICK_DIST = 0.040      # Клик үшін қашықтық (шымшу)
NAV_THRESH = 0.06       # Стрелкалар үшін қанша жылжыту керек
NAV_COOLDOWN = 0.6      # Стрелкалар арасындағы кідіріс (сек)
ESC_TIME = 3.0          # ESC басу уақыты (сек)

# 🖱 Курсор физикасы
MARGIN_X = 50           # Экран шетіндегі өлі аймақ
MARGIN_Y = 40
SMOOTHING = 0.15        # 0.1 (Жұмсақ) - 0.5 (Өткір)

# Логирование (Кәсіби формат)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | VECTOR | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VECTOR_PRO")

# PyAutoGUI баптаулары
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.002

# ================= 🛡 КАМЕРА МОДУЛІ (UNKILLABLE) =================
class CameraStream:
    """
    Камераны бөлек потокта оқиды.
    Егер камера үзіліп кетсе (сым тиіп кетсе), бағдарлама құламайды,
    қайта қосылғанша күтеді (Auto-Reconnect).
    """
    def __init__(self, src=0):
        self.src = src
        self.stream = None
        self.frame = None
        self.grabbed = False
        self.stopped = False
        self.lock = threading.Lock()
        self.connect()

    def connect(self):
        """Камераға қосылу әрекеті"""
        try:
            if self.stream: self.stream.release()
            self.stream = cv2.VideoCapture(self.src)
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, REQ_W)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, REQ_H)
            self.stream.set(cv2.CAP_PROP_FPS, 30)
            
            self.grabbed, self.frame = self.stream.read()
            if self.grabbed:
                logger.info("✅ Камера сәтті қосылды")
            else:
                logger.warning("⚠️ Камера кадр бермей тұр")
        except Exception as e:
            logger.error(f"❌ Камера қатесі: {e}")

    def start(self):
        threading.Thread(target=self._update, args=(), daemon=True).start()
        return self

    def _update(self):
        while not self.stopped:
            # Егер камера ажырап кетсе, қайта қосуға тырысамыз
            if not self.stream or not self.stream.isOpened():
                logger.warning("🔄 Камера ізделуде...")
                time.sleep(2)
                self.connect()
                continue

            try:
                grabbed, frame = self.stream.read()
                with self.lock:
                    if grabbed:
                        self.grabbed = grabbed
                        self.frame = frame
                    else:
                        self.grabbed = False
                time.sleep(0.005) # CPU-ды қыздырмау үшін микро-үзіліс
            except Exception as e:
                logger.error(f"💥 Потоктағы қате: {e}")
                time.sleep(1)

    def read(self):
        with self.lock:
            return self.frame.copy() if (self.grabbed and self.frame is not None) else None

    def stop(self):
        self.stopped = True
        if self.stream: self.stream.release()

# ================= 🧠 ЖЕСТТЕР МИЫ (CORE LOGIC) =================
class GestureBrain:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0, # RPi үшін ең жеңілі
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # Координаталар (Smooth Movement)
        self.curr_x, self.curr_y = 0.0, 0.0
        self.prev_x, self.prev_y = 0.0, 0.0
        
        # Таймерлер мен Жағдайлар
        self.fist_start = 0
        self.last_click = 0
        self.last_nav = 0
        self.nav_anchor = None # Навигация басталатын нүкте

    def _smooth_move(self, raw_x, raw_y):
        """Координаталарды түрлендіру және жұмсарту"""
        # Интерполяция (Кішкентай кадрдан -> Үлкен экранға)
        x = np.interp(raw_x * FRAME_W, (MARGIN_X, FRAME_W - MARGIN_X), (0, self.scr_w))
        y = np.interp(raw_y * FRAME_H, (MARGIN_Y, FRAME_H - MARGIN_Y), (0, self.scr_h))

        # Шектен шығармау
        x = np.clip(x, 0, self.scr_w)
        y = np.clip(y, 0, self.scr_h)

        # Exponential Moving Average (EMA) формуласы
        self.curr_x = self.prev_x + (x - self.prev_x) * SMOOTHING
        self.curr_y = self.prev_y + (y - self.prev_y) * SMOOTHING
        
        pyautogui.moveTo(self.curr_x, self.curr_y)
        self.prev_x, self.prev_y = self.curr_x, self.curr_y

    def process(self, frame):
        try:
            # Кадрды дайындау
            small = cv2.resize(frame, (FRAME_W, FRAME_H))
            small = cv2.flip(small, 1) # Айнадағыдай ету
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            
            results = self.hands.process(rgb)
            
            if not results.multi_hand_landmarks:
                self.nav_anchor = None
                self.fist_start = 0
                return

            for hand in results.multi_hand_landmarks:
                lms = hand.landmark
                
                # Саусақтарды анықтау [Сұқ, Орта, Атыжоқ, Шынашақ]
                fingers = [
                    1 if lms[8].y < lms[6].y else 0,
                    1 if lms[12].y < lms[10].y else 0,
                    1 if lms[16].y < lms[14].y else 0,
                    1 if lms[20].y < lms[18].y else 0
                ]
                up_count = sum(fingers)
                now = time.time()

                # --- 1. 👊 ЖҰДЫРЫҚ (ESC - 3 секунд) ---
                if up_count == 0:
                    self.nav_anchor = None
                    if self.fist_start == 0: self.fist_start = now
                    elif now - self.fist_start > ESC_TIME:
                        pyautogui.press('esc')
                        logger.info("🔐 ЖҮЙЕ: ESC БАСЫЛДЫ")
                        self.fist_start = 0
                    return
                self.fist_start = 0

                # --- 2. ✌️ НАВИГАЦИЯ (2 САУСАҚ) ---
                # Тек Сұқ және Ортаңғы саусақ тұрса
                if fingers[0] and fingers[1] and not fingers[2] and not fingers[3]:
                    # Алақан ортасы
                    curr_pos = np.array([lms[9].x, lms[9].y])
                    
                    if self.nav_anchor is None:
                        self.nav_anchor = curr_pos
                        logger.info("🕹 NAV: ҚОСЫЛДЫ (СЕРМЕУДІ КҮТУДЕ)")
                        return

                    delta = curr_pos - self.nav_anchor
                    dx, dy = delta[0], delta[1]

                    if now - self.last_nav > NAV_COOLDOWN:
                        # Қай ось бойынша қозғалыс көп? (Axis Locking)
                        if abs(dx) > abs(dy): # Горизонталь
                            if abs(dx) > NAV_THRESH:
                                key = 'right' if dx > 0 else 'left'
                                pyautogui.press(key)
                                logger.info(f"➡️ СВАЙП: {key.upper()}")
                                self.last_nav = now
                                self.nav_anchor = curr_pos
                        else: # Вертикаль
                            if abs(dy) > NAV_THRESH:
                                key = 'down' if dy > 0 else 'up'
                                pyautogui.press(key)
                                logger.info(f"⬇️ СВАЙП: {key.upper()}")
                                self.last_nav = now
                                self.nav_anchor = curr_pos
                    return
                
                self.nav_anchor = None

                # --- 3. 🖐 АЛАҚАН (ҚАУІПСІЗ ЖҮРУ) - 3+ САУСАҚ ---
                if up_count >= 3:
                    # Алақан ортасымен жүреміз (lms[9])
                    self._smooth_move(lms[9].x, lms[9].y)
                    return

                # --- 4. ☝️ СҰҚ САУСАҚ (КЛИК) - 1 САУСАҚ ---
                if up_count == 1 or (up_count == 2 and not fingers[1]):
                    # Сұқ саусақ ұшымен жүреміз (lms[8])
                    idx_pt = lms[8]
                    thm_pt = lms[4]

                    self._smooth_move(idx_pt.x, idx_pt.y)
                    
                    # Клик: Бас бармақ пен Сұқ саусақ жақындаса
                    dist = np.hypot(idx_pt.x - thm_pt.x, idx_pt.y - thm_pt.y)
                    
                    if dist < CLICK_DIST:
                        if now - self.last_click > 0.4: # Анти-дребезг
                            pyautogui.click()
                            logger.info("🖱 ТЫШҚАН: КЛИК")
                            self.last_click = now
                    return

        except Exception as e:
            logger.error(f"⚠️ Өңдеу қатесі: {e}")

# ================= 🚀 БАСТАУ (MAIN) =================
def main():
    logger.info("========================================")
    logger.info("🚀 VECTOR GESTURE SYSTEM: PROFESSIONAL")
    logger.info("========================================")
    
    cam = CameraStream(src=CAMERA_ID).start()
    brain = GestureBrain()
    
    time.sleep(1.0) # Камераның оянуын күту

    try:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.1)
                continue
            
            brain.process(frame)

    except KeyboardInterrupt:
        logger.info("🛑 Қолданушы тоқтатты.")
    except Exception as e:
        logger.critical(f"🔥 КРИТИКАЛЫҚ ҚАТЕ: {e}")
    finally:
        cam.stop()
        sys.exit(0)

# Systemd сигналдарын ұстау
if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    main()