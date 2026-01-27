import os
import subprocess
import sys
import time
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Конфигурация путей
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"
FLAG_PATH = "/home/yerniyaz/Desktop/vector/.first_run_completed"

def read_sensors():
    """Чтение данных с датчиков (заглушка для расширения)"""
    try:
        # Здесь будет твой реальный код для BME280/ENS160
        return {"temp": 25.5, "hum": 40, "co2": 999, "status": "online"}
    except Exception:
        return {"temp": "--", "hum": "--", "co2": "--", "status": "offline"}

@app.route('/api/sensors', methods=['GET'])
def sensors():
    return jsonify(read_sensors())

@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    try:
        if not os.path.exists(WORKING_DIR):
            return jsonify({"status": "error", "message": "Directory not found"}), 404
        
        os.chdir(WORKING_DIR)
        
        # 1. Обновление из репозитория
        subprocess.run(["git", "pull"], check=True)
        
        # 2. Установка зависимостей
        subprocess.run([
            sys.executable, "-m", "pip", "install", 
            "--break-system-packages", "-r", "requirements.txt"
        ], check=False)

        # 3. Перезапуск моста (этого самого скрипта) через 1 секунду
        os.system("sleep 1 && sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Python code updated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reset-wifi', methods=['POST'])
def reset_wifi():
    try:
        # 1. Удаляем метку завершения настройки
        if os.path.exists(FLAG_PATH):
            os.remove(FLAG_PATH)
        
        # 2. Удаляем сохраненные Wi-Fi сети (безопасно)
        cmd_get_uuids = "nmcli -t -f UUID,TYPE,NAME connection show | grep 802-11-wireless | grep -v 'Hotspot' | cut -d: -f1"
        try:
            uuids_output = subprocess.check_output(cmd_get_uuids, shell=True, text=True).strip()
            if uuids_output:
                for uuid in uuids_output.split('\n'):
                    subprocess.run(f"sudo nmcli connection delete {uuid}", shell=True)
        except Exception:
            pass # Если сетей нет, идем дальше

        # 3. Поднимаем точку доступа
        os.system("sudo systemctl restart NetworkManager")
        time.sleep(2)
        os.system("sudo nmcli connection up Hotspot &")
        
        return jsonify({"status": "success", "message": "Network reset. Hotspot active"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/restart-app', methods=['POST'])
def restart_app():
    try:
        # Перезагружаем фронтенд (Electron приложение)
        os.system("sleep 1 && sudo systemctl restart vector-app &") 
        return jsonify({"status": "success", "message": "Restarting interface..."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reboot', methods=['POST'])
def reboot_system():
    try:
        # Полная перезагрузка малинки
        os.system("sleep 1 && sudo reboot &") 
        return jsonify({"status": "success", "message": "System rebooting..."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Запуск на порту 5005
    app.run(host='0.0.0.0', port=5005, debug=False)