"""Helpers compartilhados do tracker: geo, push, planos, sessão e guards de loja."""
from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, HTTPException, Response
from pywebpush import WebPushException, webpush

from lib.auth import COOKIE_NAME, User, current_user, make_token
from lib.db import db

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_CLAIM_EMAIL", "mailto:noreply@zappedidos.com")}
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
PUSH_RADIUS_KM = 0.5

ORDER_STATUSES = {"pending", "preparing", "dispatched", "delivered", "canceled"}

PLAN_QUOTAS = {
    "free": {"max_motoboys": 2, "max_orders_month": 50, "label": "Free"},
    "basic": {"max_motoboys": 5, "max_orders_month": 500, "label": "Basic"},
    "pro": {"max_motoboys": 999, "max_orders_month": 999999, "label": "Pro"},
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def haversine_km(a, b) -> float:
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        key=COOKIE_NAME, value=make_token(user), max_age=7 * 24 * 3600,
        httponly=True, secure=COOKIE_SECURE, samesite="none" if COOKIE_SECURE else "lax", path="/",
    )


async def geocode(query: str):
    if not query:
        return None
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "zappedidos-tracker/1.0"}) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search",
                            params={"q": query, "format": "json", "limit": 1, "countrycodes": "br"})
            if r.status_code == 200 and r.json():
                d = r.json()[0]
                return float(d["lat"]), float(d["lon"])
    except Exception:
        pass
    return None


def send_push(sub: Dict[str, Any], title: str, body: str, url: str) -> bool:
    if not VAPID_PRIVATE_KEY:
        return False
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=_json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims=dict(VAPID_CLAIMS),
        )
        return True
    except (WebPushException, Exception):
        return False


async def require_store(user: User = Depends(current_user)) -> User:
    if not user.store_id:
        raise HTTPException(403, "Requer loja")
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0, "ativa": 1})
    if not s:
        raise HTTPException(404, "Loja não encontrada")
    if s.get("ativa") is False:
        raise HTTPException(403, "Loja desativada. Fale com o revendedor.")
    return user


async def get_store(store_id: Optional[str]) -> Dict[str, Any]:
    s = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Loja não encontrada")
    return s


def store_lad_ready(s: Dict[str, Any]) -> bool:
    return bool(s.get("lad_token") or s.get("lad_demo"))
