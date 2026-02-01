import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bleak import BleakClient, BleakScanner

# Настройки
TARGET_NAME = "VECTOR_FINAL"
UUID_SENS = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
UUID_LED  = "82258ba0-0557-4303-91ca-00dcc5703003"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] VECTOR: %(message)s")
logger = logging.getLogger("GW")

# Хранилище состояния
state = {
    "sensors": {"temp": 0, "hum": 0, "co2": 400},
    "status": "booting",
    "client": None,
    "lock": asyncio.Lock()
}

class LedCmd(BaseModel):
    mode: str
    color: list[int] | None = None
    speed: int | None = None
    bright: float | None = None

async def bt_manager():
    """Фоновый процесс, который вечно ищет и держит связь"""
    logger.info("🚀 Bluetooth Manager Started")
    
    while True:
        state["status"] = "scanning"
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and d.name == TARGET_NAME, timeout=10.0
        )

        if not device:
            logger.warning(f"❌ {TARGET_NAME} not found. Scan again...")
            await asyncio.sleep(3)
            continue

        logger.info(f"🔗 Connecting to {device.address}...")
        
        try:
            async with BleakClient(device) as client:
                state["client"] = client
                state["status"] = "connected"
                logger.info("✅ Connected!")

                # Функция приема данных
                def callback(sender, data):
                    try:
                        state["sensors"] = json.loads(data.decode())
                    except: pass
                
                await client.start_notify(UUID_SENS, callback)

                # Держим соединение, пока оно живо
                while client.is_connected:
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"⚠️ Connection Error: {e}")
        
        state["client"] = None
        state["status"] = "disconnected"
        logger.info("RESTARTING LOOP...")
        await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(bt_manager())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/sensors")
async def get_data():
    return {"data": state["sensors"], "status": state["status"]}

@app.post("/api/led")
async def send_cmd(cmd: LedCmd):
    client = state["client"]
    if not client or not client.is_connected:
        raise HTTPException(503, "Device not connected")
    
    async with state["lock"]:
        try:
            js = json.dumps(cmd.dict(exclude_none=True)).encode()
            # write_gatt_char(char, data, response=False) для скорости
            await client.write_gatt_char(UUID_LED, js, response=False)
            return {"status": "ok"}
        except Exception as e:
            raise HTTPException(500, str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5005)