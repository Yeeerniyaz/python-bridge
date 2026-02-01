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

# Имя устройства ESP32 (должно совпадать с прошивкой)
DEVICE_NAME = "VECTOR_ESP32"

# UUID сервисов и характеристик (из твоего main.py на ESP32)
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

# Порт, на котором будет работать API для Electron
API_PORT = 5005

# ===========================
# 📦 ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ===========================

# Здесь храним последние данные, чтобы отдавать их мгновенно
latest_sensors = {
    "temp": 0, 
    "hum": 0, 
    "co2": 0, 
    "status": "waiting..."
}

ble_client = None  # Объект клиента Bluetooth
ble_loop = asyncio.new_event_loop() # Отдельный цикл для Bluetooth

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("VECTOR")

# Инициализация Flask
app = Flask(__name__)
CORS(app) # Разрешаем запросы от React приложения

# ===========================
# 🛠 СИСТЕМНЫЕ УТИЛИТЫ
# ===========================

def reset_bluetooth_adapter():
    """
    Жесткий сброс Bluetooth-адаптера Raspberry Pi.
    Решает проблему 'зомби-соединений' после перезапуска скрипта.
    """
    logger.info("🔨 СИСТЕМА: Сброс Bluetooth адаптера (hci0)...")
    try:
        # Выключаем интерфейс
        os.system("sudo hciconfig hci0 down")
        time.sleep(1) # Даем железу секунду на отдых
        # Включаем интерфейс
        os.system("sudo hciconfig hci0 up")
        time.sleep(2) # Ждем инициализации
        logger.info("✅ СИСТЕМА: Адаптер перезагружен и готов к бою.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сброса адаптера (возможно нет прав sudo): {e}")

# ===========================
# 🌐 API ENDPOINTS (FLASK)
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    """Electron запрашивает этот адрес каждые 3 секунды."""
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    """Electron отправляет сюда команды управления лентой."""
    global ble_client
    command = request.json
    logger.info(f"🌍 API: Команда для ленты: {command}")
    
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
        logger.warning("⚠️ Команда пропущена: ESP32 не подключена")
        return jsonify({"status": "offline"}), 503

@app.route('/system/reboot', methods=['POST'])
def system_reboot():
    logger.warning("🔄 Команда: Перезагрузка системы")
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    logger.warning("🛑 Команда: Выключение системы")
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# ===========================
# 🦷 BLUETOOTH ЛОГИКА (BLEAK)
# ===========================

def sensor_notification_handler(sender, data):
    """Callback при получении данных от ESP32."""
    global latest_sensors
    try:
        decoded_data = data.decode('utf-8')
        sensor_json = json.loads(decoded_data)
        latest_sensors.update(sensor_json)
        latest_sensors["status"] = "online"
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")

async def ble_manager():
    """Главный цикл управления Bluetooth."""
    global ble_client
    
    logger.info("🦷 BLE Manager запущен")
    
    while True:
        try:
            # 1. Поиск устройства (Используем discover для свежего сканирования)
            logger.info(f"🔍 Сканирую эфир в поисках {DEVICE_NAME}...")
            
            # Сканируем 5 секунд
            devices = await BleakScanner.discover(timeout=5.0)
            
            # Ищем наше устройство в списке найденных
            device = next((d for d in devices if d.name == DEVICE_NAME), None)
            
            if not device:
                logger.warning("⚠️ VECTOR_ESP32 не найден. Повтор через 5 сек...")
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(5)
                continue

            # 2. Подключение
            logger.info(f"🔗 Нашел! Подключаюсь к {device.address}...")
            
            async with BleakClient(device, timeout=10.0) as client:
                ble_client = client
                
                # Подписываемся на датчики
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                
                logger.info(f"✅ УСПЕШНО ПОДКЛЮЧЕНО! Канал стабилен.")
                latest_sensors["status"] = "connected"

                # Бесконечный цикл, пока соединение живое
                while client.is_connected:
                    await asyncio.sleep(1)
                
                # Если вышли из цикла - значит дисконнект
                logger.warning("🔌 Соединение разорвано")
                ble_client = None
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 Ошибка BLE цикла: {e}")
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
    # 1. СНАЧАЛА "ПЕРЕДЕРГИВАЕМ" АДАПТЕР (FIX ZOMBIE CONNECTIONS)
    reset_bluetooth_adapter()

    # 2. Запускаем Bluetooth поток
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 3. Запускаем Flask
    logger.info(f"🚀 VECTOR BRIDGE запущен на порту {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)