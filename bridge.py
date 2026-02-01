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

# Ищем по именам (для совместимости)
TARGET_DEVICE_NAMES = ["VECTOR_ESP32", "MPY ESP32"]

# UUID (Должны совпадать с ESP32)
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

API_PORT = 5005

# ===========================
# 📦 ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ===========================

latest_sensors = {"temp": 0, "hum": 0, "co2": 0, "status": "booting..."}
ble_client = None
ble_loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# ===========================
# 🛠 СИСТЕМНЫЕ УТИЛИТЫ
# ===========================

def reset_bluetooth_service():
    """Перезапуск BlueZ для лечения 'зависаний' адаптера RPi."""
    logger.info("💀 SYSTEM: Перезапуск службы Bluetooth...")
    try:
        os.system("sudo rfkill unblock bluetooth")
        os.system("sudo systemctl restart bluetooth")
        time.sleep(3) # Даем службе подняться
        os.system("sudo hciconfig hci0 up")
        time.sleep(1)
        logger.info("✅ SYSTEM: Bluetooth сброшен и готов.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сброса (нужен sudo): {e}")

# ===========================
# 🌐 API (FLASK)
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
# 🦷 BLE MANAGER (BULLDOG MODE)
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
    logger.info("🦷 VECTOR BLE Started")
    
    while True:
        try:
            # --- ЭТАП 1: ПОИСК (SCAN) ---
            logger.info("🔍 Сканирование эфира...")
            target_device = None
            
            # Сканируем 5 секунд
            devices = await BleakScanner.discover(timeout=5.0, adapter="hci0")
            
            for d in devices:
                if d.name in TARGET_DEVICE_NAMES:
                    target_device = d
                    logger.info(f"🎯 ЦЕЛЬ ОБНАРУЖЕНА: '{d.name}' [{d.address}]")
                    break
            
            if not target_device:
                logger.warning(f"⚠️ Vector не найден (всего устройств: {len(devices)}). Повтор...")
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(2)
                continue

            # --- ЭТАП 2: ПОДКЛЮЧЕНИЕ С ПОВТОРАМИ (RETRY LOGIC) ---
            connected = False
            
            # Пробуем 3 раза, если с первого раза вылетит ошибка "failed to discover services"
            for attempt in range(1, 4):
                try:
                    logger.info(f"🥊 Попытка подключения {attempt}/3 к {target_device.address}...")
                    
                    # Создаем клиента
                    client = BleakClient(target_device.address, timeout=15.0, adapter="hci0")
                    
                    # Пытаемся соединиться
                    await client.connect()
                    
                    if client.is_connected:
                        ble_client = client
                        connected = True
                        logger.info("✅ УСПЕШНОЕ ПОДКЛЮЧЕНИЕ!")
                        break # Выходим из цикла попыток, так как всё ок
                        
                except Exception as e:
                    logger.warning(f"⚠️ Сбой подключения (попытка {attempt}): {e}")
                    await asyncio.sleep(1.5) # Даем ESP32 отдышаться перед новой атакой
            
            if not connected:
                logger.error("🧨 Не удалось подключиться после 3 попыток. Начинаю поиск заново.")
                await asyncio.sleep(3)
                continue

            # --- ЭТАП 3: РАБОТА (OPERATING) ---
            latest_sensors["status"] = "connected"
            
            # Подписка
            try:
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                logger.info("📡 Подписка на данные активна")
            except Exception as e:
                logger.error(f"⚠️ Ошибка подписки (но соединение есть): {e}")

            # Держим цикл пока есть связь
            while client.is_connected:
                await asyncio.sleep(1)
                
            # Если вышли из цикла - значит дисконнект
            logger.warning("🔌 Соединение разорвано. Перезапуск цикла...")
            ble_client = None
            latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🔥 Критическая ошибка BLE менеджера: {e}")
            ble_client = None
            latest_sensors["status"] = "error"
            # Если совсем беда - сбрасываем интерфейс
            os.system("sudo hciconfig hci0 reset")
            await asyncio.sleep(5) 

# ===========================
# 🚀 MAIN
# ===========================

def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. Сброс системы Bluetooth (важно для RPi)
    reset_bluetooth_service()

    # 2. Запуск BLE в фоне
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 3. Запуск сервера API
    logger.info(f"🚀 SERVER RUNNING: {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)