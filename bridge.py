import asyncio
import sys
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

DEVICE_NAME = "Vector_Sensor"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

class VectorBridge:
    def __init__(self):
        self.client = None

    def handle_disconnect(self, client):
        print("\n📡 [BRIDGE] ESP32 разорвала соединение.", file=sys.stderr)

    def notification_handler(self, characteristic, data):
        try:
            decoded = data.decode('utf-8').strip()
            if decoded.startswith('{'):
                print(decoded)
                sys.stdout.flush()
        except: pass

    async def run(self):
        while True:
            print(f"🔍 [BRIDGE] Поиск {DEVICE_NAME}...", file=sys.stderr)
            # Ищем чуть дольше
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
            
            if not device:
                await asyncio.sleep(2)
                continue

            print(f"🔵 [BRIDGE] Подключение к {device.address}...", file=sys.stderr)
            
            try:
                # Настраиваем клиент с обработчиком разрыва
                async with BleakClient(
                    device, 
                    timeout=30.0, 
                    disconnected_callback=self.handle_disconnect
                ) as client:
                    
                    print("✅ [BRIDGE] Соединение установлено! Ждем стабильности...", file=sys.stderr)
                    # КРИТИЧНО: Даем ESP32 3 секунды просто "повисеть" перед опросом сервисов
                    await asyncio.sleep(3.0)
                    
                    # Принудительный опрос сервисов
                    services = await client.get_services()
                    print(f"📂 [BRIDGE] Сервисы найдены. Поиск характеристик...", file=sys.stderr)

                    await client.start_notify(UART_TX_UUID, self.notification_handler)
                    print("🚀 [BRIDGE] ПОТОК ДАННЫХ ПОШЕЛ!", file=sys.stderr)
                    
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except Exception as e:
                print(f"⚠️ [BRIDGE] Сбой: {e}", file=sys.stderr)
                await asyncio.sleep(5)

if __name__ == "__main__":
    bridge = VectorBridge()
    asyncio.run(bridge.run())