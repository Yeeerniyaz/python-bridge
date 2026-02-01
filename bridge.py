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
DEVICE_NAME = "VECTOR_FINAL"

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
# 🌐 API ENDPOINTS (FLASK)
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    """
    Electron запрашивает этот адрес каждые 3 секунды.
    Мы отдаем последние данные, полученные от ESP32.
    """
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    """
    Electron отправляет сюда команды управления лентой.
    Пример JSON: {"mode": "RAINBOW", "bright": 0.5, "speed": 50}
    """
    global ble_client
    command = request.json
    logger.info(f"🌍 API: Получена команда для ленты: {command}")
    
    if ble_client and ble_client.is_connected:
        try:
            # Превращаем JSON в байты и отправляем в очередь BLE
            payload = json.dumps(command).encode('utf-8')
            
            # Безопасно вызываем асинхронную функцию из синхронного Flask
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
    """Перезагрузка Raspberry Pi"""
    logger.warning("🔄 Получена команда перезагрузки системы")
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

@app.route('/system/shutdown', methods=['POST'])
def system_shutdown():
    """Выключение Raspberry Pi"""
    logger.warning("🛑 Получена команда выключения системы")
    os.system('sudo shutdown -h now')
    return jsonify({"status": "shutting_down"})

# ===========================
# 🦷 BLUETOOTH ЛОГИКА (BLEAK)
# ===========================

def sensor_notification_handler(sender, data):
    """
    Эта функция вызывается АВТОМАТИЧЕСКИ, когда ESP32 присылает данные.
    """
    global latest_sensors
    try:
        decoded_data = data.decode('utf-8')
        sensor_json = json.loads(decoded_data)
        
        # Обновляем глобальную переменную
        latest_sensors.update(sensor_json)
        latest_sensors["status"] = "online"
        
        # logger.info(f"📡 Данные от ESP32: {sensor_json}") # Раскомментируй для отладки
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга JSON от ESP32: {e}")

async def ble_manager():
    """
    Главный цикл управления Bluetooth.
    Занимается поиском, подключением и переподключением.
    """
    global ble_client
    
    logger.info("🦷 Запуск BLE менеджера...")
    
    while True:
        try:
            # 1. Поиск устройства
            logger.info(f"🔍 Сканирую эфир в поисках {DEVICE_NAME}...")
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name == DEVICE_NAME,
                timeout=10.0
            )
            
            if not device:
                logger.warning("⚠️ Устройство не найдено. Повтор через 5 сек...")
                latest_sensors["status"] = "searching..."
                await asyncio.sleep(5)
                continue

            # 2. Подключение
            logger.info(f"🔗 Обнаружено! Подключаюсь к {device.address}...")
            
            async with BleakClient(device, timeout=10.0) as client:
                ble_client = client
                
                # Подписываемся на характеристику датчиков
                await client.start_notify(SENSOR_CHAR_UUID, sensor_notification_handler)
                
                logger.info(f"✅ УСПЕШНО ПОДКЛЮЧЕНО! Жду данные...")
                latest_sensors["status"] = "connected"
                
                # Отправляем приветственный сигнал (опционально)
                # await client.write_gatt_char(LED_CHAR_UUID, b'{"mode":"STATIC","color":[0,255,0]}')

                # Бесконечный цикл, пока соединение живое
                while client.is_connected:
                    await asyncio.sleep(1)
                
                logger.warning("🔌 Соединение разорвано (Bluetooth disconnect)")
                ble_client = None
                latest_sensors["status"] = "disconnected"

        except Exception as e:
            logger.error(f"🧨 Критическая ошибка BLE: {e}")
            ble_client = None
            latest_sensors["status"] = "error"
            await asyncio.sleep(5) # Пауза перед новой попыткой

# ===========================
# 🚀 ЗАПУСК (MAIN)
# ===========================

def start_ble_loop(loop):
    """Функция для запуска asyncio в отдельном потоке"""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. Запускаем Bluetooth в фоновом потоке
    # (Это нужно, потому что Flask блокирует основной поток)
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 2. Запускаем веб-сервер Flask
    logger.info(f"🚀 VECTOR BRIDGE запущен на порту {API_PORT}")
    # host='0.0.0.0' делает API доступным для всех устройств в сети (важно для docker)
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)