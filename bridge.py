import asyncio
import threading
import queue
import sys
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from bleak import BleakScanner, BleakClient

# ===========================
# ⚙️ НАСТРОЙКИ (Сенің ESP32 кодыңа дәлме-дәл)
# ===========================
TARGET_NAME = "Vector_Party"  #

# UUID (Nordic UART Service)
# Python ESP32-нің RX (Write) сипаттамасына жазуы керек
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E" 
# Python ESP32-нің TX (Notify) сипаттамасын тыңдауы керек
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

API_PORT = 5000 

# ===========================
# 🌐 FLASK SERVER (API)
# ===========================
app = Flask(__name__)
CORS(app) # Electron-ға рұқсат

cmd_queue = queue.Queue()
system_status = {"status": "starting", "device": None}

@app.route('/cmd', methods=['POST'])
def send_cmd():
    """Electron осы жерге { "cmd": "FIRE" } жібереді"""
    try:
        content = request.json
        command = content.get('cmd')
        
        # Егер түс жіберілсе: { "cmd": "COLOR", "color": [255, 0, 0] }
        if command == "COLOR" and "color" in content:
            # JSON қылып жібереміз
            json_cmd = json.dumps({"color": content["color"]})
            cmd_queue.put(json_cmd)
            return jsonify({"status": "ok", "msg": f"Color sent: {content['color']}"})
            
        elif command:
            # Жай команда: FIRE, OFF, RAINBOW
            print(f"🌍 API: Команда қабылданды -> {command}")
            cmd_queue.put(command)
            return jsonify({"status": "ok", "msg": f"Command sent: {command}"})
            
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 400

    return jsonify({"status": "error", "msg": "No command provided"}), 400

@app.route('/status', methods=['GET'])
def get_status():
    """Electron байланыс бар-жоғын тексереді"""
    return jsonify(system_status)

# ===========================
# 🦷 BLUETOOTH LOOP
# ===========================

def notification_handler(sender, data):
    """ESP32-ден бірдеңе келсе (Мысалы 'OK')"""
    try:
        text = data.decode('utf-8').strip()
        print(f"📥 [ESP32]: {text}")
    except: pass

async def run_ble_client():
    print(f"🚀 [BLE] Іске қосылды. '{TARGET_NAME}' іздеудемін...", file=sys.stderr)
    
    while True:
        target_device = None
        system_status["status"] = "scanning"
        
        # 1. ІЗДЕУ (SCAN)
        devices = await BleakScanner.discover(timeout=5.0)
        for d in devices:
            # Аты 'Vector_Party' ма?
            if d.name and TARGET_NAME in d.name:
                print(f"🎯 ТАБЫЛДЫ: {d.name} [{d.address}]", file=sys.stderr)
                target_device = d
                break
        
        if not target_device:
            print("⏳ Күтуде... (ESP32 қосулы ма?)", file=sys.stderr)
            await asyncio.sleep(2)
            continue

        # 2. ҚОСЫЛУ (CONNECT)
        print(f"🔗 Қосылып жатырмын...", file=sys.stderr)
        try:
            async with BleakClient(target_device.address) as client:
                print(f"✅ [BLE] БАЙЛАНЫС ОРНАДЫ!", file=sys.stderr)
                system_status["status"] = "connected"
                system_status["device"] = target_device.address

                # Жауаптарды тыңдау
                try:
                    await client.start_notify(NOTIFY_UUID, notification_handler)
                except Exception as e:
                    print(f"⚠️ Notify қатесі: {e}")

                # 3. ЖҰМЫС ЦИКЛІ (Команда жіберу)
                while client.is_connected:
                    if not cmd_queue.empty():
                        cmd = cmd_queue.get()
                        print(f"⚡ [SEND] -> {cmd}")
                        
                        # ESP32-ге жібереміз (UTF-8 encode)
                        await client.write_gatt_char(WRITE_UUID, cmd.encode('utf-8'))
                    
                    await asyncio.sleep(0.05) # Процессорды босқа жүктемеу үшін
                
                print("❌ [BLE] Үзіліп қалды. Қайта іздеймін...", file=sys.stderr)
                system_status["status"] = "disconnected"

        except Exception as e:
            print(f"⚠️ [ERROR] Bluetooth қатесі: {e}", file=sys.stderr)
            await asyncio.sleep(3)

# ===========================
# 🚀 НЕГІЗГІ СТАРТ
# ===========================

def start_flask():
    # Flask-ты бөлек потокта ашамыз
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    # 1. Flask серверін қосамыз (Фонда)
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()
    print(f"🌍 [API] Сервер дайын: http://localhost:{API_PORT}")

    # 2. Bluetooth (Bleak) негізгі процессте жұмыс істейді
    try:
        asyncio.run(run_ble_client())
    except KeyboardInterrupt:
        print("\n👋 Сау бол!")