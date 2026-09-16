"""
ZapPedidos + LAD Tracker — server principal
Base modular (lib/*, models/*, routers/*) do painel antigo mesclada com o tracker novo.
Auth: cookie httpOnly `zp_session` (ver lib/auth.py).
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, FastAPI  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

from lib.auth import ensure_admin_seed  # noqa: E402
from lib.db import client, ensure_indexes  # noqa: E402
from routers import admin, auth, orders, store, tracking  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("server")

app = FastAPI(title="ZapPedidos + LAD Tracker")
api = APIRouter(prefix="/api")
for r in (auth.router, admin.router, store.router, store.webhook_router, orders.router, tracking.router):
    api.include_router(r)


@api.get("/health")
async def health():
    return {"ok": True}


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await ensure_admin_seed()
    logger.info("ZapPedidos + Tracker API up. LAD=%s", os.environ.get("LAD_BASE_URL"))


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
