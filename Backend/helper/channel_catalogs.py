"""Add-only catalog membership from this installation's Telegram channel IDs."""
import asyncio

from Backend.helper.encrypt import decode_string
from Backend.logger import LOGGER

# Stable channel IDs from the user's Channel Scanner; names are existing catalogs.
CHANNEL_CATALOGS = {
    "4390174077": "Malaysian Dubbed",   # My Malay Dubbed
    "4393000264": "Indonesian Dubbed", # My Indonesia Dubbed
    "4428678722": "Anime Dubbed",      # My Ani Dub
}
SYNC_SECONDS = 60


def channel_key(value):
    value = str(value or "").strip()
    return value[4:] if value.startswith("-100") else value


def normal_name(value):
    return " ".join(str(value or "").casefold().split())


def qualities(doc):
    yield from doc.get("telegram") or []
    for season in doc.get("seasons") or []:
        for episode in season.get("episodes") or []:
            yield from episode.get("telegram") or []


async def source_channels(doc):
    channels = set()
    for quality in qualities(doc):
        for part in quality.get("parts") or []:
            channels.add(channel_key(part.get("chat_id")))
        encoded = quality.get("id")
        if not encoded:
            continue
        try:
            decoded = await decode_string(encoded)
        except Exception:
            # Old/unreadable stream IDs cannot be used as channel evidence.
            continue
        if not isinstance(decoded, dict):
            continue
        channels.add(channel_key(decoded.get("chat_id")))
        for part in decoded.get("parts") or []:
            if isinstance(part, dict):
                channels.add(channel_key(part.get("chat_id")))
    return channels.intersection(CHANNEL_CATALOGS)


def item_key(item, default_db=1, default_type="movie"):
    try:
        media_type = "tv" if item.get("media_type", default_type) in ("tv", "series") else "movie"
        return (int(item["tmdb_id"]), int(item.get("db_index", default_db)), media_type)
    except (KeyError, TypeError, ValueError):
        return None


async def sync_channel_catalogs(db):
    catalogs = await db.get_custom_catalogs()
    targets = {}
    for channel, name in CHANNEL_CATALOGS.items():
        hits = [c for c in catalogs if normal_name(c.get("name")) == normal_name(name)]
        if len(hits) != 1:
            LOGGER.warning("[Channel catalogs] Expected one catalog named %s; found %s. Skipping it.", name, len(hits))
            continue
        catalog = hits[0]
        # Do not change exclusivity or access settings as a side effect of grouping.
        if catalog.get("exclusive"):
            LOGGER.warning("[Channel catalogs] %s is exclusive; automatic grouping skipped.", name)
            continue
        targets[channel] = (catalog, {item_key(i) for i in catalog.get("items") or []})

    added = 0
    if not targets:
        return added
    projection = {"tmdb_id": 1, "telegram": 1, "seasons.episodes.telegram": 1,
                  "exclusive_catalog_id": 1}
    for db_key, storage in list(db.dbs.items()):
        if not db_key.startswith("storage_"):
            continue
        db_index = int(db_key.split("_", 1)[1])
        for media_type in ("movie", "tv"):
            async for doc in storage[media_type].find({}, projection):
                key = item_key(doc, db_index, media_type)
                if key is None:
                    continue
                for channel in await source_channels(doc):
                    if channel not in targets:
                        continue
                    catalog, known = targets[channel]
                    if key in known:
                        continue
                    catalog_id = str(catalog["_id"])
                    exclusive = doc.get("exclusive_catalog_id")
                    if exclusive and str(exclusive) != catalog_id:
                        continue
                    # Existing DB method copies per-title visibility and uses an atomic
                    # not-already-present condition, so repeated runs do not duplicate.
                    if await db.add_item_to_custom_catalog(catalog_id, key[0], db_index, media_type):
                        known.add(key)
                        added += 1
    return added


async def run_channel_catalog_sync(db):
    first = True
    while True:
        try:
            added = await sync_channel_catalogs(db)
            if first or added:
                LOGGER.info("[Channel catalogs] Sync complete: added %s missing memberships.", added)
            first = False
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("[Channel catalogs] Sync failed; will retry next minute.")
        await asyncio.sleep(SYNC_SECONDS)
