import bluetooth, machine, neopixel, json, time, random, os
from machine import Pin, I2C
import ahtx0, ens160 

# --- КОНСТАНТЫ ---
PIN_LED = 4
PIN_SDA = 21
PIN_SCL = 22
DEFAULT_LEDS = 300 # <--- ТЕПЕРЬ 300 ПО УМОЛЧАНИЮ
CONFIG_FILE = "config.json" 

# Bluetooth UUIDs
_SERVICE_UUID = bluetooth.UUID("4fafc201-1fb5-459e-8fcc-c5c9c331914b")
_CHAR_SENSOR  = (bluetooth.UUID("beb5483e-36e1-4688-b7f5-ea07361b26a8"), bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY)
_CHAR_LED     = (bluetooth.UUID("82258ba0-0557-4303-91ca-00dcc5703003"), bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
_SERVICE      = (_SERVICE_UUID, (_CHAR_SENSOR, _CHAR_LED),)

# --- КЛАСС ЛЕНТЫ ---
class VectorLed:
    def __init__(self, pin, num):
        self.pin = pin
        self.num = num
        self.np = neopixel.NeoPixel(Pin(pin), num)
        self.mode = "RAINBOW"
        self.color = (255, 165, 0)
        self.bright = 0.8
        self.speed = 50
        self.step = 0
        self.last_tick = 0

    def reconfig(self, new_num):
        if new_num != self.num:
            self.num = new_num
            self.np = neopixel.NeoPixel(Pin(self.pin), self.num)
            print(f"✨ Лента пересобрана: {self.num} LEDs")

    def wheel(self, pos):
        if pos < 85: return (pos * 3, 255 - pos * 3, 0)
        if pos < 170: pos -= 85; return (255 - pos * 3, 0, pos * 3)
        pos -= 170; return (0, pos * 3, 255 - pos * 3)

    def apply_bright(self, color):
        return tuple(int(c * self.bright) for c in color)

    def tick(self):
        now = time.ticks_ms()
        delay = 105 - self.speed 
        if time.ticks_diff(now, self.last_tick) < delay: return
        self.last_tick = now

        if self.mode == "OFF":
            self.np.fill((0,0,0))
        elif self.mode == "STATIC":
            self.np.fill(self.apply_bright(self.color))
        elif self.mode == "RAINBOW":
            for i in range(self.num):
                idx = (int(i * 256 / self.num) + self.step) & 255
                self.np[i] = self.apply_bright(self.wheel(idx))
            self.step = (self.step + 3) & 255
        elif self.mode == "METEOR":
            for i in range(self.num):
                c = self.np[i]
                self.np[i] = (int(c[0]*0.6), int(c[1]*0.6), int(c[2]*0.6))
            pos = self.step % self.num
            self.np[pos] = self.apply_bright(self.color)
            self.step += 1
        elif self.mode == "FIRE":
            for i in range(self.num):
                flicker = random.randint(0, 50)
                r = max(0, min(255, self.color[0] - flicker))
                g = max(0, min(255, self.color[1] - flicker))
                self.np[i] = self.apply_bright((r, g, 0))
        elif self.mode == "POLICE":
            c = (255, 0, 0) if (self.step // 5) % 2 == 0 else (0, 0, 255)
            self.np.fill(self.apply_bright(c))
            self.step += 1
        self.np.write()

# --- СИСТЕМА ---
class VectorSystem:
    def __init__(self):
        print("⚡ Инициализация VECTOR...")
        
        # 1. Загрузка конфига
        self.config = self.load_config()
        
        # ХАК: Если в памяти записано старое число (30), меняем на 300
        if self.config.get("leds", 0) < DEFAULT_LEDS:
             print("🔄 Обновляю старый конфиг до 300 LED...")
             self.config["leds"] = DEFAULT_LEDS
             self.led_num = DEFAULT_LEDS
             self.save_config() # Перезаписываем файл
        else:
             self.led_num = self.config.get("leds", DEFAULT_LEDS)

        # 2. I2C и Датчики
        self.i2c = I2C(0, scl=Pin(PIN_SCL), sda=Pin(PIN_SDA), freq=100000)
        time.sleep(1)
        devices = self.i2c.scan()
        
        self.aht = None
        if 0x38 in devices:
            try: self.aht = ahtx0.AHT10(self.i2c)
            except: pass
        
        self.ens = None
        if 0x53 in devices:
            try: self.ens = ens160.ENS160(self.i2c)
            except: pass

        # 3. Лента
        self.led = VectorLed(PIN_LED, self.led_num)
        # Восстанавливаем настройки
        self.led.mode = self.config.get("mode", "RAINBOW")
        self.led.speed = self.config.get("speed", 50)
        self.led.bright = self.config.get("bright", 0.8)
        if "color" in self.config:
            self.led.color = tuple(self.config["color"])

        # 4. Bluetooth
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self.ble_irq)
        ((self.h_sens, self.h_led),) = self.ble.gatts_register_services((_SERVICE,))
        self.advertise()
        print(f"📡 BLE STARTED (LEDs: {self.led.num})")

    def load_config(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {"leds": DEFAULT_LEDS, "mode": "RAINBOW"}

    def save_config(self):
        data = {
            "leds": self.led.num if hasattr(self, 'led') else DEFAULT_LEDS,
            "mode": self.led.mode if hasattr(self, 'led') else "RAINBOW",
            "speed": self.led.speed if hasattr(self, 'led') else 50,
            "bright": self.led.bright if hasattr(self, 'led') else 0.8,
            "color": self.led.color if hasattr(self, 'led') else (255,165,0)
        }
        # Если вызываем save до создания self.led (как в hack выше), используем self.config
        if not hasattr(self, 'led'):
             data.update(self.config)

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print("Save Err:", e)

    def ble_irq(self, event, data):
        if event == 1: print("🔗 Connected")
        elif event == 2: self.advertise()
        elif event == 3: 
            conn, handle = data
            if handle == self.h_led:
                self.handle_command(self.ble.gatts_read(handle))

    def advertise(self):
        name = "VECTOR_ESP32"
        adv = bytearray('\x02\x01\x06', 'utf-8') + bytearray([len(name)+1, 0x09]) + name.encode()
        self.ble.gap_advertise(100, adv)

    def handle_command(self, data):
        try:
            cmd = json.loads(data.decode())
            print("📩 CMD:", cmd)
            save = False

            if "config" in cmd:
                new_num = cmd["config"].get("num", self.led.num)
                if new_num != self.led.num:
                    self.led.reconfig(new_num)
                    save = True
            
            if "mode" in cmd: self.led.mode = cmd["mode"]; save=True
            if "color" in cmd: self.led.color = tuple(cmd["color"]); save=True
            if "speed" in cmd: self.led.speed = cmd["speed"]; save=True
            if "bright" in cmd: self.led.bright = cmd["bright"]; save=True
                
            if save: self.save_config()
        except: pass

    def loop(self):
        last_sensor_time = 0
        while True:
            self.led.tick()
            now = time.ticks_ms()
            if time.ticks_diff(now, last_sensor_time) > 3000:
                last_sensor_time = now
                self.read_sensors()
            time.sleep_ms(10)

    def read_sensors(self):
        t, h, co2 = 0, 0, 0
        if self.aht: 
            try: t, h = self.aht.read()
            except: pass
        if self.ens: 
            try: _, _, co2 = self.ens.read_all()
            except: pass
        if co2 == 0: co2 = 400
        payload = json.dumps({"temp": round(t, 1), "hum": int(h), "co2": int(co2)})
        try: self.ble.gatts_notify(0, self.h_sens, payload)
        except: pass 

# ЗАПУСК
sys = VectorSystem()
sys.loop()