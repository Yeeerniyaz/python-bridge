#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VECTOR GESTURE CONTROL - DUAL MODE (v9.0)
=========================================
Режимы:
1. COMPUTER (Оранжевый): Курсор + Щипок (Клик)
2. CINEMA (Синий): Взмахи (Листать) + Кулак (Enter)
3. GLOBAL: Громкость (справа), Пауза (Ладонь), Выход (Шака)
"""

import cv2
import mediapipe as mp
import pyautogui
import math
import time
import numpy as np
import urllib.request
import json
import threading
import logging

# --- КОНФИГУРАЦИЯ ---
CAMERA_ID = 0
WIDTH, HEIGHT = 640, 480
BRIDGE_URL = "http://localhost:5005"  # Адрес твоего bridge.py

# Чувствительность
CLICK_DIST = 0.045     # Расстояние для клика (щипок)
SWIPE_THRESH = 60      # Пикселей для фиксации взмаха
VOL_EDGE_X = 0.92      # Зона громкости (92% ширины экрана и правее)
MODE_HOLD_TIME = 1.5   # Сколько держать лайк для смены режима

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger("VECTOR")

pyautogui.FAILSAFE = False

class VectorLED:
    """Отправляет команды на bridge.py без задержки видео"""
    @staticmethod
    def send(endpoint, data):
        def _req():
            try:
                url = f"{BRIDGE_URL}{endpoint}"
                req = urllib.request.Request(url, 
                    data=json.dumps(data).encode('utf-8'), 
                    headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=0.1)
            except:
                pass # Если бридж не отвечает, не вешаем систему
        threading.Thread(target=_req, daemon=True).start()

    @staticmethod
    def blink(color_rgb):
        # Отправляем цвет и через секунду возвращаем статику (опционально)
        VectorLED.send('/led/color', {'color': color_rgb})

class GestureMode:
    COMPUTER = "COMPUTER"  # Оранжевый
    CINEMA = "CINEMA"      # Синий

class VectorBrain:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.scr_w, self.scr_h = pyautogui.size()
        
        # Состояние
        self.mode = GestureMode.COMPUTER
        self.is_dragging = False
        self.prev_x, self.prev_y = 0, 0 # Для сглаживания курсора
        
        # Таймеры и флаги
        self.mode_timer = 0
        self.swipe_cooldown = 0
        self.last_vol_y = 0
        self.vol_active = False

    def get_fingers(self, lms):
        """Возвращает список [1,0,0,0,0] - какие пальцы подняты"""
        # Порядок: Большой, Указ, Средний, Безым, Мизинец
        tips = [4, 8, 12, 16, 20]
        fingers = []
        
        # Большой палец (проверка по X для правой руки, упрощенно)
        if lms[4].x < lms[3].x: fingers.append(1)
        else: fingers.append(0)
        
        # Остальные (проверка по Y, так как верх экрана это 0)
        for id in tips[1:]:
            if lms[id].y < lms[id-2].y: fingers.append(1)
            else: fingers.append(0)
        return fingers

    def get_dist(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def process_frame(self, frame):
        # Подготовка
        frame = cv2.flip(frame, 1)
        h, w, c = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.hands.process(rgb)

        if not res.multi_hand_landmarks:
            return frame

        lms = res.multi_hand_landmarks[0].landmark
        fingers = self.get_fingers(lms)
        
        # Координаты ключевых точек
        idx_x, idx_y = int(lms[8].x * w), int(lms[8].y * h) # Кончик указательного
        thumb_tip = lms[4]
        index_tip = lms[8]
        
        # ==========================================
        # 1. ГЛОБАЛЬНЫЕ ЖЕСТЫ (Приоритет №1)
        # ==========================================
        
        # A. Смена режима (👍 ЛАЙК)
        # Условие: Большой палец поднят, остальные (кроме может быть указательного) сжаты? 
        # Проще: Большой палец оттопырен, а мизинец и безымянный точно прижаты
        is_like = fingers[0] == 1 and fingers[3] == 0 and fingers[4] == 0
        
        if is_like:
            if self.mode_timer == 0: self.mode_timer = time.time()
            elif time.time() - self.mode_timer > MODE_HOLD_TIME:
                # ПЕРЕКЛЮЧЕНИЕ
                if self.mode == GestureMode.COMPUTER:
                    self.mode = GestureMode.CINEMA
                    logger.info("🔵 MODE: CINEMA")
                    VectorLED.blink([0, 0, 255]) # Синий
                else:
                    self.mode = GestureMode.COMPUTER
                    logger.info("🟠 MODE: COMPUTER")
                    VectorLED.blink([255, 100, 0]) # Оранжевый
                self.mode_timer = 0 # Сброс
                time.sleep(1) # Задержка чтобы не мигало
                return frame
        else:
            self.mode_timer = 0

        # B. Громкость (Слайдер справа)
        # Если указательный палец в зоне 92% ширины
        if lms[8].x > VOL_EDGE_X:
            current_y = lms[8].y
            if not self.vol_active:
                self.vol_active = True
                self.last_vol_y = current_y
                logger.info("🔊 VOL: Active")
            else:
                diff = self.last_vol_y - current_y # Вверх (+), Вниз (-)
                if abs(diff) > 0.05: # Шаг чувствительности
                    if diff > 0: pyautogui.press('volumeup')
                    else: pyautogui.press('volumedown')
                    self.last_vol_y = current_y
            return frame # Выходим, чтобы не двигать курсор
        else:
            self.vol_active = False

        # C. Пауза (🖐️ ЛАДОНЬ)
        if sum(fingers) == 5:
             if time.time() - self.swipe_cooldown > 1.0:
                 pyautogui.press('space')
                 logger.info("🖐️ PAUSE/PLAY")
                 VectorLED.blink([255, 255, 255]) # Белый
                 self.swipe_cooldown = time.time()
             return frame

        # D. Выход / Назад (🤙 ШАКА)
        # Большой и мизинец подняты, середина прижата
        if fingers[0] == 1 and fingers[4] == 1 and fingers[2] == 0:
             if time.time() - self.swipe_cooldown > 2.0:
                 pyautogui.press('esc')
                 logger.info("🤙 ESCAPE")
                 VectorLED.blink([255, 0, 0]) # Красный миг
                 self.swipe_cooldown = time.time()
             return frame

        # ==========================================
        # 2. РЕЖИМ КОМПЬЮТЕР (Точность)
        # ==========================================
        if self.mode == GestureMode.COMPUTER:
            # Движение курсора (только если поднят указательный)
            if fingers[1] == 1:
                # Интерполяция координат (экранные)
                # Делаем зону чуть меньше (Margin), чтобы доставать до краев
                margin = 50
                scr_x = np.interp(idx_x, [margin, w-margin], [0, self.scr_w])
                scr_y = np.interp(idx_y, [margin, h-margin], [0, self.scr_h])
                
                # Сглаживание (Smoothing)
                curr_x = self.prev_x + (scr_x - self.prev_x) * 0.2
                curr_y = self.prev_y + (scr_y - self.prev_y) * 0.2
                
                pyautogui.moveTo(curr_x, curr_y)
                self.prev_x, self.prev_y = curr_x, curr_y

                # Клик (Щипок)
                dist = self.get_dist(thumb_tip, index_tip)
                if dist < CLICK_DIST:
                    if not self.is_dragging:
                        pyautogui.mouseDown()
                        self.is_dragging = True
                        VectorLED.blink([0, 255, 0]) # Зеленый
                        logger.info("👌 CLICK DOWN")
                else:
                    if self.is_dragging:
                        pyautogui.mouseUp()
                        self.is_dragging = False
                        logger.info("👌 CLICK UP")

        # ==========================================
        # 3. РЕЖИМ КИНОТЕАТР (YouTube)
        # ==========================================
        elif self.mode == GestureMode.CINEMA:
            # ENTER (Кулак ✊)
            if sum(fingers) == 0: # Все пальцы сжаты
                if time.time() - self.swipe_cooldown > 1.5:
                    pyautogui.press('enter')
                    logger.info("✊ ENTER")
                    VectorLED.blink([0, 255, 0]) # Зеленый
                    self.swipe_cooldown = time.time()
            
            # СВАЙПЫ (Листание)
            # Отслеживаем движение центра ладони (9 точка)
            cx, cy = int(lms[9].x * w), int(lms[9].y * h)
            
            # Для определения свайпа нам нужна история позиций.
            # Но в простом варианте можно использовать скорость указательного пальца
            # Или просто использовать относительное смещение курсора (виртуального)
            
            # Простая реализация: 
            # Если рука быстро сместилась относительно предыдущего кадра (который мы не храним в классе явно для свайпа, 
            # но можем использовать prev_x из режима компьютера как "последнюю известную точку")
            
            # Лучше использовать статический буфер внутри функции или класса
            if not hasattr(self, 'last_sw_x'): 
                self.last_sw_x = cx
                self.last_sw_y = cy
                self.last_sw_time = time.time()

            # Вычисляем дельту
            dx = cx - self.last_sw_x
            dy = cy - self.last_sw_y
            
            if time.time() - self.swipe_cooldown > 0.6: # Кулдаун между свайпами
                if abs(dx) > SWIPE_THRESH:
                    if dx > 0: 
                        pyautogui.press('right') # Вправо (для YouTube это +5 сек или след видео в фокусе)
                        logger.info("➡️ SWIPE RIGHT")
                    else: 
                        pyautogui.press('left')
                        logger.info("⬅️ SWIPE LEFT")
                    self.swipe_cooldown = time.time()
                    
                elif abs(dy) > SWIPE_THRESH:
                    if dy > 0: 
                        pyautogui.press('down')
                        logger.info("⬇️ SWIPE DOWN")
                    else: 
                        pyautogui.press('up')
                        logger.info("⬆️ SWIPE UP")
                    self.swipe_cooldown = time.time()

            # Обновляем "предыдущую" точку
            self.last_sw_x = cx
            self.last_sw_y = cy

        return frame

def main():
    cap = cv2.VideoCapture(CAMERA_ID)
    cap.set(3, WIDTH)
    cap.set(4, HEIGHT)
    
    brain = VectorBrain()
    
    print(f"--- VECTOR GESTURE CONTROL v9.0 STARTED ---")
    print(f"Mode Default: COMPUTER (Use 👍 to switch)")

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # Обработка
            frame = brain.process_frame(frame)
            
            # Отрисовка (Опционально, для тестов. В проде можно убрать imshow)
            # cv2.imshow('Vector Vision', frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()