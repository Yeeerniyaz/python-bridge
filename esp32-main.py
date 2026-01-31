import bluetooth, machine, neopixel, json, time, random, gc
from machine import Pin, I2C
import ahtx0, ens160 

# --- НАСТРОЙКИ ---
PIN_LED = 4
PIN_SDA = 21
PIN_SCL = 22
DEFAULT_LEDS = 30 

# Bluetooth UUIDs
_SERVICE_UUID = bluetooth.UUID("4fafc201-1fb5-459e-8fcc-c5c9c331914b")
_CHAR_SENSOR  = (bluetooth.UUID("beb5483e-36e1-4688-b7f5-ea07361b26a8"), bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY)
_CHAR_LED     = (bluetooth.UUID("82258ba0-0557-4303-91ca-00dcc5703003"), bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
_SERVICE      = (_SERVICE_UUID, (_CHAR_SENSOR, _CHAR_LED),)

# --- КЛАСС УПРАВЛЕНИЯ ЛЕНТОЙ ---
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

# --- ОСНОВНОЙ КЛАСС СИСТЕМЫ ---
class VectorSystem:
    def __init__(self):
        print("⚡ Инициализация...")
        
        # 1. I2C и Диагностика
        self.i2c = I2C(0, scl=Pin(PIN_SCL), sda=Pin(PIN_SDA), freq=100000)
        time.sleep(1) # Даем датчикам проснуться после подачи питания
        
        # Сканируем шину перед запуском драйверов
        devices = self.i2c.scan()
        print(f"🔍 I2C Сканирование: {[hex(d) for d in devices]}")

        # 2. Подключаем AHT120
        self.aht = None
        if 0x38 in devices:
            try:
                self.aht = ahtx0.AHT10(self.i2c)
                print("✅ AHT120 подключен")
            except Exception as e:
                print(f"⚠️ Ошибка AHT: {e}")
        else:
            print("❌ AHT120 (0x38) не найден!")

        # 3. Подключаем ENS160
        self.ens = None
        if 0x53 in devices:
            try:
                self.ens = ens160.ENS160(self.i2c)
                print("✅ ENS160 подключен")
            except Exception as e:
                print(f"⚠️ Ошибка ENS: {e}")
        else:
            print("❌ ENS160 (0x53) не найден!")

        # 4. Лента
        self.led = VectorLed(PIN_LED, DEFAULT_LEDS)

        # 5. Bluetooth
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self.ble_irq)
        ((self.h_sens, self.h_led),) = self.ble.gatts_register_services((_SERVICE,))
        self.advertise()
        print("📡 VECTOR BLE STARTED")

    def ble_irq(self, event, data):
        if event == 1: print("🔗 Connected")
        elif event == 2: 
            print("📴 Disconnected -> Restarting Adv")
            self.advertise()
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
            if "config" in cmd:
                self.led.reconfig(cmd["config"].get("num", self.led.num))
            self.led.mode = cmd.get("mode", self.led.mode)
            self.led.color = tuple(cmd.get("color", self.led.color))
            self.led.bright = cmd.get("bright", self.led.bright)
            self.led.speed = cmd.get("speed", self.led.speed)
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
        
        # Читаем AHT
        if self.aht:
            try:
                t, h = self.aht.read()
            except: pass
            
        # Читаем ENS
        if self.ens:
            try:
                _, _, co2 = self.ens.read_all()
                if co2 == 0: co2 = 400
            except: pass
        
        payload = json.dumps({"temp": round(t, 1), "hum": int(h), "co2": int(co2)})
        try:
            self.ble.gatts_notify(0, self.h_sens, payload)
        except: pass 

# ЗАПУСК
sys = VectorSystem()
sys.loop()
