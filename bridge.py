import asyncio
import json
import logging
from quart import Quart, request, jsonify
from bleak import BleakScanner, BleakClient

# ===========================
# ⚙️ НАСТРОЙКИ (CONFIG)
# ===========================
TARGET_NAME = "Vector_Party"
WRITE_UUID  = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

# API Server
app = Quart(__name__)

# Логтарды баптау
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VECTOR")

# ===========================
# 🧠 BLE МЕНЕДЖЕР
# ===========================
class VectorBLEManager:
    def __init__(self):
        self.client = None
        self.queue = asyncio.Queue()
        self.connected = False
        self.running = True
        self.device_address = None

    async def start_loop(self):
        """Негізгі фондық процесс"""
        logger.info("🚀 BLE Manager is starting...")
        
        while self.running:
            try:
                # 1. Қосылу логикасы
                if not self.connected or not self.client or not self.client.is_connected:
                    await self.connect_logic()
                
                # 2. Кезектегі командаларды орындау
                if self.connected:
                    try:
                        cmd_data = await asyncio.wait_for(self.queue.get(), timeout=0.5)
                        await self.send_raw(cmd_data)
                        self.queue.task_done()
                    except asyncio.TimeoutError:
                        pass
                    except Exception as e:
                        logger.error(f"Queue Error: {e}")
                        self.connected = False

            except Exception as main_err:
                logger.error(f"💥 Main Loop Crash Protected: {main_err}")
                await asyncio.sleep(2)

    async def connect_logic(self):
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
            
            # В) ⏳ ПАУЗА (ESP32 тұрақталуы үшін)
            logger.info("⏳ Waiting 4s for ESP32 stabilization...")
            await asyncio.sleep(4)

            # Г) Сервистерді тексеру
            # ТҮЗЕТУ: len() қатесін болдырмау үшін try-except қолданамыз
            try:
                services = self.client.services
                # Кейбір нұсқаларда get_services() шақыру керек
                if not services:
                     logger.warning("⚠️ Services empty! Forcing refresh...")
                     services = await self.client.get_services()
                
                # Қауіпсіз санау
                count = 0
                try:
                    count = len(list(services))
                except: pass
                logger.info(f"✅ Services ready: {count} found.")
                
            except Exception as s_err:
                logger.warning(f"⚠️ Service check warning: {s_err}")

            self.connected = True

        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            self.connected = False
            if self.client:
                try:
                    await self.client.disconnect()
                except: pass
                self.client = None
            await asyncio.sleep(3)

    async def send_raw(self, data: bytes):
        if not self.client or not self.connected:
            logger.warning("⚠️ Cannot send: Disconnected")
            raise ConnectionError("No BLE Connection")
        
        try:
            logger.info(f"📤 Sending: {data}")
            await self.client.write_gatt_char(WRITE_UUID, data, response=True)
        except Exception as e:
            logger.error(f"❌ Send Error: {e}")
            self.connected = False
            raise e

    async def enqueue_command(self, command_str: str):
        logger.info(f"📥 Enqueued: {command_str}")
        await self.queue.put(command_str.encode('utf-8'))

ble_manager = VectorBLEManager()

# ===========================
# 🌐 API ROUTES
# ===========================

@app.before_serving
async def startup():
    asyncio.create_task(ble_manager.start_loop())

# ✅ ТҮЗЕТУ: Датчиктер жоқ, бірақ Electron сұрап жатыр (404 қатесін жою үшін)
@app.route('/api/sensors', methods=['GET'])
async def get_sensors_dummy():
    return jsonify({
        "temp": 0, 
        "hum": 0, 
        "co2": 0, 
        "pressure": 0,
        "status": "dummy"
    })

@app.route('/led/color', methods=['POST'])
async def set_color():
    data = await request.get_json()
    rgb = data.get('color')
    if rgb:
        cmd = json.dumps({"color": rgb})
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
        "device": ble_manager.device_address
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005)