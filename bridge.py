import pexpect
import sys
import time
import json

# Твои данные
MAC = "14:33:5C:C0:5C:BA"
# UUID для RX (куда слать команды)
CHAR_UUID_RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

def run_bridge():
    print(f"🚀 [BRIDGE] Запуск жесткого коннекта к {MAC}...", file=sys.stderr)
    
    # Запускаем интерактивный gatttool (самый стабильный метод для ESP32)
    child = pexpect.spawn(f"gatttool -b {MAC} -t random --char-write-req -a 0x0001 -n 0100 --interactive")
    
    try:
        child.expect("\[LE\]>", timeout=10)
        print("🔍 [BRIDGE] Попытка подключения...", file=sys.stderr)
        child.sendline("connect")
        
        # Ждем успешного подключения
        child.expect("Connection successful", timeout=20)
        print("✅ [BRIDGE] СОЕДИНЕНИЕ УСТАНОВЛЕНО!", file=sys.stderr)

        while True:
            # Ждем уведомления от датчиков (Notification)
            index = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=5)
            
            if index == 0:
                # Получаем hex-данные
                hex_data = child.readline().decode().strip()
                # Переводим hex в текст (JSON)
                try:
                    bytes_data = bytes.fromhex(hex_data.replace(" ", ""))
                    decoded = bytes_data.decode('utf-8').strip()
                    if decoded.startswith('{'):
                        print(decoded)
                        sys.stdout.flush()
                except:
                    pass
            
            if index == 2:
                print("❌ [BRIDGE] ESP32 отключилась.", file=sys.stderr)
                break

    except Exception as e:
        print(f"⚠️ [BRIDGE] Ошибка: {e}", file=sys.stderr)
    finally:
        child.close()

if __name__ == "__main__":
    while True:
        try:
            run_bridge()
        except KeyboardInterrupt:
            sys.exit(0)
        print("🔄 [BRIDGE] Перезапуск через 5 секунд...", file=sys.stderr)
        time.sleep(5)