import pexpect
import sys
import time

MAC = "14:33:5C:C0:5C:BA"

def run_bridge():
    print(f"🚀 [BRIDGE] VECTOR: Пробую все ключи для {MAC}...", file=sys.stderr)
    # Используем интерактивный режим, он стабильнее для удержания связи
    child = pexpect.spawn(f"gatttool -b {MAC} -t public --interactive")
    
    try:
        child.expect(r"\[LE\]>", timeout=10)
        child.sendline("connect")
        
        if child.expect(["Connection successful", pexpect.TIMEOUT], timeout=15) == 0:
            print("✅ [BRIDGE] СОЕДИНЕНИЕ УСТАНОВЛЕНО!", file=sys.stderr)
            
            # Список всех подозрительных ручек из твоего дампа
            # 0x0011 - это CCCD для твоего TX
            # 0x0009 - это CCCD для системного сервиса (иногда путается)
            handles = ["0x0011", "0x0010", "0x0009"]
            
            for h in handles:
                print(f"🔑 [BRIDGE] Пробую активировать {h}...", file=sys.stderr)
                # Пробуем два разных способа записи
                child.sendline(f"char-write-req {h} 0100")
                time.sleep(0.3)
                child.sendline(f"char-write-cmd {h} 0100")
                time.sleep(0.3)

            print("📡 [BRIDGE] Перехожу в режим прослушки (listen)...", file=sys.stderr)
            child.sendline("listen")

            while True:
                # Ждем ЛЮБОЕ уведомление от устройства
                idx = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=15)
                
                if idx == 0:
                    hex_data = child.readline().decode().strip()
                    # Печатаем вообще всё, что прилетело, чтобы увидеть хоть что-то
                    print(f"📦 [RAW]: {hex_data}", file=sys.stderr) 
                    
                    try:
                        clean_hex = hex_data.replace(" ", "")
                        bytes_data = bytes.fromhex(clean_hex)
                        decoded = bytes_data.decode('utf-8', errors='ignore').strip()
                        
                        if "{" in decoded:
                            print(decoded)
                            sys.stdout.flush()
                    except:
                        pass
                
                if idx == 2:
                    print("❌ [BRIDGE] ESP32 отвалилась.", file=sys.stderr)
                    break
                    
                if idx == 1:
                    # Если долго нет данных, пробуем еще раз "пнуть" подписку
                    child.sendline("char-write-req 0x0011 0100")
        else:
            print("❌ [BRIDGE] Тайм-аут подключения.", file=sys.stderr)
            
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
        time.sleep(5)