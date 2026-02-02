import asyncio
import json
from quart import Quart, request, jsonify
from bleak import BleakClient, BleakScanner

app = Quart(__name__)

# ===========================
# ⚙️ НАСТРОЙКИ (Из твоего main.py)
# ===========================
TARGET_NAME = "Vector_Party"

# В твоем MicroPython коде:
# RX_UUID = ...E50E24DCCA9E (FLAG_WRITE) - сюда мы пишем с Raspberry Pi
WRITE_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

# Глобальные переменные для соединения
client = None
device_address = None

async def get_client():
    """Менеджер соединения BLE. Ищет, подключается и держит связь."""
    global client, device_address
    
    # 1. Если уже подключены — возвращаем клиент
    if client and client.is_connected:
        return client

    print(f"📡 Сканирую эфир в поиске {TARGET_NAME}...")
    
    # 2. Поиск устройства
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: d.name and TARGET_NAME in d.name
    )

    if not device:
        print("❌ Устройство не найдено! (Проверь питание ESP32)")
        return None

    device_address = device.address
    print(f"✅ Нашел! Адрес: {device_address}. Подключаюсь...")
    
    # 3. Подключение
    client = BleakClient(device_address)
    try:
        await client.connect()
        print(f"🔗 Успешное подключение к {TARGET_NAME}!")
        return client
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        client = None
        return None

async def send_to_esp(message: str):
    """Отправляет строку на ESP32 (конвертирует в байты)."""
    ble = await get_client()
    if ble:
        try:
            # Твой MicroPython делает .decode(), поэтому мы кодируем в utf-8
            data = message.encode("utf-8")
            await ble.write_gatt_char(WRITE_CHAR_UUID, data)
            print(f"📤 Отправлено: {message}")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка отправки: {e}")
            global client
            client = None # Сбрасываем клиент, чтобы переподключиться
            return False
    return False

# ===========================
# 🌐 API ЭНДПОИНТЫ (Для Electron)
# ===========================

@app.route('/led/color', methods=['POST'])
async def set_color():
    """Принимает JSON: {'color': [255, 0, 0]}"""
    try:
        req_data = await request.get_json()
        rgb = req_data.get('color') # [R, G, B]
        
        if not rgb or len(rgb) != 3:
            return jsonify({"status": "error", "msg": "Invalid color format"}), 400

        # Твой main.py ждет JSON строку для цвета: {"color": [r,g,b]}
        # Строка 44 в main.py: if msg.startswith("{"): ... data = json.loads(msg)
        cmd_json = json.dumps({"color": rgb})
        
        success = await send_to_esp(cmd_json)
        if success:
            return jsonify({"status": "ok", "color": rgb})
        else:
            return jsonify({"status": "error", "msg": "BLE Disconnected"}), 500
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/led/mode', methods=['POST'])
async def set_mode():
    """Принимает JSON: {'mode': 'RAINBOW'}"""
    try:
        req_data = await request.get_json()
        mode = req_data.get('mode') # RAINBOW, FIRE, POLICE, OFF
        
        if not mode:
            return jsonify({"status": "error", "msg": "No mode provided"}), 400

        # Твой main.py ждет просто строку для режимов
        # Строка 57 в main.py: current_mode = cmd
        success = await send_to_esp(mode.upper())
        
        if success:
            return jsonify({"status": "ok", "mode": mode})
        else:
            return jsonify({"status": "error", "msg": "BLE Disconnected"}), 500
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/led/off', methods=['POST'])
async def led_off():
    """Просто выключает свет"""
    success = await send_to_esp("OFF")
    return jsonify({"status": "off" if success else "error"})

# ===========================
# 🚀 ЗАПУСК
# ===========================
if __name__ == '__main__':
    print("💎 VECTOR Python Bridge запускается на порту 5005...")
    # Запускаем Quart сервер
    app.run(host='0.0.0.0', port=5005)
    