import asyncio
import logging
import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bleak import BleakClient, BleakScanner, BleakError

# ===========================
# ⚙️ НАСТРОЙКИ (GATEWAY)
# ===========================
# ИЩЕМ ИМЕННО ЭТО ИМЯ!
TARGET_DEVICE_NAME = "VECTOR_FINAL" 

SENSOR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
LED_UUID    = "82258ba0-0557-4303-91ca-00dcc5703003"
API_PORT = 5005

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VECTOR_GATEWAY")

# ===========================
# 🧠 МОДЕЛИ
# ===========================
class LedCommand(BaseModel):
    mode: str
    color: list[int] | None = None
    speed: int | None = None
    bright: float | None = None

# ===========================
# 🦷 BLE BRIDGE (SCAN & CONNECT)
# ===========================
class VectorBridge:
    def __init__(self):
        self.client = None
        self.state = {
            "temp": 0.0, 
            "hum": 0, 
            "co2": 400, 
            "status": "booting", 
            "connected_to": None
        }
        self._lock = asyncio.Lock()

    async def _notification_handler(self, sender, data):
        try:
            decoded = json.loads(data.decode())
            self.state.update(decoded)
            self.state["status"] = "online"
        except: pass

    async def send_command(self, cmd: dict):
        if not self.client or not self.client.is_connected:
            raise HTTPException(status_code=503, detail="Not connected to VECTOR")
        
        async with self._lock:
            try:
                payload = json.dumps(cmd).encode()
                await self.client.write_gatt_char(LED_UUID, payload, response=False)
                logger.info(f"📤 SENT: {cmd}")
                return {"status": "ok"}
            except Exception as e:
                logger.error(f"Write Error: {e}")
                raise HTTPException(status_code=500, detail="BLE Write Failed")

    async def _find_device(self):
        """Сканирует эфир и ищет VECTOR_FINAL"""
        logger.info(f"🔍 SCANNING FOR: {TARGET_DEVICE_NAME}...")
        try:
            # Лямбда-фильтр: ищем устройство, у которого есть имя и оно совпадает
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name and d.name == TARGET_DEVICE_NAME,
                timeout=10.0
            )
            return device
        except Exception as e:
            logger.error(f"Scan Error: {e}")
            return None

    async def run_loop(self):
        logger.info("🚀 SERVICE STARTED")
        
        while True:
            # 1. СКАНИРОВАНИЕ
            self.state["status"] = "scanning"
            device = await self._find_device()

            if not device:
                logger.warning("❌ Device not found. Retrying in 5s...")
                await asyncio.sleep(5)
                continue

            # 2. ПОДКЛЮЧЕНИЕ
            logger.info(f"🔗 Found {device.name} [{device.address}]. Connecting...")
            
            try:
                async with BleakClient(device, timeout=15.0) as client:
                    self.client = client
                    self.state["status"] = "connected"
                    self.state["connected_to"] = device.address
                    
                    logger.info("✅ CONNECTED SUCCESSFULLY!")
                    
                    # Подписка
                    await client.start_notify(SENSOR_UUID, self._notification_handler)
                    
                    # Цикл удержания связи
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except Exception as e:
                logger.error(f"⚠️ Connection Lost/Failed: {e}")
                self.state["status"] = "disconnected"
                self.client = None
            
            # Пауза перед новым циклом поиска
            await asyncio.sleep(3)

bridge = VectorBridge()

# ===========================
# 🌐 FASTAPI
# ===========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(bridge.run_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

@app.get("/api/sensors")
async def get_sensors():
    return bridge.state

@app.post("/api/led")
async def control_led(cmd: LedCommand):
    return await bridge.send_command(cmd.model_dump(exclude_none=True))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)