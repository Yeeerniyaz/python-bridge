import subprocess
import os
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    # Твоя логика датчиков
    return jsonify({"temp": 25.5, "hum": 40, "co2": 450})

# ЭТОТ БЛОК НУЖЕН ДЛЯ ОБНОВЛЕНИЯ
@app.route('/api/system/update-python', methods=['POST'])
def update_python():
    try:
        # 1. Скачиваем новый код из Git
        subprocess.run(["git", "pull"], check=True)
        # 2. Перезапускаем службу (systemd сам поднимет процесс)
        os.system("sudo systemctl restart vector-bridge &")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005)