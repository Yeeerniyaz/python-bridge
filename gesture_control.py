import cv2
import mediapipe as mp
import pyautogui
import asyncio
import logging
import signal
import sys
import os

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VECTOR_GESTURE")

class VectorGestureMouse:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        # Настройки экрана
        self.screen_w, self.screen_h = pyautogui.size()
        self.cap = None
        self.running = True
        
        # Сглаживание (чтобы курсор не дрожал на зеркале)
        self.smoothening = 5
        self.plocX, self.plocY = 0, 0
        
        pyautogui.FAILSAFE = False

    async def start(self):
        logger.info("🚀 Запуск системы жестов VECTOR...")
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        try:
            while self.running:
                success, img = self.cap.read()
                if not success:
                    await asyncio.sleep(1)
                    continue

                img = cv2.flip(img, 1)
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                results = self.hands.process(rgb_img)

                if results.multi_hand_landmarks:
                    for hand_lms in results.multi_hand_landmarks:
                        # Указательный палец (Index Tip)
                        index_tip = hand_lms.landmark[8]
                        # Большой палец (Thumb Tip)
                        thumb_tip = hand_lms.landmark[4]

                        # Масштабирование
                        fx = int(index_tip.x * self.screen_w)
                        fy = int(index_tip.y * self.screen_h)

                        # Плавное движение
                        clocX = self.plocX + (fx - self.plocX) / self.smoothening
                        clocY = self.plocY + (fy - self.plocY) / self.smoothening
                        
                        pyautogui.moveTo(clocX, clocY, _pause=False)
                        self.plocX, self.plocY = clocX, clocY

                        # Клик при соединении большого и указательного пальцев
                        dist = ((index_tip.x - thumb_tip.x)**2 + (index_tip.y - thumb_tip.y)**2)**0.5
                        if dist < 0.05:
                            pyautogui.click()
                            logger.info("🖱 Жест: Клик!")
                            await asyncio.sleep(0.3) 

                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"💥 Ошибка: {e}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.cap: self.cap.release()
        logger.info("🛑 Система жестов остановлена")

if __name__ == "__main__":
    controller = VectorGestureMouse()
    
    def shutdown(sig, frame):
        controller.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    asyncio.run(controller.start())