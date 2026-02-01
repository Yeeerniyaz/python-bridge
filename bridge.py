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
# ⚙️ НАСТРОЙКИ (CONFIG)
# ===========================

DEVICE_NAME = "VECTOR_ESP32"

# UUID из твоего ESP32
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

API_PORT = 5005

# ===========================
# 📦 ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ===========================

latest_sensors = {
    "temp": 0, 
    "hum": 0, 
    "co2": 0, 
    "status": "waiting..."
}

ble_client = None
ble_loop = asyncio.new_event_loop()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

app = Flask(__name__)
CORS(app)

# ===========================
# 🛠 СИСТЕМНЫЕ УТИЛИТЫ (FIX)
# ===========================

def reset_bluetooth_service():
    """
    Эмулирует перезагрузку Raspberry Pi для Bluetooth-модуля.
    Перезапускает системный демон bluetoothd и поднимает интерфейс.
    """
    logger.info("💀 СИСТЕМА: Полный перезапуск службы Bluetooth (BlueZ)...")
    try:
        # 1. Снимаем программную блокировку (если есть)
        os.system("sudo rfkill unblock bluetooth")
        
        # 2. Перезапускаем саму службу (Самое важное действие!)
        os.system("sudo systemctl restart bluetooth")
        
        # Ждем, пока Linux проснется (3 секунды критически важны)
        logger.info("⏳ Жду поднятия службы...")
        time.sleep(3) 
        
        # 3. Принудительно поднимаем интерфейс
        os.system("sudo hciconfig hci0 up")
        time.sleep(1)
        
        logger.info("✅ СИСТЕМА: Bluetooth стек полностью перезагружен.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сброса (нужен sudo): {e}")

# ===========================
# 🌐 API ENDPOINTS
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    global ble_client
    command = request.json
    logger.info(f"🌍 API: Команда LED: {command}")
    
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
    else:
        return jsonify({"status": "offline"}), 503

@app.route('/system/reboot', methods=['POST'])
def system_reboot():
    logger.warning("🔄 REBOOT RPI")
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    logger.warning("🛑 SHUTDOWN RPI")
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# ===========================
# 🦷 BLUETOOTH ЛОГИКА
# ===========================

def sensor_notification_handler(sender, data):
    global latest_sensors
    try:
        decoded_data = data.decode('utf-8')
        sensor_json = json.loads(decoded_data)
        latest_sensors.update(sensor_json)
        latest_sensors["status"] = "online"
    except Exception as e:
        logger.error(f"❌ JSON Error: {e}")

async def ble_manager():
    global ble_client
    logger.info("🦷 BLE Manager Started")
    
    while True:
        try:
            # 1. Поиск (Явно указываем адаптер hci0)
            logger.info(f"🔍 Ищу {DEVICE_NAME}...")
            
            # discover возвращает список найденных устройств
            devices = await BleakScanner.discover(timeout=5.0, adapter="hci0")
            
            # Фильтруем список
            device = next((d for d in devices if d.name == DEVICE_NAME), None)
            
            if not device:
                logger.warning(f"⚠️ {DEVICE_NAME} не найден. (Вижу {len(devices)} других устр.)")
                # Для отладки можно раскомментировать строку ниже, чтобы видеть, кого он вообще видит:
                # for d in devices: logger.info(f"   -> {d.name} ({d.address})")
                
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(3)
                continue

            # 2. Подключение
            logger.info(f"🔗 Подключаюсь к {device.address}...")
            
            async with BleakClient(device, timeout=10.0, adapter="hci0") as client:
                ble_client = client
                
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                
                logger.info(f"✅ CONNECTED! VECTOR ONLINE.")
                latest_sensors["status"] = "connected"

                # Держим соединение
                while client.is_connected:
                    await asyncio.sleep(1)
                
                logger.warning("🔌 Disconnected")
                ble_client = None
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 BLE Error: {e}")
            ble_client = None
            latest_sensors["status"] = "error"
            await asyncio.sleep(5) 

# ===========================
# 🚀 MAIN START
# ===========================

def start_ble_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. ЖЕСТКИЙ СБРОС СЛУЖБЫ ПЕРЕД СТАРТОМ
    # Это решает проблему "работает только после перезагрузки"
    reset_bluetooth_service()

    # 2. Запуск потоков
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 3. Запуск Flask
    logger.info(f"🚀 VECTOR BRIDGE on port {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)