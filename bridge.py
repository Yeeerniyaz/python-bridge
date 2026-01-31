import asyncio
import json
import threading
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from bleak import BleakClient, BleakScanner

# --- НАСТРОЙКИ ---
DEVICE_NAME = "VECTOR_ESP32"

# UUID (Должны совпадать с прошивкой ESP32)
SENSOR_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_CHAR_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"

# Глобальные переменные
latest_sensors = {"temp": "--", "hum": "--", "co2": "--"}
ble_client = None
ble_loop = asyncio.new_event_loop()
connection_event = asyncio.Event()

app = Flask(__name__)
CORS(app) # Разрешаем запросы от React

# ===========================
# 🌐 FLASK API (Для Electron)
# ===========================

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    """Отдает зеркалу последние данные с датчиков"""
    return jsonify(latest_sensors)

@app.route('/api/led', methods=['POST'])
def control_led():
    """Принимает команды для ленты и шлет их в ESP32"""
    global ble_client
    
    # Получаем JSON от Electron (например: {"mode": "RAINBOW", "speed": 50})
    command = request.json
    print(f"🌍 Получена команда API: {command}")
    
    if ble_client and ble_client.is_connected:
        try:
            # Превращаем JSON в строку байтов для ESP32
            payload = json.dumps(command).encode('utf-8')
            
            # Отправляем в BLE-поток
            future = asyncio.run_coroutine_threadsafe(
                ble_client.write_gatt_char(LED_CHAR_UUID, payload),
                ble_loop
            )
            future.result(timeout=2) # Ждем подтверждения отправки
            return jsonify({"status": "sent", "cmd": command})
        except Exception as e:
            print(f"❌ Ошибка отправки BLE: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        print("⚠️ ESP32 не подключена!")
        return jsonify({"status": "offline"}), 503

@app.route('/system/reboot', methods=['POST'])
def reboot_system():
    """Перезагрузка самой Малины (на всякий случай)"""
    import os
    os.system('sudo reboot')
    return jsonify({"status": "rebooting"})

# ===========================
# 🦷 BLUETOOTH ЛОГИКА (Bleak)
# ===========================

def sensor_callback(sender, data):
    """Обработка входящих данных от ESP32"""
    global latest_sensors
    try:
        # Декодируем байты в строку, потом в JSON
        json_str = data.decode('utf-8')
        latest_sensors = json.loads(json_str)
        # print(f"📡 Датчики: {latest_sensors}") # Раскомментируй для отладки
    except Exception as e:
        print(f"❌ Ошибка парсинга датчиков: {e}")

async def ble_manager():
    """Главный цикл управления Bluetooth"""
    global ble_client
    
    print("🦷 Запуск BLE менеджера...")
    
    while True:
        try:
            # 1. Поиск устройства
            print(f"🔍 Ищу {DEVICE_NAME}...")
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name == DEVICE_NAME,
                timeout=10.0
            )
            
            if not device:
                print("⚠️ Устройство не найдено, повтор через 5 сек...")
                await asyncio.sleep(5)
                continue

            # 2. Подключение
            print(f"🔗 Подключаюсь к {device.address}...")
            async with BleakClient(device, timeout=10.0) as client:
                ble_client = client
                
                # Подписываемся на обновления датчиков
                await client.start_notify(SENSOR_CHAR_UUID, sensor_callback)
                print(f"✅ УСПЕШНО ПОДКЛЮЧЕНО! Жду данные...")
                
                # Держим соединение активным
                while client.is_connected:
                    await asyncio.sleep(1)
                
                print("🔌 Соединение разорвано")
                ble_client = None

        except Exception as e:
            print(f"🧨 Ошибка BLE цикла: {e}")
            ble_client = None
            await asyncio.sleep(5) # Пауза перед реконнектом

# ===========================
# 🚀 ЗАПУСК
# ===========================

def start_ble_loop(loop):
    """Запуск asyncio в отдельном потоке"""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_manager())

if __name__ == '__main__':
    # 1. Запускаем Bluetooth в фоне
    ble_thread = threading.Thread(target=start_ble_loop, args=(ble_loop,), daemon=True)
    ble_thread.start()
    
    # 2. Запускаем Flask сервер (блокирует основной поток)
    print("🚀 Bridge API запущен на порту 5005")
    # host='0.0.0.0' делает сервер доступным для локальной сети и контейнеров
    app.run(host='0.0.0.0', port=5005, debug=False, use_reloader=False)