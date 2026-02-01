import pexpect
import sys
import time
import re

MAC = "14:33:5C:C0:5C:BA"
# UUID твоего TX (из кода ESP32)
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

def run_bridge():
    print(f"🚀 [BRIDGE] Подключение к {MAC}...", file=sys.stderr)
    child = pexpect.spawn(f"gatttool -b {MAC} -t public --interactive")
    
    try:
        child.expect(r"\[LE\]>", timeout=10)
        child.sendline("connect")
        
        if child.expect(["Connection successful", pexpect.TIMEOUT], timeout=15) == 0:
            print("✅ [BRIDGE] Соединение установлено!", file=sys.stderr)
            
            # --- АВТОПОИСК HANDLE ---
            print("🔍 [BRIDGE] Ищу ручку (handle) для данных...", file=sys.stderr)
            child.sendline("char-desc")
            child.expect(r"\[LE\]>", timeout=5)
            
            # Ищем наш UUID в выводе char-desc
            output = child.before.decode().lower()
            match = re.search(r"handle:\s+(0x[0-9a-f]+),\s+uuid:\s+" + TX_UUID, output)
            
            if match:
                # Нашли handle характеристики, для подписки обычно нужен следующий (+1)
                base_handle = match.group(1)
                notify_handle = hex(int(base_handle, 16) + 1)
                print(f"🎯 [BRIDGE] Нашел! Характеристика: {base_handle}, Подписка: {notify_handle}", file=sys.stderr)
                
                # Команда на включение уведомлений
                child.sendline(f"char-write-req {notify_handle} 0100")
            else:
                # Если не нашли, пробуем стандартные 0x0012 или 0x0003
                print("⚠️ [BRIDGE] UUID не найден, пробую стандартный 0x0012", file=sys.stderr)
                child.sendline("char-write-req 0x0012 0100")

            print("📡 [BRIDGE] Жду JSON...", file=sys.stderr)

            while True:
                idx = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=10)
                if idx == 0:
                    hex_data = child.readline().decode().strip()
                    try:
                        bytes_data = bytes.fromhex(hex_data.replace(" ", ""))
                        decoded = bytes_data.decode('utf-8').strip()
                        if decoded.startswith('{'):
                            print(decoded)
                            sys.stdout.flush()
                    except: pass
                if idx == 2: break
        else:
            print("❌ [BRIDGE] Тайм-аут коннекта", file=sys.stderr)
            
    except Exception as e:
        print(f"⚠️ [BRIDGE] Ошибка: {e}", file=sys.stderr)
    finally:
        child.close()

if __name__ == "__main__":
    while True:
        run_bridge()
        time.sleep(5)