import asyncio
import json
import sys
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# Твое имя устройства из config.py на ESP32
DEVICE_NAME = "Vector_Sensor"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

class VectorBridge:
    def __init__(self):
        self.connected = False

    def notification_handler(self, characteristic, data):
        """Ловим данные от ESP32"""
        try:
            decoded = data.decode('utf-8').strip()
            if decoded.startswith('{'):
                print(decoded)
                sys.stdout.flush()
        except:
            pass

    async def run(self):
        while True:
            print(f"🔍 [BRIDGE] Ищу устройство с именем: {DEVICE_NAME}...", file=sys.stderr)
            
            # Ищем устройство по имени
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            
            if not device:
                print(f"❌ [BRIDGE] {DEVICE_NAME} не найден. Проверь ESP32.", file=sys.stderr)
                await asyncio.sleep(5)
                continue

            print(f"🔵 [BRIDGE] Нашел {DEVICE_NAME} ({device.address}). Подключаюсь...", file=sys.stderr)
            
            try:
                # На Linux (RPi) лучше ставить больший timeout на коннект
                async with BleakClient(device, timeout=20.0) as client:
                    print("✅ [BRIDGE] Соединение установлено!", file=sys.stderr)
                    
                    # КРИТИЧЕСКИ ВАЖНО: Пауза, чтобы BlueZ успел проинициализировать сервисы
                    await asyncio.sleep(2.0)
                    
                    # Пытаемся начать прослушивание
                    await client.start_notify(UART_TX_UUID, self.notification_handler)
                    print("📡 [BRIDGE] Поток данных активирован.", file=sys.stderr)
                    
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except BleakError as e:
                print(f"⚠️ [BRIDGE] Ошибка Bleak: {e}", file=sys.stderr)
            except Exception as e:
                print(f"💥 [BRIDGE] Непредвиденная ошибка: {e}", file=sys.stderr)
            
            print("🔄 [BRIDGE] Попытка переподключения через 5 сек...", file=sys.stderr)
            await asyncio.sleep(5)

if __name__ == "__main__":
    bridge = VectorBridge()
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n🛑 [BRIDGE] Мост остановлен пользователем.", file=sys.stderr)