# Temperature monitoring

## TP920 localhost dashboard

On a Mac with Bluetooth enabled, turn on the ThermoPro TP920 and run these commands from the repository root.

```sh
uv sync --locked
npm ci
uv run --locked python tp920/server.py
```

Both probes update every 10 seconds. The **Bluetooth decoding** tab documents the device service, startup command, and packet format. [Open the local dashboard](http://localhost:8765/)

SQLite keeps the full recording in `tp920/data/readings.sqlite3`. Git ignores the entire `tp920/data/` directory.
