import os
import subprocess
import sys
import time
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"
FLAG_PATH = "/home/yerniyaz/Desktop/vector/.first_run_completed"

@app.route('/api/sensors', methods=['GET'])
def sensors():
    return jsonify({"temp": 25.5, "hum": 40, "co2": 999, "status": "online"})

@app.route('/api/system/restart-app', methods=['POST'])
def restart_app():
    # Отправляем ответ и через секунду перезапускаем сервис
    os.system("sleep 1 && sudo systemctl restart vector-app &")
    return jsonify({"status": "success"}), 200

@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    # Полная перезагрузка малинки
    os.system("sleep 1 && sudo reboot &")
    return jsonify({"status": "success"}), 200

@app.route('/api/system/reset-wifi', methods=['POST'])
def reset_wifi():
    try:
        if os.path.exists(FLAG_PATH):
            os.remove(FLAG_PATH)
        
        # Полная очистка всех Wi-Fi соединений (кроме Hotspot)
        cmd = "nmcli -t -f UUID,TYPE connection show | grep 802-11-wireless | grep -v 'Hotspot' | cut -d: -f1"
        try:
            uuids = subprocess.check_output(cmd, shell=True, text=True).strip().split('\n')
            for uuid in uuids:
                if uuid:
                    subprocess.run(f"sudo nmcli connection delete {uuid}", shell=True)
        except:
            pass

        # Рестарт сети и активация точки доступа
        os.system("sudo systemctl restart NetworkManager")
        time.sleep(2)
        os.system("sudo nmcli connection up Hotspot &")
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005)