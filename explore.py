import asyncio
from bleak import BleakClient

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"

async def explore():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)

        services = client.services
        for service in services:
            print(f"\n[Service] {service.uuid}")
            for char in service.characteristics:
                print(f"  [Characteristic] {char.uuid}")
                print(f"    Properties: {char.properties}")

asyncio.run(explore())