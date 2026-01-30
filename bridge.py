import time
import threading
import board
import busio
import adafruit_ahtx0
import adafruit_ens160
from flask import Flask, jsonify, request
from flask_cors import CORS
from rpi_ws281x import PixelStrip, Color

# --- 1. УНИВЕРСАЛЬНАЯ НАСТРОЙКА ---
# Ставим 300 - этого хватит на любое зеркало.
# Лишние данные просто игнорируются лентой.
LED_COUNT = 300       
LED_PIN = 21          # GPIO 21 (Пин 40)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 255
LED_INVERT = False
LED_CHANNEL = 0       

# Инициализация ленты
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
try:
    strip.begin()
    print(f"✅ LED Strip initialized (Max: {LED_COUNT})")
except Exception as e:
    print(f"⚠️ LED Error (Run with sudo!): {e}")

# --- 2. ДАТЧИКИ ---
sensor_data = {"temp": 0, "hum": 0, "co2": 0, "aqi": 0, "status": "init"}

def init_sensors():
    try:
        i2c = board.I2C()
        aht = adafruit_ahtx0.AHTx0(i2c)
        ens = adafruit_ens160.ENS160(i2c)
        ens.aqi_mode = adafruit_ens160.AQI_MODE_STANDARD
        return aht, ens
    except Exception as e:
        print(f"❌ Sensor Init Error: {e}")
        return None, None

def sensor_loop():
    global sensor_data
    aht, ens = init_sensors()
    while True:
        try:
            if aht and ens:
                sensor_data = {
                    "temp": round(aht.temperature, 1),
                    "hum": round(aht.relative_humidity, 1),
                    "co2": ens.eCO2,
                    "aqi": ens.AQI,
                    "status": "active"
                }
            else:
                sensor_data["status"] = "sensor_error"
                if int(time.time()) % 60 == 0: aht, ens = init_sensors()
        except Exception as e:
            print(f"⚠️ Read Error: {e}")
            sensor_data["status"] = "read_error"
        time.sleep(3)

threading.Thread(target=sensor_loop, daemon=True).start()

# --- 3. FLASK API ---
app = Flask(__name__)
CORS(app)

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(sensor_data)

@app.route('/api/led', methods=['POST'])
def set_led():
    try:
        data = request.json
        state = data.get('state', 'OFF')
        color_hex = data.get('color', '#FFFFFF')

        if state == 'OFF':
            color = Color(0, 0, 0)
        else:
            h = color_hex.lstrip('#')
            r, g, b = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
            color = Color(r, g, b)

        # Заливаем все 300 пикселей.
        # Если у тебя физически их меньше, лишние просто не зажгутся.
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, color)
        strip.show()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    os.system("sleep 1 && sudo reboot &")
    return jsonify({"status": "rebooting"}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False, use_reloader=False)