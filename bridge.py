import os
import subprocess
import sys
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Путь к директории проекта
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"

@app.route('/api/sensors', methods=['GET'])
def sensors():
    """Получение данных с датчиков"""
    return jsonify({
        "temp": 25.5, 
        "hum": 40, 
        "co2": 999, 
        "status": "online"
    })

@app.route('/api/wifi/list', methods=['GET'])
def list_wifi():
    """Сканирование доступных Wi-Fi сетей"""
    try:
        subprocess.run('sudo nmcli device wifi rescan', shell=True)
        time.sleep(2)
        cmd = "nmcli -t -f SSID,SIGNAL device wifi list | sort -u -t: -k1,1"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        networks = []
        for line in res.stdout.split('\n'):
            if line.strip() and ':' in line:
                ssid, signal = line.split(':')
                if ssid:
                    networks.append({'ssid': ssid, 'signal': signal})
        return jsonify(networks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/wifi/connect', methods=['POST'])
def connect_wifi():
    """Подключение к Wi-Fi"""
    data = request.json
    ssid = data.get('ssid')
    password = data.get('password')
    try:
        cmd = f'sudo nmcli device wifi connect "{ssid}" password "{password}"'
        subprocess.run(cmd, shell=True, check=True)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    """Обновление кода и датчиков"""
    try:
        # Переходим в папку с кодом
        os.chdir(WORKING_DIR)
        
        # 1. Скачиваем свежий код из GitHub
        subprocess.run(["git", "pull"], check=True)
        
        # 2. Перезапускаем сервис (фоновый процесс)
        # Мы используем nohup или & чтобы Flask успел вернуть ответ "success"
        os.system("sleep 1 && sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Code updated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    
@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    """Перезагрузка Raspberry Pi"""
    try:
        os.system("sleep 1 && sudo reboot &")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)