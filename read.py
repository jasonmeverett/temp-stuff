



import asyncio
from bleak import BleakClient

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
READ_UUID = "0000ff03-0000-1000-8000-00805f9b34fb"

def handle(sender, data):
    print("Notification:", data, list(data))

async def run():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)

        value = await client.read_gatt_char(READ_UUID)
        print("Read:", value, list(value))

asyncio.run(run())