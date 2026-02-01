import asyncio
import json
import sys
from bleak import BleakClient, BleakScanner

# UUID характеристики для записи (RX), которую мы создали на ESP32
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
DEVICE_NAME = "Vector_Sensor"

class VectorBridge:
    def __init__(self):
        self.client = None

    def notification_handler(self, characteristic, data):
        """Читаем JSON от ESP32 и выводим в stdout"""
        try:
            decoded = data.decode('utf-8').strip()
            if decoded.startswith('{'):
                print(decoded) # Electron поймает это
                sys.stdout.flush()
        except: pass

    async def run(self):
        print(f"🔍 Поиск {DEVICE_NAME}...", file=sys.stderr)
        device = await BleakScanner.find_device_by_name(DEVICE_NAME)
        
        if not device:
            print("❌ Не нашел ESP32. Проверь питание.", file=sys.stderr)
            return

        async with BleakClient(device) as client:
            self.client = client
            print(f"✅ Подключено к {device.address}", file=sys.stderr)
            
            # Включаем прослушку данных
            await client.start_notify(UART_TX_UUID, self.notification_handler)
            
            # Читаем команды из stdin (от Electron) и шлем на ESP32
            loop = asyncio.get_event_loop()
            while client.is_connected:
                # Этот блок позволяет Electron отправлять команды через мост
                if sys.stdin in sys.stdin: # Проверка входящих команд
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if line:
                        cmd = line.strip()
                        await client.write_gatt_char(UART_RX_UUID, cmd.encode())
                await asyncio.sleep(0.1)

if __name__ == "__main__":
    bridge = VectorBridge()
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n🛑 Мост остановлен.", file=sys.stderr)