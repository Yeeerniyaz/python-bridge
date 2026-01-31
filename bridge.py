import asyncio
import json
import threading
import time
import os
import logging
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request
from flask_cors import CORS
from bleak import BleakClient, BleakScanner

# =================================================================
# ⚙️ CONFIGURATION (Чтение из общего файла)
# =================================================================

# Путь к общему конфигу (на уровень выше, как ты просил)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

def load_global_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

config = load_global_config()

# Параметры из конфига
DEVICE_NAME = "VECTOR_ESP32"
MQTT_BROKER = config.get("mqttBroker", "82.115.43.240")
API_PORT    = 5005

# BLE UUIDs
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

# =================================================================
# 📡 MQTT CLOUD SETUP (Для Алисы)
# =================================================================

mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, 1883, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"⚠️ MQTT Cloud connection failed: {e}")

connect_mqtt()

# =================================================================
# 📦 GLOBAL STATE & LOGGING
# =================================================================

latest_sensors = {
    "temp": 0, "hum": 0, "co2": 0, "status": "waiting..."
}

ble_client = None
ble_loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# =================================================================
# 🌐 API ENDPOINTS (Функции не тронуты)
# =================================================================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    global ble_client
    command = request.json
    logger.info(f"🌍 API -> LED: {command}")
    
    if ble_client and ble_client.is_connected:
        try:
            payload = json.dumps(command).encode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ble_client.write_gatt_char(LED_CHAR_UUID, payload),
                ble_loop
            )
            return jsonify({"status": "success", "cmd": command})
        except Exception as e:
            logger.error(f"❌ BLE Write Error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "offline"}), 503

@app.route('/system/reboot', methods=['POST'])
def system_reboot():
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# =================================================================
# 🦷 BLUETOOTH & CLOUD SYNC
# =================================================================

def sensor_notification_handler(sender, data):
    """Обновляет локальные данные и отправляет их в Облако"""
    global latest_sensors
    try:
        decoded_data = data.decode('utf-8')
        sensor_json = json.loads(decoded_data)
        
        # Обновляем состояние для Electron
        latest_sensors.update(sensor_json)
        latest_sensors["status"] = "online"
        
        # 🔥 ОТПРАВКА В ОБЛАКО (Синхронизация с Алисой)
        topic = f"vector/{DEVICE_NAME}/state"
        mqtt_client.publish(topic, json.dumps(sensor_json))
        
    except Exception as e:
        logger.error(f"❌ Parser Error: {e}")

async def ble_manager():
    global ble_client
    logger.info(f"🦷 Ищу устройство: {DEVICE_NAME}...")
    
    while True:
        try:
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name == DEVICE_NAME, timeout=10.0
            )
            
            if not device:
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(5)
                continue

            async with BleakClient(device, timeout=10.0) as client:
                ble_client = client
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                
                logger.info(f"✅ Подключено к {DEVICE_NAME} ({device.address})")
                latest_sensors["status"] = "connected"
                
                while client.is_connected:
                    await asyncio.sleep(1)
                
                logger.warning("🔌 Bluetooth разрыв соединения")
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 BLE Manager Error: {e}")
            latest_sensors["status"] = "error"
            await asyncio.sleep(5)

# =================================================================
# 🚀 LAUNCHER
# =================================================================

def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. Запуск Bluetooth потока
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 2. Запуск Flask
    print("\n" + "="*50)
    print(f"🚀 VECTOR BRIDGE SYSTEM ONLINE")
    print(f"📍 Device ID: {DEVICE_NAME}")
    print(f"🔗 Cloud MQTT: {MQTT_BROKER}")
    print(f"🌐 Local API: http://localhost:{API_PORT}")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)