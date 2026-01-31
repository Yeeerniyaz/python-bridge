import time
from machine import I2C

class ENS160:
    def __init__(self, i2c, addr=0x53):
        self.i2c = i2c
        self.addr = addr
        self.reset()
        self.set_mode(0x02) # Standard mode

    def _write(self, reg, data):
        self.i2c.writeto_mem(self.addr, reg, bytes([data]))

    def _read(self, reg, count=1):
        return self.i2c.readfrom_mem(self.addr, reg, count)

    def reset(self):
        # Сброс через переключение режимов
        self._write(0x10, 0x02) 
        time.sleep(0.1)
        self._write(0x10, 0x00) # Idle
        time.sleep(0.1)

    def set_mode(self, mode):
        self._write(0x10, mode)
        time.sleep(0.1)

    def read_all(self):
        # Читаем статус, AQI, TVOC, eCO2
        data = self._read(0x20, 8)
        aqi = data[1] & 0x07
        tvoc = (data[2] | (data[3] << 8))
        eco2 = (data[4] | (data[5] << 8))
        return aqi, tvoc, eco2
