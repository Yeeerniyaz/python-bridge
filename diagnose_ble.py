import asyncio
import sys
from bleak import BleakScanner, BleakClient

# 🎯 ТВОИ НАСТРОЙКИ
TARGET_MAC = "14:33:5C:C0:5C:BA"  # Твой адрес ESP32 (из логов)
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

async def test_connection(client, variant_name, sleep_time=0):
    """Попытка подключения и отправки команды"""
    print(f"\n👉 [{variant_name}] Пробуем подключиться...")
    
    try:
        await client.connect()
        print(f"   ✅ [CONN] Соединение установлено!")
        
        if sleep_time > 0:
            print(f"   ⏳ [WAIT] Ждем {sleep_time} сек (даем ESP32 проснуться)...")
            await asyncio.sleep(sleep_time)

        # Самый важный момент - получение сервисов
        print(f"   🔍 [SERVICES] Запрашиваем список сервисов...")
        services = client.services
        
        # Если сервисов нет (BlueZ глюк), пробуем получить их явно
        if not services:
             print("   ⚠️ Сервисы пусты, пробуем get_services()...")
             services = await client.get_services()

        print(f"   ✅ [OK] Сервисы получены: {len(services)} шт.")
        
        # Тест записи
        print(f"   📤 [SEND] Отправляем команду цвета...")
        await client.write_gatt_char(WRITE_UUID, b'{"color": [0, 255, 0]}', response=True)
        print(f"   🎉 [SUCCESS] УРА! ЭТОТ ВАРИАНТ СРАБОТАЛ!")
        
        await client.disconnect()
        return True

    except Exception as e:
        print(f"   ❌ [FAIL] Ошибка: {e}")
        try:
            await client.disconnect()
        except:
            pass
        return False

async def main():
    print(f"💎 VECTOR ULTRA CONNECT 💎")
    print(f"🎯 Цель: {TARGET_MAC}\n")

    # ==========================================
    # ВАРИАНТ 1: "АККУРАТНЫЙ" (Самый вероятный)
    # ==========================================
    # Мы ждем 4 секунды после подключения, так как в твоем коде ESP32
    # есть пауза 3 секунды при старте (строка 93 main.py).
    # Если мы начнем долбить запросами раньше, он разорвет связь.
    print("--- ВАРИАНТ 1: Пауза под твой код ---")
    async with BleakClient(TARGET_MAC, timeout=15.0) as client:
        if await test_connection(client, "1. PAUSE 4 SEC", sleep_time=4):
            return

    await asyncio.sleep(2)

    # ==========================================
    # ВАРИАНТ 2: "БЫСТРЫЙ СТАНДАРТ"
    # ==========================================
    # Обычное подключение без ожиданий.
    print("\n--- ВАРИАНТ 2: Стандарт ---")
    async with BleakClient(TARGET_MAC, timeout=10.0) as client:
        if await test_connection(client, "2. STANDARD", sleep_time=0):
            return

    await asyncio.sleep(2)

    # ==========================================
    # ВАРИАНТ 3: "УПОРНЫЙ" (Long Timeout)
    # ==========================================
    # Даем 30 секунд на подключение.
    print("\n--- ВАРИАНТ 3: Долгий тайм-аут ---")
    async with BleakClient(TARGET_MAC, timeout=30.0) as client:
        if await test_connection(client, "3. LONG TIMEOUT", sleep_time=1):
            return

    await asyncio.sleep(2)

    # ==========================================
    # ВАРИАНТ 4: "ЧЕРЕЗ СКАНЕР" (Refresh)
    # ==========================================
    # Сначала ищем устройство сканером, чтобы обновить RSSI, и используем объект устройства.
    print("\n--- ВАРИАНТ 4: Через сканирование ---")
    device = await BleakScanner.find_device_by_address(TARGET_MAC, timeout=10.0)
    if device:
        async with BleakClient(device, timeout=15.0) as client:
            if await test_connection(client, "4. VIA SCANNER", sleep_time=2):
                return
    else:
        print("   ❌ Сканер не увидел устройство.")

    await asyncio.sleep(2)

    # ==========================================
    # ВАРИАНТ 5: "GATT HACK" (Без MTU)
    # ==========================================
    # Иногда согласование MTU ломает связь. В Bleak сложно отключить, 
    # но мы попробуем просто подключиться с минимальными настройками (по дефолту).
    print("\n--- ВАРИАНТ 5: Последняя надежда ---")
    # Пробуем подключиться к 'device' если нашли его в шаге 4, иначе по MAC
    target = device if 'device' in locals() and device else TARGET_MAC
    async with BleakClient(target, timeout=20.0) as client:
        if await test_connection(client, "5. FINAL TRY", sleep_time=5):
            return

    print("\n💀 ВСЕ ВАРИАНТЫ ПРОВАЛЕНЫ.")
    print("👉 Сделай в терминале: sudo bluetoothctl remove 14:33:5C:C0:5C:BA")
    print("👉 Потом перезагрузи ESP32.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")