"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
INDEXES: dict[str, list[IndexModel]] = {
    "status_checks": [IndexModel([("timestamp", DESCENDING)], name="timestamp_desc")],
    "stores": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("created_at", ASCENDING)], name="created_at_asc"),
    ],
    "orders": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("store_id", ASCENDING), ("created_at", DESCENDING)], name="store_created"),
        IndexModel([("tracking_token", ASCENDING)], name="tracking_token"),
        IndexModel([("motoboy_share_token", ASCENDING)], name="motoboy_share_token"),
    ],
    "chat_messages": [
        IndexModel([("store_id", ASCENDING), ("session_id", ASCENDING), ("created_at", ASCENDING)],
                   name="store_session_created"),
    ],
    "users": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("email", ASCENDING)], name="email", unique=True),
        IndexModel([("store_id", ASCENDING)], name="store_id"),
    ],
    "payment_intents": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("store_id", ASCENDING), ("created_at", DESCENDING)], name="store_created"),
        IndexModel([("provider_payment_id", ASCENDING)], name="provider_payment_id"),
    ],
    "webhook_events": [
        IndexModel([("event_key", ASCENDING)], name="event_key", unique=True),
    ],
    "login_attempts": [
        IndexModel([("email", ASCENDING)], name="email", unique=True),
    ],
    "routes": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("store_id", ASCENDING), ("created_at", DESCENDING)], name="store_created"),
    ],
    "opt_outs": [
        IndexModel([("store_id", ASCENDING), ("chat_id", ASCENDING)], name="store_chat", unique=True),
    ],
    "motoboys": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("store_id", ASCENDING), ("ativo", ASCENDING)], name="store_ativo"),
    ],
    "locations": [
        IndexModel([("order_id", ASCENDING), ("at", DESCENDING)], name="order_at"),
    ],
    "notes": [
        IndexModel([("store_id", ASCENDING), ("at", DESCENDING)], name="store_at"),
    ],
    "push_subs": [
        IndexModel([("order_id", ASCENDING), ("endpoint", ASCENDING)], name="order_endpoint", unique=True),
    ],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
