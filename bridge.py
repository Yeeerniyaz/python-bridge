import pexpect
import sys
import time

MAC = "14:33:5C:C0:5C:BA"
# Твои ручки из лога:
NOTIFY_HANDLE = "0x0011" # Для включения потока данных (CCCD)
WRITE_HANDLE = "0x0013"  # Для отправки команд (RX)

def run_bridge():
    print(f"🚀 [BRIDGE] VECTOR: Старт на Public {MAC}...", file=sys.stderr)
    child = pexpect.spawn(f"gatttool -b {MAC} -t public --interactive")
    
    try:
        child.expect(r"\[LE\]>", timeout=10)
        child.sendline("connect")
        
        if child.expect(["Connection successful", pexpect.TIMEOUT], timeout=15) == 0:
            print("✅ [BRIDGE] СОЕДИНЕНИЕ УСТАНОВЛЕНО!", file=sys.stderr)
            
            # Активируем уведомления (пишем 0100 в ручку 0x0011)
            print(f"📡 [BRIDGE] Активация TX (handle {NOTIFY_HANDLE})...", file=sys.stderr)
            child.sendline(f"char-write-req {NOTIFY_HANDLE} 0100")
            
            print("📡 [BRIDGE] Жду JSON...", file=sys.stderr)

            while True:
                # Слушаем поток данных
                idx = child.expect(["Notification handle = 0x0010 value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=10)
                
                if idx == 0:
                    hex_data = child.readline().decode().strip()
                    try:
                        # Конвертируем HEX в текст (JSON)
                        bytes_data = bytes.fromhex(hex_data.replace(" ", ""))
                        decoded = bytes_data.decode('utf-8').strip()
                        if "{" in decoded:
                            print(decoded) # Этот вывод заберет Electron
                            sys.stdout.flush()
                    except: pass
                
                if idx == 2:
                    print("❌ [BRIDGE] ESP32 отключилась.", file=sys.stderr)
                    break
        else:
            print("❌ [BRIDGE] Не удалось подключиться.", file=sys.stderr)
            
    except Exception as e:
        print(f"⚠️ [BRIDGE] Ошибка: {e}", file=sys.stderr)
    finally:
        child.close()

if __name__ == "__main__":
    while True:
        try:
            run_bridge()
        except KeyboardInterrupt:
            print("\n🛑 Мост остановлен.", file=sys.stderr)
            sys.exit(0)
        time.sleep(3)