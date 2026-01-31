import time
from machine import I2C

class AHT10:
    def __init__(self, i2c, address=0x38):
        self.i2c = i2c
        self.address = address
        self.buf = bytearray(6)
        time.sleep(0.1) # Пауза на включение
        
        # 1. Сброс (Soft Reset)
        try:
            self.i2c.writeto(self.address, b'\xBA')
            time.sleep(0.02)
        except OSError:
            pass # Если не ответил на сброс — не страшно

        # 2. Инициализация (Пробуем AHT10, если нет — AHT20)
        # Команда 0xE1 - для AHT10, 0xBE - для AHT20/21
        if not self._calibrate(0xE1): 
            self._calibrate(0xBE)

    def _calibrate(self, cmd):
        try:
            # Отправляем команду инициализации и параметры 0x08, 0x00
            self.i2c.writeto(self.address, bytes([cmd, 0x08, 0x00]))
            time.sleep(0.01)
            return True
        except OSError:
            return False

    def trigger(self):
        # Запуск измерения
        self.i2c.writeto(self.address, b'\xAC\x33\x00')
        time.sleep(0.08)

    def read(self):
        try:
            self.trigger()
            self.i2c.readfrom_into(self.address, self.buf)
            
            # Проверка бита занятости (Bit 7)
            if (self.buf[0] & 0x80):
                time.sleep(0.02) # Если занят, ждем еще чуть-чуть
            
            # Расчет влажности и температуры
            hum = ((self.buf[1] << 12) | (self.buf[2] << 4) | (self.buf[3] >> 4)) * 100 / 0x100000
            temp = (((self.buf[3] & 0xF) << 16) | (self.buf[4] << 8) | self.buf[5]) * 200 / 0x100000 - 50
            
            return temp, hum
        except OSError:
            return 0, 0
