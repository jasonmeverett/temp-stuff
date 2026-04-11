import asyncio
from bleak import BleakClient

ADDRESS = "6E00D83A-7480-3FCF-D7C5-7D89FBDD8974"

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