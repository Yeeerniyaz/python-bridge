import asyncio
import json
import threading
import time
import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from bleak import BleakClient

# ===========================
# ⚙️ НАСТРОЙКИ (DIRECT CONNECT)
# ===========================
# МЫ ЗНАЕМ АДРЕС! ВПИСЫВАЕМ ЕГО ЖЕСТКО.
# Это решает проблему "failed to discover", так как мы пропускаем этап поиска.
DEVICE_MAC = "14:33:5C:C0:5C:BA" 

SENSOR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"
API_PORT = 5005

# ===========================
# 📦 STATE
# ===========================
latest_sensors = {"temp": 0, "hum": 0, "co2": 0, "status": "booting..."}
ble_client = None
ble_loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# ===========================
# 🛠 SELF-HEALING
# ===========================
def reset_bluetooth_service():
    logger.info("💀 SYSTEM: Перезапуск службы Bluetooth...")
    os.system("sudo rfkill unblock bluetooth")
    os.system("sudo systemctl restart bluetooth")
    time.sleep(3)
    os.system("sudo hciconfig hci0 up")
    time.sleep(1)
    logger.info("✅ Bluetooth Ready.")

# ===========================
# 🌐 API
# ===========================
@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    global ble_client
    cmd = request.json
    logger.info(f"🌍 API: {cmd}")
    if ble_client and ble_client.is_connected:
        try:
            payload = json.dumps(cmd).encode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ble_client.write_gatt_char(LED_UUID, payload), ble_loop
            )
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "msg": str(e)}), 500
    return jsonify({"status": "offline"}), 503

# ===========================
# 🦷 BLE MANAGER (DIRECT)
# ===========================
def notify_handler(sender, data):
    global latest_sensors
    try:
        latest_sensors.update(json.loads(data.decode('utf-8')))
        latest_sensors["status"] = "online"
    except: pass

async def ble_manager():
    global ble_client
    logger.info("🦷 BLE MANAGER: Direct Mode")

    while True:
        try:
            # Прямое подключение без сканирования!
            logger.info(f"🔗 Стучусь к {DEVICE_MAC}...")
            
            # Увеличенный таймаут (30 сек) - даем ESP32 время проснуться
            async with BleakClient(DEVICE_MAC, timeout=30.0, adapter="hci0") as client:
                ble_client = client
                
                logger.info("✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ!")
                latest_sensors["status"] = "connected"
                
                # Подписка
                try:
                    await client.start_notify(SENSOR_UUID, notify_handler)
                    logger.info("📡 Данные идут")
                except Exception as e:
                    logger.error(f"⚠️ Ошибка подписки: {e}")

                # Держим связь
                while client.is_connected:
                    await asyncio.sleep(1)

            logger.warning("🔌 Отключилось. Реконнект через 2 сек...")
            ble_client = None
            latest_sensors["status"] = "disconnected"
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"🧨 Ошибка: {e}")
            # Если ошибка - сброс и пауза
            os.system("sudo hciconfig hci0 reset")
            await asyncio.sleep(5)

# ===========================
# 🚀 MAIN
# ===========================
def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    reset_bluetooth_service()
    
    t = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    t.start()
    
    logger.info(f"🚀 SERVER: {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)