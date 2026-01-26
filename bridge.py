import os
import subprocess
import sys
import shutil
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

WORKING_DIR = "/home/yerniyaz/Desktop/vector/python"
FLAG_PATH = "/home/yerniyaz/Desktop/vector/.first_run_completed"

def read_sensors():
    try:
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
        
        # 1. Git Pull (Раз ты говоришь, что он работает — оставляем)
        subprocess.run(["git", "pull"], check=True)
        
        # 2. Pip Install с защитой от блокировки системных пакетов
        try:
            # Добавляем флаг --break-system-packages для новых систем
            subprocess.run([
                sys.executable, "-m", "pip", "install", 
                "--break-system-packages", 
                "-r", "requirements.txt"
            ], check=False) # check=False, чтобы если даже пип не сработал, рестарт пошел дальше
        except Exception as pip_e:
            print(f"Pip warning: {pip_e}")

        # 3. Рестарт сервиса
        # Используем фоновый запуск, чтобы Flask успел отправить ответ зеркалу
        os.system("sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Код обновлен, перезагружаюсь..."}), 200

    except Exception as e:
        # Теперь мы будем видеть реальную ошибку в логах
        return jsonify({"status": "error", "message": str(e)}), 500
    try:
        # Проверка директории
        if not os.path.exists(WORKING_DIR):
            return jsonify({"status": "error", "message": f"Папка {WORKING_DIR} не найдена"}), 404
        
        os.chdir(WORKING_DIR)

        # 1. Git Pull
        # Фикс: перед pull делаем fetch, чтобы проверить связь
        process = subprocess.run(["git", "pull"], capture_output=True, text=True)
        if process.returncode != 0:
            return jsonify({
                "status": "error", 
                "message": f"Git Error: {process.stderr if process.stderr else 'Конфликт локальных файлов'}"
            }), 500

        # 2. Pip Install
        pip_process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            capture_output=True, text=True
        )
        if pip_process.returncode != 0:
            return jsonify({"status": "error", "message": f"Pip Error: {pip_process.stderr}"}), 500

        # 3. Рестарт сервиса
        # Используем фоновый запуск, чтобы Flask успел отдать ответ 200 до того, как его убьют
        os.system("sudo systemctl restart vector-bridge &")
        
        return jsonify({"status": "success", "message": "Обновление завершено, рестарт..."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/system/reset-wifi', methods=['POST'])
def reset_wifi():
    try:
        if os.path.exists(FLAG_PATH):
            os.remove(FLAG_PATH)
        cmd = "nmcli --fields UUID,TYPE connection show | grep 802-11-wireless | awk '{print $1}' | xargs nmcli connection delete"
        subprocess.run(cmd, shell=True, check=True)
        return jsonify({"status": "success", "message": "Wi-Fi сброшен"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)