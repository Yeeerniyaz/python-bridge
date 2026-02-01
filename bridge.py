import pexpect
import sys
import time

MAC = "14:33:5C:C0:5C:BA"

def run_bridge():
    print(f"🚀 [BRIDGE] Запуск VECTOR в режиме PUBLIC...", file=sys.stderr)
    # Сразу используем public, раз он сработал
    child = pexpect.spawn(f"gatttool -b {MAC} -t public --interactive")
    
    try:
        child.expect(r"\[LE\]>", timeout=10)
        child.sendline("connect")
        
        index = child.expect(["Connection successful", "Error", pexpect.TIMEOUT], timeout=15)
        
        if index == 0:
            print("✅ [BRIDGE] СОЕДИНЕНИЕ УСТАНОВЛЕНО!", file=sys.stderr)
            
            # Подписываемся на уведомления (handle 0x0012 обычно стандарт для UART на ESP32)
            # Если не заработает, заменим 0x0012 на тот, что найдем через --char-desc
            child.sendline("char-write-req 0x0012 0100") 
            
            print("📡 [BRIDGE] Поток данных активирован. Жду JSON...", file=sys.stderr)

            while True:
                # Слушаем поток данных
                idx = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=10)
                
                if idx == 0:
                    hex_data = child.readline().decode().strip()
                    try:
                        # Конвертируем HEX в текст
                        bytes_data = bytes.fromhex(hex_data.replace(" ", ""))
                        decoded = bytes_data.decode('utf-8').strip()
                        if decoded.startswith('{'):
                            print(decoded) # Вот этот вывод поймает Electron
                            sys.stdout.flush()
                    except: pass
                
                if idx == 2:
                    print("❌ [BRIDGE] ESP32 разорвала связь.", file=sys.stderr)
                    break
        else:
            print("❌ [BRIDGE] Ошибка подключения.", file=sys.stderr)
            
    except Exception as e:
        print(f"⚠️ [BRIDGE] Ошибка: {e}", file=sys.stderr)
    finally:
        child.close()

if __name__ == "__main__":
    while True:
        run_bridge()
        print("🔄 [BRIDGE] Переподключение через 5 секунд...", file=sys.stderr)
        time.sleep(5)