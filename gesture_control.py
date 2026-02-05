import cv2
import mediapipe as mp
import pyautogui
import asyncio
import logging
import signal
import sys

# Настройка логирования в стиле VECTOR
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
        self.screen_w, self.screen_h = pyautogui.size()
        self.cap = None
        self.running = True
        
        # Настройки чувствительности
        self.smoothening = 7
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        
        pyautogui.FAILSAFE = False

    async def start(self):
        logger.info("🚀 Starting Gesture Control System...")
        self.cap = cv2.VideoCapture(0)
        
        # Оптимизация для Raspberry Pi (низкое разрешение = высокая скорость)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        try:
            while self.running:
                success, img = self.cap.read()
                if not success:
                    logger.error("❌ Camera Frame Error")
                    await asyncio.sleep(1)
                    continue

                img = cv2.flip(img, 1)
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                results = self.hands.process(rgb_img)

                if results.multi_hand_landmarks:
                    for hand_lms in results.multi_hand_landmarks:
                        # Указательный палец (Index Finger Tip)
                        index_finger = hand_lms.landmark[8]
                        # Большой палец (Thumb Tip)
                        thumb_finger = hand_lms.landmark[4]

                        # Координаты на экране
                        fx = int(index_finger.x * self.screen_w)
                        fy = int(index_finger.y * self.screen_h)

                        # Сглаживание движения (чтобы курсор не дрожал)
                        self.clocX = self.plocX + (fx - self.plocX) / self.smoothening
                        self.clocY = self.plocY + (fy - self.plocY) / self.smoothening
                        
                        pyautogui.moveTo(self.clocX, self.clocY, _pause=False)
                        self.plocX, self.plocY = self.clocX, self.clocY

                        # Логика клика (расстояние между 4 и 8 пальцами)
                        dist = ((index_finger.x - thumb_finger.x)**2 + (index_finger.y - thumb_finger.y)**2)**0.5
                        if dist < 0.05:
                            pyautogui.click()
                            logger.info("🖱 Gesture Click!")
                            await asyncio.sleep(0.2) # Защита от двойного клика

                await asyncio.sleep(0.01)

        except Exception as e:
            logger.error(f"💥 Crash: {e}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
        logger.info("🛑 Gesture System Stopped")

# Глобальный обработчик завершения (для systemd)
def signal_handler(sig, frame):
    controller.stop()
    sys.exit(0)

if __name__ == "__main__":
    controller = VectorGestureMouse()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(controller.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()