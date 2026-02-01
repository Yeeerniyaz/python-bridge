import pexpect
import sys
import time

MAC = "14:33:5C:C0:5C:BA"

def run_bridge():
    print(f"🚀 [BRIDGE] VECTOR: Старт прослушки {MAC}...", file=sys.stderr)
    # Запускаем gatttool в интерактивном режиме
    child = pexpect.spawn(f"gatttool -b {MAC} -t public --interactive")
    
    try:
        child.expect(r"\[LE\]>", timeout=10)
        child.sendline("connect")
        
        if child.expect(["Connection successful", pexpect.TIMEOUT], timeout=15) == 0:
            print("✅ [BRIDGE] Соединение установлено!", file=sys.stderr)
            
            # Пробуем включить уведомления на самых частых ручках для ESP32 (0x0012, 0x0011, 0x000e)
            # Одна из них точно сработает
            for h in ["0x0012", "0x0011", "0x000e", "0x002a"]:
                child.sendline(f"char-write-req {h} 0100")
                time.sleep(0.2)
            
            print("📡 [BRIDGE] Жду данные (JSON)...", file=sys.stderr)

            while True:
                # Ждем строку с данными
                idx = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=10)
                
                if idx == 0:
                    hex_data = child.readline().decode().strip()
                    try:
                        # Чистим hex и переводим в текст
                        clean_hex = hex_data.replace(" ", "")
                        bytes_data = bytes.fromhex(clean_hex)
                        decoded = bytes_data.decode('utf-8').strip()
                        
                        if "{" in decoded: # Проверяем наличие JSON
                            print(decoded)
                            sys.stdout.flush()
                    except:
                        pass
                
                if idx == 2:
                    print("❌ [BRIDGE] Разрыв связи.", file=sys.stderr)
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
            sys.exit(0)
        time.sleep(2)