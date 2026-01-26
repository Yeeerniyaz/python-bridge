import os
import subprocess
import sys
import shutil
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Пути
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"
FLAG_PATH = "/home/yerniyaz/Desktop/vector/.first_run_completed"

def read_sensors():
    try:
        # Твой код датчиков
        return {"temp": 25.5, "hum": 40, "co2": 999, "status": "online"}
    except Exception as e:
        return {"temp": "--", "hum": "--", "co2": "--", "status": "offline"}

@app.route('/api/sensors', methods=['GET'])
def sensors():
    return jsonify(read_sensors())

@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    try:
        if not os.path.exists(WORKING_DIR):
            return jsonify({"status": "error", "message": "Папка не найдена"}), 404
        
        os.chdir(WORKING_DIR)
        
        # 1. Git Pull
        subprocess.run(["git", "pull"], check=True)
        
        # 2. Pip Install (с флагом для новых систем)
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", 
                "--break-system-packages", "-r", "requirements.txt"
            ], check=False)
        except:
            pass

        # 3. Рестарт сервиса в фоне
        os.system("sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Код обновлен, перезагружаюсь..."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reset-wifi', methods=['POST'])
def reset_wifi():
    try:
        # 1. Удаляем флаг
        if os.path.exists(FLAG_PATH):
            os.remove(FLAG_PATH)
        
        # 2. Удаляем все Wi-Fi кроме Hotspot
        cmd = "nmcli -t -f UUID,TYPE,NAME connection show | grep 802-11-wireless | grep -v 'Hotspot' | cut -d: -f1"
        try:
            uuids = subprocess.check_output(cmd, shell=True, text=True).strip().split('\n')
            for uuid in uuids:
                if uuid:
                    subprocess.run(f"sudo nmcli connection delete {uuid}", shell=True)
        except:
            pass

        # 3. ПЕРЕЗАПУСК СЕТИ (чтобы точка доступа точно заработала)
        os.system("sudo systemctl restart NetworkManager")
        time.sleep(2)
        subprocess.run("sudo nmcli connection up Hotspot", shell=True)
        
        return jsonify({"status": "success", "message": "Wi-Fi reset, Hotspot starting"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)