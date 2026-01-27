import os
import subprocess
import time
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
# Разрешаем CORS для связи с React
CORS(app)

# Путь к рабочей директории на Raspberry Pi
WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"

# --- ДАТЧИКИ ---
@app.route('/api/sensors', methods=['GET'])
def sensors():
    """Получение данных с датчиков (BME280/ENS160)"""
    # Здесь позже добавишь реальное чтение через библиотеки
    return jsonify({
        "temp": 25.5, 
        "hum": 40, 
        "co2": 999, 
        "status": "online"
    })

# --- ОБНОВЛЕНИЕ И СИСТЕМА ---
@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    """Обновление кода через Git и перезапуск моста"""
    try:
        if os.path.exists(WORKING_DIR):
            os.chdir(WORKING_DIR)
            # Тянем свежий код из GitHub
            subprocess.run(["git", "pull"], check=True)
            
            # Перезапускаем сервис в фоне, чтобы Flask успел вернуть ответ
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
    # Запускаем на порту 5005
    app.run(host='0.0.0.0', port=5005, debug=False)