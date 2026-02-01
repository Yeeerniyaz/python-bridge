import asyncio
import json
import threading
import time
import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from bleak import BleakClient, BleakScanner

# ===========================
# ⚙️ НАСТРОЙКИ (УНИВЕРСАЛЬНЫЕ)
# ===========================

# Ищем ЛЮБОЕ из этих имен.
# "MPY ESP32" - чтобы работало прямо сейчас.
# "VECTOR_ESP32" - чтобы работало в будущем.
TARGET_DEVICE_NAMES = ["VECTOR_ESP32", "MPY ESP32"]

# UUID (Те, что сейчас в твоей ESP32)
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

API_PORT = 5005

# ===========================
# 📦 GLOBAL STATE
# ===========================

latest_sensors = {"temp": 0, "hum": 0, "co2": 0, "status": "booting..."}
ble_client = None
ble_loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# ===========================
# 🛠 СИСТЕМА (СБРОС ЗАВИСАНИЙ)
# ===========================

def reset_bluetooth_service():
    """
    Перезапуск службы Bluetooth перед стартом.
    Решает проблему, когда RPi не видит устройства после перезапуска скрипта.
    """
    logger.info("💀 SYSTEM: Перезапуск службы Bluetooth (BlueZ)...")
    try:
        os.system("sudo rfkill unblock bluetooth")
        os.system("sudo systemctl restart bluetooth")
        time.sleep(3) # Ждем, пока служба поднимется
        os.system("sudo hciconfig hci0 up")
        time.sleep(1)
        logger.info("✅ SYSTEM: Bluetooth готов.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сброса (запусти с sudo): {e}")

# ===========================
# 🌐 API
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    global ble_client
    command = request.json
    logger.info(f"🌍 API CMD: {command}")
    
    if ble_client and ble_client.is_connected:
        try:
            payload = json.dumps(command).encode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ble_client.write_gatt_char(LED_CHAR_UUID, payload), ble_loop
            )
            return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"❌ Send Error: {e}")
            return jsonify({"status": "error", "msg": str(e)}), 500
    else:
        return jsonify({"status": "offline"}), 503

@app.route('/system/reboot', methods=['POST'])
def system_reboot():
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# ===========================
# 🦷 BLE MANAGER (ПОИСК ПО СПИСКУ ИМЕН)
# ===========================

def sensor_notification_handler(sender, data):
    global latest_sensors
    try:
        decoded = data.decode('utf-8')
        latest_sensors.update(json.loads(decoded))
        latest_sensors["status"] = "online"
    except:
        pass

async def ble_manager():
    global ble_client
    logger.info("🦷 Служба VECTOR BLE запущена")
    
    while True:
        try:
            # 1. ПОИСК (SCAN)
            logger.info("🔍 Ищу устройства (VECTOR_ESP32 или MPY ESP32)...")
            
            # Сканируем эфир 5 секунд
            devices = await BleakScanner.discover(timeout=5.0, adapter="hci0")
            
            # Ищем совпадение по имени
            target_device = None
            for d in devices:
                # Если имя устройства есть в нашем списке TARGET_DEVICE_NAMES
                if d.name in TARGET_DEVICE_NAMES:
                    target_device = d
                    logger.info(f"🎯 НАЙДЕНО: '{d.name}' [{d.address}]")
                    break
            
            if not target_device:
                logger.warning(f"⚠️ Цель не найдена. (Вижу {len(devices)} других). Повтор...")
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(3)
                continue

            # 2. ПОДКЛЮЧЕНИЕ (CONNECT)
            logger.info(f"🔗 Подключаюсь к {target_device.address}...")
            
            async with BleakClient(target_device.address, timeout=15.0, adapter="hci0") as client:
                ble_client = client
                
                if client.is_connected:
                    logger.info(f"✅ УСПЕШНО ПОДКЛЮЧЕНО к {target_device.name}!")
                    latest_sensors["status"] = "connected"
                    
                    # Подписка на уведомления
                    try:
                        await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                    except Exception as e:
                        logger.error(f"⚠️ Ошибка подписки (проверь UUID): {e}")

                    # Держим соединение
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
                logger.warning("🔌 Устройство отключилось")
                ble_client = None
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 Ошибка BLE: {e}")
            ble_client = None
            latest_sensors["status"] = "error"
            # Если ошибка - немного ждем перед новой попыткой
            await asyncio.sleep(5) 

# ===========================
# 🚀 ЗАПУСК
# ===========================

def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. Обязательный сброс службы (Fix зависания RPi)
    reset_bluetooth_service()

    # 2. Поток BLE
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 3. Flask
    logger.info(f"🚀 VECTOR SERVER running on {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)