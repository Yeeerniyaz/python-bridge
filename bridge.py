import os
import subprocess
import sys
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Путь к рабочей директории
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"

@app.route('/api/sensors', methods=['GET'])
def sensors():
    """Чтение данных с датчиков (заглушка)"""
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
        # Принудительное сканирование
        subprocess.run('sudo nmcli device wifi rescan', shell=True)
        time.sleep(2)
        
        # Получение списка SSID и уровня сигнала
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
    """Подключение к выбранной Wi-Fi сети"""
    data = request.json
    ssid = data.get('ssid')
    password = data.get('password')
    try:
        # Попытка подключения
        cmd = f'sudo nmcli device wifi connect "{ssid}" password "{password}"'
        subprocess.run(cmd, shell=True, check=True)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    """Полная перезагрузка системы Raspberry Pi"""
    try:
        # Задержка 1 сек, чтобы Flask успел отправить ответ
        os.system("sleep 1 && sudo reboot &")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Запуск сервера на порту 5005
    app.run(host='0.0.0.0', port=5005, debug=False)