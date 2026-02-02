import asyncio
import sys
from bleak import BleakScanner, BleakClient

# Сенің ESP32 параметрлерің
TARGET_NAME = "Vector_Party"
TARGET_ADDRESS = "14:33:5C:C0:5C:BA" # Сенің соңғы логыңнан алынды
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

async def try_variant(variant_name, address, timeout, sleep_after_connect):
    print(f"\n👉 [{variant_name}] әдісін байқап көрудеміз...")
    print(f"   (Timeout: {timeout}s, Sleep: {sleep_after_connect}s)")
    
    client = BleakClient(address, timeout=timeout)
    try:
        await client.connect()
        print(f"   ✅ ҚОСЫЛДЫ! ({variant_name})")
        
        # Кейбір ESP32 сервистерді жүктеуге уақыт сұрайды
        if sleep_after_connect > 0:
            print(f"   ⏳ Тұрақталуын күту ({sleep_after_connect} сек)...")
            await asyncio.sleep(sleep_after_connect)
            
        # Сервистерді тексеру (ең қиын жері осы)
        print("   📜 Сервистерді оқуда...")
        # Bleak мұны автоматты түрде жасайды, біз жай ғана тексереміз
        services = client.services
        if not services:
             print("   ❌ Сервистер бос! (Discovery Failed)")
             await client.disconnect()
             return False
             
        print(f"   ✅ Сервистер табылды: {len(services)} дана")
        
        # Жұмыс істеп тұрғанын тексеру үшін команда жібереміз
        cmd = b'{"color": [255, 0, 0]}' # Қызыл
        await client.write_gatt_char(WRITE_UUID, cmd, response=True)
        print("   ✅ Команда сәтті жіберілді! Байланыс тұрақты.")
        
        await client.disconnect()
        return True

    except Exception as e:
        print(f"   ❌ Сәтсіз аяқталды: {e}")
        # Егер қосылып тұрса, үземіз
        try:
            await client.disconnect()
        except:
            pass
        return False

async def main():
    print(f"💎 VECTOR BRUTE FORCE CONNECT 💎")
    print(f"🎯 Мақсат: {TARGET_NAME} [{TARGET_ADDRESS}]")

    # === ВАРИАНТТАР ТІЗІМІ ===
    
    # 1-Вариант: Стандартты (Ең жылдам)
    if await try_variant("1. STANDARD", TARGET_ADDRESS, timeout=10.0, sleep_after_connect=0):
        print("\n🎉 1-ші вариант жұмыс істеді!")
        return

    # 2-Вариант: "Сабырлы" (ESP32-ге ес жиюға уақыт береміз)
    # Сенің ESP32 кодыңда 3 секунд пауза бар, соны ескереміз
    print("\n⚠️ 1-ші вариант өтпеді. 2 секунд демалыс...")
    await asyncio.sleep(2)
    if await try_variant("2. PATIENT (Wait 4s)", TARGET_ADDRESS, timeout=15.0, sleep_after_connect=4.0):
        print("\n🎉 2-ші вариант жұмыс істеді! (Кідіріс керек екен)")
        return

    # 3-Вариант: "Ұзақ күту" (Timeout 25 секунд)
    print("\n⚠️ 2-ші вариант өтпеді. 2 секунд демалыс...")
    await asyncio.sleep(2)
    if await try_variant("3. LONG TIMEOUT", TARGET_ADDRESS, timeout=25.0, sleep_after_connect=1.0):
        print("\n🎉 3-ші вариант жұмыс істеді!")
        return

    # 4-Вариант: "Тез-тез" (Cache жаңарту үшін)
    print("\n⚠️ 3-ші вариант өтпеді. Cache мәселесі болуы мүмкін.")
    print("🔄 Тез қосылып-өшіп көреміз...")
    await try_variant("4. DUMMY CONNECT", TARGET_ADDRESS, timeout=5.0, sleep_after_connect=0)
    await asyncio.sleep(1)
    if await try_variant("4. REAL CONNECT", TARGET_ADDRESS, timeout=10.0, sleep_after_connect=1.0):
        print("\n🎉 4-ші вариант жұмыс істеді!")
        return

    print("\n❌ БАРЛЫҚ ВАРИАНТТАР СӘТСІЗ АЯҚТАЛДЫ.")
    print("Кеңес: `sudo bluetoothctl remove 14:33:5C:C0:5C:BA` жасап көр.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass