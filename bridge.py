import asyncio
import json
import threading
import time
import os
import logging
import paho.mqtt.client as mqtt # Добавили библиотеку для связи с облаком
from flask import Flask, jsonify, request
from flask_cors import CORS
from bleak import BleakClient, BleakScanner

# ===========================
# ⚙️ НАСТРОЙКИ (CONFIG)
# ===========================

# Путь к общему конфигу
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

def load_global_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

config = load_global_config()

# Имя устройства ESP32 для Bluetooth
DEVICE_NAME = "VECTOR_ESP32" 
# ID зеркала для Облака (Алисы)
DEVICE_ID = config.get("deviceId", "VECTOR_MIRROR_DEFAULT")
# Адрес твоего брокера
MQTT_BROKER = config.get("mqttBroker", "82.115.43.240")

SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"
API_PORT = 5005

# ===========================
# 📡 MQTT SETUP (Для Алисы)
# ===========================
mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, 1883, 60)
        mqtt_client.loop_start()
        print(f"✅ Connected to Cloud MQTT: {MQTT_BROKER}")
    except Exception as e:
        print(f"⚠️ MQTT Cloud error: {e}")

connect_mqtt()

# ===========================
# 📦 ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ===========================

latest_sensors = {
    "temp": 0, "hum": 0, "co2": 0, "status": "waiting..."
}

ble_client = None
ble_loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# ===========================
# 🌐 API ENDPOINTS (FLASK)
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    global ble_client
    command = request.json
    logger.info(f"🌍 API: Получена команда для ленты: {command}")
    
    if ble_client and ble_client.is_connected:
        try:
            payload = json.dumps(command).encode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ble_client.write_gatt_char(LED_CHAR_UUID, payload),
                ble_loop
            )
            return jsonify({"status": "success", "cmd": command})
        except Exception as e:
            logger.error(f"❌ Ошибка отправки BLE: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "offline"}), 503

# ===========================
# 🦷 BLUETOOTH ЛОГИКА (BLEAK)
# ===========================

def sensor_notification_handler(sender, data):
    global latest_sensors
    try:
        decoded_data = data.decode('utf-8')
        sensor_json = json.loads(decoded_data)
        
        # 1. Обновляем для Electron (Зеркала)
        latest_sensors.update(sensor_json)
        latest_sensors["status"] = "online"
        
        # 2. 🔥 ОТПРАВЛЯЕМ В ОБЛАКО (Для Алисы)
        # Публикуем в топик, который ждет твой сервер
        topic = f"vector/{DEVICE_ID}/state"
        mqtt_client.publish(topic, json.dumps(sensor_json))
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга JSON от ESP32: {e}")

async def ble_manager():
    global ble_client
    logger.info("🦷 Запуск BLE менеджера...")
    
    while True:
        try:
            logger.info(f"🔍 Сканирую эфир в поисках {DEVICE_NAME}...")
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name == DEVICE_NAME,
                timeout=10.0
            )
            
            if not device:
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(5)
                continue

            logger.info(f"🔗 Обнаружено! Подключаюсь к {device.address}...")
            
            async with BleakClient(device, timeout=10.0) as client:
                ble_client = client
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                
                logger.info(f"✅ УСПЕШНО ПОДКЛЮЧЕНО! Жду данные...")
                latest_sensors["status"] = "connected"
                
                while client.is_connected:
                    await asyncio.sleep(1)
                
                ble_client = None
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 Критическая ошибка BLE: {e}")
            ble_client = None
            latest_sensors["status"] = "error"
            await asyncio.sleep(5)

# ===========================
# 🚀 ЗАПУСК (MAIN)
# ===========================

def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    logger.info(f"🚀 VECTOR BRIDGE запущен на порту {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)