import asyncio
import json
import sys
import logging
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# Настройки — должны строго совпадать с ESP32
DEVICE_NAME = "Vector_Sensor"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

class VectorBridge:
    def __init__(self):
        self.client = None

    def notification_handler(self, characteristic, data):
        """Принимает данные от ESP32 и отправляет в stdout для Electron"""
        try:
            decoded = data.decode('utf-8').strip()
            # Выводим только если это похоже на JSON
            if decoded.startswith('{') and decoded.endswith('}'):
                print(decoded)
                sys.stdout.flush() # Мгновенная отправка в Electron
        except Exception:
            pass

    async def run(self):
        while True:
            try:
                print(f"🔍 [BRIDGE] Поиск {DEVICE_NAME}...", file=sys.stderr)
                device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
                
                if not device:
                    print("❌ [BRIDGE] Устройство не найдено. Повтор...", file=sys.stderr)
                    await asyncio.sleep(5)
                    continue

                print(f"🔵 [BRIDGE] Найдено: {device.address}. Подключение...", file=sys.stderr)
                
                async with BleakClient(device, timeout=20.0) as client:
                    self.client = client
                    print("🚀 [BRIDGE] Соединение установлено!", file=sys.stderr)
                    
                    # Даем стеку BlueZ время прочухаться перед поиском сервисов
                    await asyncio.sleep(1.5)
                    
                    # Включаем уведомления (TX)
                    await client.start_notify(UART_TX_UUID, self.notification_handler)
                    print("📡 [BRIDGE] Слушаю данные от датчиков...", file=sys.stderr)

                    # Цикл удержания связи и чтения команд из stdin (если нужно)
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except BleakError as e:
                print(f"⚠️ [BRIDGE] Ошибка Bluetooth: {e}", file=sys.stderr)
            except Exception as e:
                print(f"💥 [BRIDGE] Критическая ошибка: {e}", file=sys.stderr)
            
            # Пауза перед попыткой переподключения
            self.client = None
            print("🔄 [BRIDGE] Переподключение через 3 секунды...", file=sys.stderr)
            await asyncio.sleep(3)

if __name__ == "__main__":
    # На Raspberry Pi BlueZ иногда требует времени на инициализацию
    bridge = VectorBridge()
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n🛑 [BRIDGE] Мост остановлен пользователем.", file=sys.stderr)
        sys.exit(0)