import asyncio
import threading
import queue
import sys
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from bleak import BleakScanner, BleakClient

# ===========================
# ⚙️ НАСТРОЙКИ
# ===========================
TARGET_NAME = "Vector_Party"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
API_PORT = 5000 

# ===========================
# 🌐 FLASK SERVER
# ===========================
app = Flask(__name__)
CORS(app)

cmd_queue = queue.Queue()
system_status = {"status": "starting", "device": None}

@app.route('/cmd', methods=['POST'])
def send_cmd():
    try:
        content = request.json
        command = content.get('cmd')
        if command == "COLOR" and "color" in content:
            json_cmd = json.dumps({"color": content["color"]})
            cmd_queue.put(json_cmd)
            return jsonify({"status": "ok", "msg": f"Color sent: {content['color']}"})
        elif command:
            print(f"🌍 API: Команда -> {command}")
            cmd_queue.put(command)
            return jsonify({"status": "ok", "msg": f"Command sent: {command}"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 400
    return jsonify({"status": "error", "msg": "No command"}), 400

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify(system_status)

# ===========================
# 🦷 BLUETOOTH LOOP
# ===========================

def notification_handler(sender, data):
    try:
        text = data.decode('utf-8').strip()
        print(f"📥 [ESP32]: {text}")
    except: pass

async def run_ble_client():
    print(f"🚀 [BLE] Іске қосылды. '{TARGET_NAME}' іздеудемін...", file=sys.stderr)
    
    while True:
        target_device = None
        system_status["status"] = "scanning"
        
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            for d in devices:
                if d.name and TARGET_NAME in d.name:
                    print(f"🎯 ТАБЫЛДЫ: {d.name} [{d.address}]", file=sys.stderr)
                    target_device = d
                    break
            
            if not target_device:
                print("⏳ Құрылғы табылмады, қайта іздеймін...", file=sys.stderr)
                await asyncio.sleep(2)
                continue

            print(f"🔗 Қосылып жатырмын...", file=sys.stderr)
            
            # Timeout-ты көбейтеміз (20 секунд)
            async with BleakClient(target_device.address, timeout=20.0) as client:
                print(f"✅ [BLE] БАЙЛАНЫС ОРНАДЫ! (Services resolving...)", file=sys.stderr)
                
                # МАҢЫЗДЫ: Қосылған соң сәл күтеміз, ESP өзіне келсін
                await asyncio.sleep(1.0)
                
                system_status["status"] = "connected"
                system_status["device"] = target_device.address

                try:
                    await client.start_notify(NOTIFY_UUID, notification_handler)
                except Exception as e:
                    print(f"⚠️ Notify қосылмады: {e}")

                while client.is_connected:
                    if not cmd_queue.empty():
                        cmd = cmd_queue.get()
                        print(f"⚡ [SEND] -> {cmd}")
                        await client.write_gatt_char(WRITE_UUID, cmd.encode('utf-8'))
                    
                    await asyncio.sleep(0.1) # PC процессорын босатамыз
                
                print("❌ [BLE] Үзіліп қалды.", file=sys.stderr)
                system_status["status"] = "disconnected"

        except Exception as e:
            print(f"⚠️ [ERROR] Қате: {e}", file=sys.stderr)
            # Егер қате шықса, Bluetooth адаптерін "есін жиғызу" үшін сәл күтеміз
            await asyncio.sleep(3)

# ===========================
# 🚀 START
# ===========================
def start_flask():
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()
    print(f"🌍 [API] Server: http://localhost:{API_PORT}")

    try:
        asyncio.run(run_ble_client())
    except KeyboardInterrupt:
        print("\n👋 Bye!")