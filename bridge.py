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
# ⚙️ НАСТРОЙКИ
# ===========================
# Ищем ВСЕ варианты имен, чтобы точно найти ESP32
TARGET_DEVICE_NAMES = ["VECTOR_FINAL", "VECTOR_ESP32", "MPY ESP32"]

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
    """Перезапуск Bluetooth для лечения 'зависаний' адаптера RPi."""
    logger.info("💀 SYSTEM: Перезапуск службы Bluetooth...")
    try:
        os.system("sudo rfkill unblock bluetooth")
        os.system("sudo systemctl restart bluetooth")
        time.sleep(3) # Ждем пока служба поднимется
        os.system("sudo hciconfig hci0 up")
        time.sleep(1)
        logger.info("✅ Bluetooth Ready.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сброса (нужен sudo): {e}")

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

@app.route('/system/reboot', methods=['POST'])
def system_reboot():
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# ===========================
# 🦷 BLE MANAGER
# ===========================
def notify_handler(sender, data):
    global latest_sensors
    try:
        latest_sensors.update(json.loads(data.decode('utf-8')))
        latest_sensors["status"] = "online"
    except: pass

async def ble_manager():
    global ble_client
    logger.info("🦷 VECTOR BLE Manager Started")

    while True:
        try:
            # 1. ПОИСК (SCAN)
            logger.info("🔍 Сканирую эфир...")
            target = None
            
            # Сканируем 5 секунд
            devices = await BleakScanner.discover(timeout=5.0, adapter="hci0")
            
            # Проверяем, есть ли среди найденных наши имена
            for d in devices:
                if d.name in TARGET_DEVICE_NAMES:
                    target = d
                    logger.info(f"🎯 ЦЕЛЬ ОБНАРУЖЕНА: '{d.name}' [{d.address}]")
                    break
            
            if not target:
                logger.warning(f"⚠️ Vector не найден (всего вокруг: {len(devices)}). Повтор...")
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(2)
                continue

            # 2. ПОДКЛЮЧЕНИЕ (3 попытки)
            connected = False
            for i in range(3): # Пробуем 3 раза
                try:
                    logger.info(f"🔗 Попытка {i+1}/3 к {target.address}...")
                    client = BleakClient(target.address, timeout=15.0, adapter="hci0")
                    await client.connect()
                    
                    if client.is_connected:
                        ble_client = client
                        connected = True
                        logger.info("✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ!")
                        break
                except Exception as e:
                    logger.warning(f"⚠️ Сбой: {e}")
                    await asyncio.sleep(1.5) # Даем ESP32 время отдышаться
            
            if not connected:
                logger.error("🧨 Не удалось подключиться. Пробую искать заново...")
                continue

            # 3. РАБОТА
            latest_sensors["status"] = "connected"
            try: 
                await client.start_notify(SENSOR_UUID, notify_handler)
                logger.info("📡 Подписка на данные активна")
            except Exception as e:
                logger.error(f"⚠️ Ошибка подписки (но связь есть): {e}")

            # Держим соединение пока оно живое
            while client.is_connected:
                await asyncio.sleep(1)

            logger.warning("🔌 Устройство отключилось")
            ble_client = None
            latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 Критическая ошибка: {e}")
            # Если совсем всё плохо - сбрасываем адаптер
            os.system("sudo hciconfig hci0 reset")
            await asyncio.sleep(5)

# ===========================
# 🚀 MAIN
# ===========================
def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # Сброс Bluetooth при старте (Обязательно!)
    reset_bluetooth_service()
    
    t = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    t.start()
    
    logger.info(f"🚀 SERVER: {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)