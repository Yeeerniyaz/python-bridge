import asyncio
import json
import logging
from quart import Quart, request, jsonify
from bleak import BleakScanner, BleakClient

# ===========================
# ⚙️ НАСТРОЙКИ (CONFIG)
# ===========================
TARGET_NAME = "Vector_Party"
# UUID-лар сенің ESP32-мен бірдей болуы керек!
WRITE_UUID  = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

# API Server
app = Quart(__name__)

# Логтарды әдемілеу
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VECTOR")

# ===========================
# 🧠 BLE МЕНЕДЖЕР (Бронепоезд)
# ===========================
class VectorBLEManager:
    def __init__(self):
        self.client = None
        self.queue = asyncio.Queue()  # Командалар кезегі
        self.connected = False
        self.running = True
        self.device_address = None

    async def start_loop(self):
        """Негізгі фондық процесс: Қосылу -> Күту -> Командаларды орындау"""
        logger.info("🚀 BLE Manager is starting...")
        
        while self.running:
            try:
                # 1. Егер байланыс жоқ болса -> ҚОСЫЛАМЫЗ
                if not self.connected or not self.client or not self.client.is_connected:
                    await self.connect_logic()
                
                # 2. Егер байланыс бар болса -> КЕЗЕКТІ ТЕКСЕРЕМІЗ
                if self.connected:
                    try:
                        # Кезекте команда бар ма? (0.5 сек күтеміз)
                        cmd_data = await asyncio.wait_for(self.queue.get(), timeout=0.5)
                        await self.send_raw(cmd_data)
                        self.queue.task_done()
                    except asyncio.TimeoutError:
                        # Кезек бос, жай ғана байланысты тексеріп тұрамыз
                        pass
                    except Exception as e:
                        logger.error(f"Queue Error: {e}")
                        self.connected = False # Қате шықса, қайта қосылуға жібереміз

            except Exception as main_err:
                logger.error(f"💥 Main Loop Crash Protected: {main_err}")
                await asyncio.sleep(2) # Спам жасамау үшін кідіріс

    async def connect_logic(self):
        """Қосылу логикасы (Retry, Scan, Wait)"""
        self.connected = False
        logger.info("📡 Scanning for Vector_Party...")

        try:
            # А) Іздеу
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name and TARGET_NAME in d.name,
                timeout=10.0
            )

            if not device:
                logger.warning("❌ Device not found. Retrying in 3s...")
                await asyncio.sleep(3)
                return

            self.device_address = device.address
            logger.info(f"✅ Found: {self.device_address}. Connecting...")

            # Б) Қосылу
            self.client = BleakClient(device, timeout=15.0)
            await self.client.connect()
            
            logger.info("🔗 Bluetooth Connected!")
            
            # В) ⏳ ПАУЗА (ESP32 есін жиюы үшін - ӨТЕ МАҢЫЗДЫ!)
            logger.info("⏳ Waiting 4s for ESP32 stabilization...")
            await asyncio.sleep(4)

            # Г) Сервистерді тексеру (GATT)
            services = self.client.services
            if not services:
                logger.warning("⚠️ Services empty! Forcing refresh...")
                services = await self.client.get_services()
            
            logger.info(f"✅ Services ready: {len(services)} found.")
            self.connected = True
            
            # Д) Тест командасын жіберу (Мысалы, жасыл "жыпылық" - мен тірімін деген белгі)
            # await self.send_raw(b'{"color":[0,10,0]}') 

        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            self.connected = False
            # Қате болса, клиентті тазалаймыз
            if self.client:
                try:
                    await self.client.disconnect()
                except: pass
                self.client = None
            await asyncio.sleep(3)

    async def send_raw(self, data: bytes):
        """Тікелей жіберу (қателерді ұстап қалады)"""
        if not self.client or not self.connected:
            logger.warning("⚠️ Cannot send: Disconnected")
            raise ConnectionError("No BLE Connection")
        
        try:
            logger.info(f"📤 Sending: {data}")
            await self.client.write_gatt_char(WRITE_UUID, data, response=True)
        except Exception as e:
            logger.error(f"❌ Send Error: {e}")
            self.connected = False # Келесі циклде реконнект болады
            raise e

    async def enqueue_command(self, command_str: str):
        """API-дан келген команданы кезекке қосу"""
        logger.info(f"📥 Enqueued: {command_str}")
        await self.queue.put(command_str.encode('utf-8'))

# Менеджерді жасаймыз (Глобалды объект)
ble_manager = VectorBLEManager()

# ===========================
# 🌐 API ROUTES (API)
# ===========================

@app.before_serving
async def startup():
    """Сервер қосылғанда BLE циклін бастаймыз"""
    asyncio.create_task(ble_manager.start_loop())

@app.route('/led/color', methods=['POST'])
async def set_color():
    data = await request.get_json()
    rgb = data.get('color')
    if rgb:
        # JSON дайындау
        cmd = json.dumps({"color": rgb})
        # Кезекке лақтыру (жауапты күтпейміз, клиентке тез жауап береміз)
        await ble_manager.enqueue_command(cmd)
        return jsonify({"status": "queued", "color": rgb})
    return jsonify({"error": "no color"}), 400

@app.route('/led/mode', methods=['POST'])
async def set_mode():
    data = await request.get_json()
    mode = data.get('mode')
    if mode:
        await ble_manager.enqueue_command(mode.upper())
        return jsonify({"status": "queued", "mode": mode})
    return jsonify({"error": "no mode"}), 400

@app.route('/led/off', methods=['POST'])
async def set_off():
    await ble_manager.enqueue_command("OFF")
    return jsonify({"status": "queued", "action": "off"})

@app.route('/status', methods=['GET'])
async def get_status():
    return jsonify({
        "connected": ble_manager.connected,
        "queue_size": ble_manager.queue.qsize(),
        "device": ble_manager.device_address
    })

# ===========================
# 🚀 MAIN START
# ===========================
if __name__ == '__main__':
    # Hypercorn/Uvicorn-сыз тікелей іске қосу (Dev mode)
    app.run(host='0.0.0.0', port=5005)