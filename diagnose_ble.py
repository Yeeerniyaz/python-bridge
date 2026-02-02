import asyncio
import sys
from bleak import BleakScanner, BleakClient

# 🎯 ТВОИ НАСТРОЙКИ
TARGET_MAC = "14:33:5C:C0:5C:BA"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

async def test_connection(client, variant_name, sleep_time=0):
    """
    Попытка подключения с защитой от вылетов.
    Возвращает True, если успешно, False если ошибка.
    """
    print(f"\n👉 [{variant_name}] Пробуем подключиться...")
    
    try:
        # 1. ПОДКЛЮЧЕНИЕ
        await client.connect()
        print(f"   ✅ [CONN] Соединение установлено!")
        
        # 2. ПАУЗА (если нужна)
        if sleep_time > 0:
            print(f"   ⏳ [WAIT] Ждем {sleep_time} сек...")
            await asyncio.sleep(sleep_time)

        # 3. СЕРВИСЫ
        print(f"   🔍 [SERVICES] Проверка сервисов...")
        # Безопасное получение сервисов
        try:
            services = client.services
            if not services:
                # Если пустой список, пробуем принудительно обновить
                services = await client.get_services()
        except Exception as s_err:
             print(f"   ⚠️ Ошибка получения сервисов: {s_err}")
             await client.disconnect()
             return False

        print(f"   ✅ [OK] Сервисы есть! ({len(services)} шт.)")
        
        # 4. ОТПРАВКА КОМАНДЫ
        print(f"   📤 [SEND] Отправляем команду...")
        await client.write_gatt_char(WRITE_UUID, b'{"color": [0, 255, 0]}', response=True)
        print(f"   🎉 [SUCCESS] УСПЕХ! СВЕТ ГОРИТ!")
        
        await client.disconnect()
        return True

    except Exception as e:
        # ЛОВИМ ЛЮБУЮ ОШИБКУ, ЧТОБЫ СКРИПТ НЕ УПАЛ
        print(f"   ❌ [FAIL] Не вышло: {e}")
        try:
            # Пытаемся корректно закрыть, если открыто
            await client.disconnect()
        except:
            pass
        return False

async def main():
    print(f"💎 VECTOR ULTRA CONNECT (SAFE MODE) 💎")
    print(f"🎯 Цель: {TARGET_MAC}")
    
    # ---------------------------------------------------------
    # ВАРИАНТ 1: ОСТОРОЖНЫЙ (С паузой)
    # ---------------------------------------------------------
    print("\n--- ВАРИАНТ 1: Пауза 4 сек (Под MicroPython) ---")
    try:
        async with BleakClient(TARGET_MAC, timeout=15.0) as client:
            if await test_connection(client, "1. PAUSE 4s", sleep_time=4):
                return
    except Exception as e:
        print(f"   ❌ Ошибка в варианте 1: {e}")

    await asyncio.sleep(2)

    # ---------------------------------------------------------
    # ВАРИАНТ 2: БЫСТРЫЙ
    # ---------------------------------------------------------
    print("\n--- ВАРИАНТ 2: Быстрый старт ---")
    try:
        async with BleakClient(TARGET_MAC, timeout=10.0) as client:
            if await test_connection(client, "2. STANDARD", sleep_time=0):
                return
    except Exception as e:
        print(f"   ❌ Ошибка в варианте 2: {e}")

    await asyncio.sleep(2)
    
    # ---------------------------------------------------------
    # ВАРИАНТ 3: ЧЕРЕЗ ПОИСК (SCAN FIRST)
    # ---------------------------------------------------------
    print("\n--- ВАРИАНТ 3: Поиск + Подключение ---")
    found_device = None
    try:
        print("   📡 Сканирую эфир...")
        found_device = await BleakScanner.find_device_by_address(TARGET_MAC, timeout=10.0)
    except Exception as e:
        print(f"   ⚠️ Ошибка сканера: {e}")

    if found_device:
        print("   ✅ Устройство найдено сканером!")
        try:
            async with BleakClient(found_device, timeout=20.0) as client:
                if await test_connection(client, "3. VIA SCANNER", sleep_time=2):
                    return
        except Exception as e:
             print(f"   ❌ Ошибка в варианте 3: {e}")
    else:
        print("   ❌ Сканер не увидел устройство.")

    print("\n💀 ВСЕ ВАРИАНТЫ ПРОВАЛЕНЫ.")
    print("💡 КЕҢЕС: `sudo bluetoothctl remove 14:33:5C:C0:5C:BA`")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Тоқтатылды.")
    except Exception as global_e:
        print(f"\n💥 ГЛОБАЛДЫ ҚАТЕ (Бірақ скрипт тоқтамады): {global_e}")