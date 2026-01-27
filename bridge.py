import os
import subprocess
import sys
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
# Разрешаем CORS, чтобы React мог свободно общаться с Python
CORS(app)

# Путь к твоей рабочей директории на Raspberry Pi
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"

# --- ДАТЧИКИ ---
@app.route('/api/sensors', methods=['GET'])
def sensors():
    """Получение данных с датчиков (BME280/ENS160)"""
    # Здесь позже добавишь реальное чтение через библиотеку bme280/ens160
    return jsonify({
        "temp": 25.5, 
        "hum": 40, 
        "co2": 999, 
        "status": "online"
    })

# --- WI-FI ПАРАМЕТРЫ ---
@app.route('/api/wifi/list', methods=['GET'])
def list_wifi():
    """Сканирование доступных Wi-Fi сетей"""
    try:
        # Заставляем систему обновить список сетей
        subprocess.run('sudo nmcli device wifi rescan', shell=True)
        time.sleep(1.5)
        
        # Получаем SSID и уровень сигнала, убираем дубликаты
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
        # Подключаемся через nmcli
        cmd = f'sudo nmcli device wifi connect "{ssid}" password "{password}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "error", "message": result.stderr}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- ОБНОВЛЕНИЕ И СИСТЕМА ---
@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    """Обновление кода через Git и перезапуск моста"""
    try:
        if os.path.exists(WORKING_DIR):
            os.chdir(WORKING_DIR)
            # Тянем свежий код
            subprocess.run(["git", "pull"], check=True)
            
            # Перезапускаем сервис vector-bridge в фоне
            os.system("sleep 1 && sudo systemctl restart vector-bridge &")
            return jsonify({"status": "success", "message": "Обновление запущено"}), 200
        else:
            return jsonify({"status": "error", "message": "Директория не найдена"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    """Полная перезагрузка Raspberry Pi"""
    try:
        os.system("sleep 1 && sudo reboot &")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Запускаем на всех интерфейсах (0.0.0.0), порт 5005
    # debug=False предотвращает двойной запуск ресурсов
    app.run(host='0.0.0.0', port=5005, debug=False)