import pexpect
import sys
import time

MAC = "14:33:5C:C0:5C:BA"

def connect_attempt(addr_type):
    print(f"📡 [BRIDGE] Пробую тип адреса: {addr_type}...", file=sys.stderr)
    # Запускаем без лишних флагов на старте
    cmd = f"gatttool -b {MAC} -t {addr_type} --interactive"
    child = pexpect.spawn(cmd)
    
    try:
        child.expect(r"\[LE\]>", timeout=5)
        child.sendline("connect")
        
        # Ждем коннекта
        index = child.expect(["Connection successful", "Error", pexpect.TIMEOUT], timeout=10)
        
        if index == 0:
            print("✅ [BRIDGE] ЕСТЬ КОННЕКТ!", file=sys.stderr)
            # Включаем уведомления (UUID характеристики TX на твоей ESP32 может иметь другой handle)
            # Мы просто подпишемся на всё через "listen"
            child.sendline("char-write-req 0x0001 0100") 
            
            while True:
                idx = child.expect(["Notification handle = 0x[0-9a-f]+ value: ", pexpect.TIMEOUT, pexpect.EOF], timeout=5)
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
            print(f"❌ [BRIDGE] Не удалось подключиться через {addr_type}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ [BRIDGE] Ошибка: {e}", file=sys.stderr)
    finally:
        child.close()

if __name__ == "__main__":
    while True:
        # Пробуем по очереди оба типа адреса
        for t in ["public", "random"]:
            connect_attempt(t)
            time.sleep(2)
        print("🔄 [BRIDGE] Рестарт цикла поиска...", file=sys.stderr)
        time.sleep(3)