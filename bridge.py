import os
import subprocess
import sys
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Путь к папке на малинке (зафиксируем его)
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"

def read_sensors():
    try:
        # ТВОЙ КОД ДЛЯ ДАТЧИКОВ ТУТ
        return {"temp": 25.5, "hum": 40, "co2": 999, "status": "online"}
    except Exception as e:
        return {"temp": "--", "hum": "--", "co2": "--", "status": "offline"}

@app.route('/api/sensors', methods=['GET'])
def sensors():
    return jsonify(read_sensors())

@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    try:
        # 1. Переходим в нужную папку
        os.chdir(WORKING_DIR)
        import os
import subprocess
import sys
import shutil
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Путь к папке на малинке
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"
# Путь к файлу-флагу (должен совпадать с setup_portal.py)
FLAG_PATH = "/home/yerniyaz/Desktop/vector/.first_run_completed"

def read_sensors():
    try:
        # ТВОЙ КОД ДЛЯ ДАТЧИКОВ ТУТ
        return {"temp": 25.5, "hum": 40, "co2": 999, "status": "online"}
    except Exception as e:
        return {"temp": "--", "hum": "--", "co2": "--", "status": "offline"}

@app.route('/api/sensors', methods=['GET'])
def sensors():
    return jsonify(read_sensors())

@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    try:
        os.chdir(WORKING_DIR)
        subprocess.run(["git", "pull"], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        
        # Перезагружаем сервис через systemd
        os.system("sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Code updated, restarting..."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reset-wifi', methods=['POST'])
def reset_wifi():
    try:
        # 1. Удаляем флаг завершения настройки
        if os.path.exists(FLAG_PATH):
            os.remove(FLAG_PATH)
        
        # 2. Удаляем все сохраненные Wi-Fi соединения через nmcli
        # Находим UUID всех беспроводных соединений и удаляем их
        cmd = "nmcli --fields UUID,TYPE connection show | grep 802-11-wireless | awk '{print $1}' | xargs nmcli connection delete"
        subprocess.run(cmd, shell=True, check=True)
        
        return jsonify({"status": "success", "message": "Wi-Fi settings cleared"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)
        # 2. Обновляем код из Git
        subprocess.run(["git", "pull"], check=True)
        
        # 3. Установка новых библиотек из requirements.txt
        # Используем sys.executable, чтобы установилось именно в тот питон, который запущен
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        
        # 4. Перезагружаем сервис через systemd
        # Используем sudo, так как сервис системный
        os.system("sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Code and libs updated, restarting..."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)