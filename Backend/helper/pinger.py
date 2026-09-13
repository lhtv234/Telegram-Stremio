import asyncio
import traceback
from urllib.parse import urlsplit

import aiohttp

from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER


#----- Periodically self-ping the stats endpoint to keep the instance awake
async def ping():
    sleep_time = 1200

    while True:
        await asyncio.sleep(sleep_time)
        try:
            base = (SettingsManager.current().base_url or "").strip().rstrip("/")
            if urlsplit(base).scheme not in ("http", "https") or not urlsplit(base).hostname:
                LOGGER.warning("Ping skipped: set Base URL to the full http(s) server address")
                continue
            manifest_url = f"{base}/api/system/stats"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(manifest_url) as resp:
                    LOGGER.info(f"Pinged manifest URL — Status: {resp.status}")
        except asyncio.TimeoutError:
            LOGGER.warning("Timeout: Could not connect to manifest URL.")
        except Exception:
            LOGGER.error("Ping failed:\n" + traceback.format_exc())
