import asyncio
import sys
from bleak import BleakScanner, BleakClient

# Сенің ESP32-дегі UUID-ларың
TARGET_NAME = "Vector_Party"
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
WRITE_UUID        = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID       = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

async def scan_only():
    print(f"\n🔎 [1-ВАРИАНТ] Барлық құрылғыларды қарап шығу...")
    try:
        devices = await BleakScanner.discover(timeout=5.0)
        found = False
        for d in devices:
            name = d.name or "Unknown"
            # RSSI кейде қате береді, сондықтан жай ғана адресті шығарамыз
            print(f"   - {name} [{d.address}]")
            if TARGET_NAME in name:
                found = True
                print(f"   ✅ ТАБЫЛДЫ! Бұл біздің клиент!")
        
        if not found:
            print("   ❌ 'Vector_Party' эфирде көрінбейді.") 
        return found
    except Exception as e:
        print(f"   ⚠️ Сканерлеу қатесі: {e}")
        return False

async def connect_and_list_services(address):
    print(f"\n🔗 [2-ВАРИАНТ] Қосылу және UUID тексеру...")
    try:
        async with BleakClient(address, timeout=15.0) as client:
            print(f"   ✅ Қосылдық! ({address})")
            
            print("   📜 Сервистер тізімі:")
            for service in client.services:
                print(f"   - Service: {service.uuid}")
                for char in service.characteristics:
                    print(f"     -- Char: {char.uuid} ({', '.join(char.properties)})")
                    
                    if str(char.uuid).upper() == WRITE_UUID.upper():
                        print("        ✨ WRITE UUID сәйкес келеді!")
                    if str(char.uuid).upper() == NOTIFY_UUID.upper():
                        print("        ✨ NOTIFY UUID сәйкес келеді!")
                        
            return True
    except Exception as e:
        print(f"   ❌ Қосылу қатесі: {e}")
        return False

async def try_send_command(address):
    print(f"\n📨 [3-ВАРИАНТ] Команда жіберіп көру...")
    try:
        async with BleakClient(address, timeout=10.0) as client:
            # Түсті өзгерту командасы (JSON)
            cmd = b'{"color": [0, 255, 0]}' # Жасыл түс
            print(f"   📤 Жіберіп жатырмын: {cmd}")
            
            await client.write_gatt_char(WRITE_UUID, cmd, response=True)
            print("   ✅ Команда кетті! Светодиод жанды ма?")
            return True
    except Exception as e:
        print(f"   ❌ Жіберу қатесі: {e}")
        return False

async def main():
    print("💎 VECTOR DIAGNOSTICS TOOL v2 💎")
    
    # 1. SCAN
    print("📡 'Vector_Party' ізделуде...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: d.name and TARGET_NAME in d.name
    )
    
    if not device:
        print("\n❌ ҚАТЕ: ESP32 тікелей іздеуде табылған жоқ.")
        print("Кеңес: ESP32-ні розеткадан суырып, қайта қос.")
        await scan_only() # Барлық құрылғыларды көрсету
        return

    print(f"\n✅ ESP32 табылды: {device.address}")
    
    # 2. SERVICE CHECK
    connected = await connect_and_list_services(device.address)
    if not connected:
        return

    # 3. SEND CHECK
    await try_send_command(device.address)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nТоқтатылды.")