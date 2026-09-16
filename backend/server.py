"""
ZapPedidos + LAD Tracker — server principal
Base modular (lib/*.py, models/schemas.py) do painel antigo mesclada com as
features do painel novo (motoboys, tracker público, push, alertas, notas).
Auth: cookie httpOnly `zp_session` (ver lib/auth.py).
"""
from __future__ import annotations

import json as _json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from pywebpush import WebPushException, webpush
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from lib.auth import (  # noqa: E402
    COOKIE_NAME,
    User,
    admin_user,
    check_senha,
    current_user,
    ensure_admin_seed,
    hash_senha,
    make_token,
    optional_user,
)
from lib.db import client, db, ensure_indexes  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_CLAIM_EMAIL", "mailto:noreply@zappedidos.com")}
LAD_BASE_URL = os.environ.get("LAD_BASE_URL", "https://api2.laddelivery.com.br")
PUSH_RADIUS_KM = 0.5
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"

PLAN_QUOTAS = {
    "free": {"max_motoboys": 2, "max_orders_month": 50, "label": "Free"},
    "basic": {"max_motoboys": 5, "max_orders_month": 500, "label": "Basic"},
    "pro": {"max_motoboys": 999, "max_orders_month": 999999, "label": "Pro"},
}

app = FastAPI(title="ZapPedidos + LAD Tracker")
api = APIRouter(prefix="/api")


# ============ helpers ============
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _haversine_km(a, b) -> float:
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def _set_session_cookie(response: Response, user: User) -> None:
    token = make_token(user)
    response.set_cookie(
        key=COOKIE_NAME, value=token, max_age=7 * 24 * 3600,
        httponly=True, secure=COOKIE_SECURE, samesite="none" if COOKIE_SECURE else "lax", path="/",
    )


async def _geocode(query: str):
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


def _send_push(sub: Dict[str, Any], title: str, body: str, url: str) -> bool:
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


# ============ models (endpoint-specific) ============
class RegisterIn(BaseModel):
    nome: str
    email: EmailStr
    senha: str
    nome_loja: str
    telefone: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class MotoboyIn(BaseModel):
    nome: str
    telefone: str
    veiculo: Optional[str] = "Moto"
    placa: Optional[str] = None


class OrderIn(BaseModel):
    cliente_nome: str
    cliente_whatsapp: str
    endereco: str
    itens: str
    total: float
    forma_pagamento: Optional[str] = "PIX"
    observacao: Optional[str] = None


class DispatchIn(BaseModel):
    motoboy_id: str


class LocationIn(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None


class StatusIn(BaseModel):
    status: str


class LadConfigIn(BaseModel):
    token: str
    demo: Optional[bool] = False


class LadImportIn(BaseModel):
    uuid: str


class NoteIn(BaseModel):
    mensagem: str


class PushSubscribeIn(BaseModel):
    endpoint: str
    keys: Dict[str, str]


class AdminCreateStoreIn(BaseModel):
    nome_loja: str
    nome_dono: str
    email_dono: EmailStr
    senha_dono: str
    telefone: Optional[str] = None
    plano: Optional[str] = "free"


class PlanIn(BaseModel):
    plano: str


# ============ AUTH ============
@api.post("/auth/register")
async def register(body: RegisterIn, response: Response):
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    sid = str(uuid.uuid4())
    now = utcnow()
    user = User(
        email=body.email.lower(), nome=body.nome, role="lojista",
        store_id=sid, senha_hash=hash_senha(body.senha),
    )
    await db.users.insert_one(user.model_dump())
    await db.stores.insert_one({
        "id": sid, "nome": body.nome_loja, "owner_id": user.id,
        "telefone": body.telefone, "lad_token": "", "lad_demo": False,
        "webhook_token": secrets.token_urlsafe(16),
        "plano": "free", "ativa": True, "created_at": now,
    })
    _set_session_cookie(response, user)
    return {"user": {"id": user.id, "email": user.email, "nome": user.nome,
                     "role": user.role, "store_id": user.store_id}}


@api.post("/auth/login")
async def login(body: LoginIn, response: Response):
    key = body.email.lower()
    attempt = await db.login_attempts.find_one({"email": key})
    if attempt and attempt.get("count", 0) >= 5:
        blocked_until = attempt.get("blocked_until")
        if blocked_until and utcnow() < datetime.fromisoformat(blocked_until):
            raise HTTPException(429, "Muitas tentativas. Aguarde 5 minutos.")
    u = await db.users.find_one({"email": key})
    if not u or not check_senha(body.senha, u.get("senha_hash", "")):
        cnt = (attempt.get("count", 0) if attempt else 0) + 1
        upd = {"email": key, "count": cnt}
        if cnt >= 5:
            upd["blocked_until"] = (utcnow() + timedelta(minutes=5)).isoformat()
        await db.login_attempts.update_one({"email": key}, {"$set": upd}, upsert=True)
        raise HTTPException(401, "Credenciais inválidas")
    await db.login_attempts.delete_one({"email": key})
    u.pop("_id", None)
    user = User(**u)
    _set_session_cookie(response, user)
    return {"user": {"id": user.id, "email": user.email, "nome": user.nome,
                     "role": user.role, "store_id": user.store_id}}


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "nome": user.nome,
            "role": user.role, "store_id": user.store_id}


# ============ ADMIN ============
@api.get("/admin/stats")
async def admin_stats(user: User = Depends(admin_user)):
    return {
        "stores": await db.stores.count_documents({}),
        "users": await db.users.count_documents({}),
        "motoboys": await db.motoboys.count_documents({}),
        "orders": await db.orders.count_documents({}),
    }


@api.get("/admin/stores")
async def admin_stores(user: User = Depends(admin_user)):
    stores = await db.stores.find({}, {"_id": 0}).to_list(500)
    for s in stores:
        s["motoboys_count"] = await db.motoboys.count_documents({"store_id": s["id"]})
        s["orders_count"] = await db.orders.count_documents({"store_id": s["id"]})
        s.setdefault("plano", "free")
    return stores


@api.post("/admin/stores")
async def admin_create_store(body: AdminCreateStoreIn, user: User = Depends(admin_user)):
    if await db.users.find_one({"email": body.email_dono.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    if body.plano not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    sid = str(uuid.uuid4())
    owner = User(
        email=body.email_dono.lower(), nome=body.nome_dono, role="lojista",
        store_id=sid, senha_hash=hash_senha(body.senha_dono),
    )
    await db.users.insert_one(owner.model_dump())
    await db.stores.insert_one({
        "id": sid, "nome": body.nome_loja, "owner_id": owner.id,
        "telefone": body.telefone, "lad_token": "", "lad_demo": False,
        "webhook_token": secrets.token_urlsafe(16),
        "plano": body.plano, "ativa": True, "created_at": utcnow(),
    })
    return {"id": sid, "plano": body.plano}


@api.patch("/admin/stores/{sid}")
async def admin_toggle_store(sid: str, body: Dict[str, Any], user: User = Depends(admin_user)):
    await db.stores.update_one({"id": sid}, {"$set": {"ativa": bool(body.get("ativa", True))}})
    return {"ok": True}


@api.put("/admin/stores/{sid}/plan")
async def admin_update_plan(sid: str, body: PlanIn, user: User = Depends(admin_user)):
    if body.plano not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    r = await db.stores.update_one({"id": sid}, {"$set": {"plano": body.plano}})
    if r.matched_count == 0:
        raise HTTPException(404, "Loja não encontrada")
    return {"ok": True, "plano": body.plano}


@api.delete("/admin/stores/{sid}")
async def admin_delete_store(sid: str, user: User = Depends(admin_user)):
    if not await db.stores.find_one({"id": sid}):
        raise HTTPException(404, "Loja não encontrada")
    await db.users.delete_many({"store_id": sid})
    await db.motoboys.delete_many({"store_id": sid})
    await db.orders.delete_many({"store_id": sid})
    await db.locations.delete_many({"store_id": sid}) if False else None
    await db.stores.delete_one({"id": sid})
    return {"ok": True}


@api.get("/admin/plans")
async def admin_plans(user: User = Depends(admin_user)):
    return PLAN_QUOTAS


# ============ STORE settings ============
async def _require_store(user: User = Depends(current_user)) -> User:
    if not user.store_id and user.role != "admin":
        raise HTTPException(403, "Requer loja")
    return user


@api.get("/store/me")
async def get_my_store(user: User = Depends(_require_store)):
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Loja não encontrada")
    return s


@api.put("/store/lad")
async def update_lad_config(body: LadConfigIn, user: User = Depends(_require_store)):
    await db.stores.update_one(
        {"id": user.store_id},
        {"$set": {"lad_token": body.token, "lad_demo": bool(body.demo)}},
    )
    return {"ok": True}


@api.get("/store/lad/loja")
async def lad_loja(user: User = Depends(_require_store)):
    from lib.lad import LadClient, LadError
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0})
    if not s or (not s.get("lad_token") and not s.get("lad_demo")):
        raise HTTPException(400, "Configure o token LAD (ou ative demo) primeiro")
    lad = LadClient(s.get("lad_token", ""), demo=bool(s.get("lad_demo")))
    try:
        return {"data": await lad.loja()}
    except LadError as e:
        raise HTTPException(e.status, e.descricao)


@api.get("/store/webhook-url")
async def get_webhook_url(user: User = Depends(_require_store)):
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0, "webhook_token": 1})
    if not s.get("webhook_token"):
        tok = secrets.token_urlsafe(16)
        await db.stores.update_one({"id": user.store_id}, {"$set": {"webhook_token": tok}})
        return {"token": tok}
    return {"token": s["webhook_token"]}


@api.post("/store/webhook-url/rotate")
async def rotate_webhook_url(user: User = Depends(_require_store)):
    tok = secrets.token_urlsafe(16)
    await db.stores.update_one({"id": user.store_id}, {"$set": {"webhook_token": tok}})
    return {"token": tok}


# ============ MOTOBOYS ============
@api.get("/motoboys")
async def list_motoboys(user: User = Depends(_require_store)):
    return await db.motoboys.find({"store_id": user.store_id}, {"_id": 0}).to_list(500)


@api.post("/motoboys")
async def create_motoboy(body: MotoboyIn, user: User = Depends(_require_store)):
    store = await db.stores.find_one({"id": user.store_id}, {"_id": 0, "plano": 1})
    quota = PLAN_QUOTAS.get(store.get("plano", "free"), PLAN_QUOTAS["free"])
    count = await db.motoboys.count_documents({"store_id": user.store_id})
    if count >= quota["max_motoboys"]:
        raise HTTPException(400, f"Limite do plano {quota['label']} atingido ({quota['max_motoboys']} motoboys). Faça upgrade.")
    mid = str(uuid.uuid4())
    doc = {"id": mid, "store_id": user.store_id, **body.model_dump(),
           "ativo": True, "created_at": utcnow()}
    await db.motoboys.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.put("/motoboys/{mid}")
async def update_motoboy(mid: str, body: MotoboyIn, user: User = Depends(_require_store)):
    r = await db.motoboys.update_one({"id": mid, "store_id": user.store_id}, {"$set": body.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(404, "Motoboy não encontrado")
    return {"ok": True}


@api.delete("/motoboys/{mid}")
async def delete_motoboy(mid: str, user: User = Depends(_require_store)):
    await db.motoboys.delete_one({"id": mid, "store_id": user.store_id})
    return {"ok": True}


# ============ ORDERS ============
@api.get("/orders")
async def list_orders(user: User = Depends(_require_store)):
    orders = await db.orders.find({"store_id": user.store_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for o in orders:
        if o.get("motoboy_id"):
            m = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "nome": 1, "telefone": 1, "id": 1})
            o["motoboy"] = m
    return orders


@api.post("/orders")
async def create_order(body: OrderIn, user: User = Depends(_require_store)):
    dest = await _geocode(body.endereco)
    oid = str(uuid.uuid4())
    doc = {
        "id": oid, "store_id": user.store_id, **body.model_dump(),
        "status": "pending", "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12),
        "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest[0] if dest else None,
        "dest_lng": dest[1] if dest else None,
        "created_at": utcnow(), "dispatched_at": None, "delivered_at": None,
        "last_location": None, "lad_uuid": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.post("/orders/{oid}/dispatch")
async def dispatch_order(oid: str, body: DispatchIn, user: User = Depends(_require_store)):
    o = await db.orders.find_one({"id": oid, "store_id": user.store_id})
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    m = await db.motoboys.find_one({"id": body.motoboy_id, "store_id": user.store_id})
    if not m:
        raise HTTPException(400, "Motoboy inválido")
    await db.orders.update_one(
        {"id": oid},
        {"$set": {"motoboy_id": body.motoboy_id, "status": "dispatched",
                  "dispatched_at": utcnow()}},
    )
    o2 = await db.orders.find_one({"id": oid}, {"_id": 0})
    o2["motoboy"] = {k: m.get(k) for k in ("id", "nome", "telefone")}
    return o2


@api.patch("/orders/{oid}/status")
async def update_status(oid: str, body: StatusIn, user: User = Depends(_require_store)):
    upd: Dict[str, Any] = {"status": body.status}
    if body.status == "delivered":
        upd["delivered_at"] = utcnow()
    r = await db.orders.update_one({"id": oid, "store_id": user.store_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Pedido não encontrado")
    return {"ok": True}


@api.delete("/orders/{oid}")
async def delete_order(oid: str, user: User = Depends(_require_store)):
    await db.orders.delete_one({"id": oid, "store_id": user.store_id})
    return {"ok": True}


# ============ LAD IMPORT / WEBHOOK ============
def _lad_to_internal(lad: Dict[str, Any]) -> Dict[str, Any]:
    itens_txt = ", ".join([f"{i.get('quantidade', 1)}x {i.get('nome', '')}" for i in lad.get("itens", [])])
    addr = lad.get("enderecoEntrega") or {}
    endereco_parts = [addr.get("endereco"), addr.get("numero"), addr.get("bairro"), addr.get("cidade")]
    endereco = ", ".join([p for p in endereco_parts if p]) or "Retirada na loja"
    cliente = lad.get("cliente") or {}
    status_map = {"E": "pending", "A": "preparing", "V": "preparing", "X": "dispatched",
                  "D": "delivered", "P": "pending", "C": "canceled", "R": "canceled"}
    status_code = (lad.get("status") or {}).get("codigo", "E")
    return {
        "cliente_nome": cliente.get("nome") or "Cliente LAD",
        "cliente_whatsapp": (cliente.get("telefone") or "").replace(" ", ""),
        "endereco": endereco,
        "itens": itens_txt or "Pedido LAD",
        "total": float(lad.get("valorTotal") or 0),
        "forma_pagamento": (lad.get("pagamento") or {}).get("forma", "—"),
        "observacao": lad.get("observacao"),
        "status": status_map.get(status_code, "pending"),
        "lad_uuid": lad.get("uuid"),
    }


async def _import_lad_uuid(store: Dict[str, Any], lad_uuid: str) -> Dict[str, Any]:
    from lib.lad import LadClient, LadError
    lad_client = LadClient(store.get("lad_token", ""), demo=bool(store.get("lad_demo")))
    try:
        lad = await lad_client.pedido(lad_uuid)
    except LadError as e:
        raise HTTPException(e.status if e.status else 502, e.descricao)
    internal = _lad_to_internal(lad)
    existing = await db.orders.find_one({"store_id": store["id"], "lad_uuid": lad.get("uuid")})
    if existing:
        await db.orders.update_one({"id": existing["id"]}, {"$set": internal})
        doc = await db.orders.find_one({"id": existing["id"]}, {"_id": 0})
        return {"imported": False, "updated": True, "order": doc}
    dest = await _geocode(internal["endereco"])
    oid = str(uuid.uuid4())
    doc = {
        "id": oid, "store_id": store["id"], **internal,
        "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12),
        "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest[0] if dest else None,
        "dest_lng": dest[1] if dest else None,
        "created_at": utcnow(), "dispatched_at": None, "delivered_at": None,
        "last_location": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return {"imported": True, "updated": False, "order": doc}


@api.post("/store/lad/import")
async def lad_import_order(body: LadImportIn, user: User = Depends(_require_store)):
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0})
    if not s or (not s.get("lad_token") and not s.get("lad_demo")):
        raise HTTPException(400, "Configure o token LAD primeiro")
    return await _import_lad_uuid(s, body.uuid)


@api.post("/store/lad/refresh")
async def lad_refresh_all(user: User = Depends(_require_store)):
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0})
    if not s or (not s.get("lad_token") and not s.get("lad_demo")):
        raise HTTPException(400, "Configure o token LAD primeiro")
    from lib.lad import LadClient
    lad_client = LadClient(s.get("lad_token", ""), demo=bool(s.get("lad_demo")))
    active = await db.orders.find({"store_id": user.store_id, "lad_uuid": {"$ne": None},
                                    "status": {"$nin": ["delivered", "canceled"]}},
                                    {"_id": 0, "id": 1, "lad_uuid": 1}).to_list(50)
    updated = 0
    for o in active:
        try:
            lad = await lad_client.pedido(o["lad_uuid"])
            await db.orders.update_one({"id": o["id"]}, {"$set": {"status": _lad_to_internal(lad)["status"]}})
            updated += 1
        except Exception:
            continue
    return {"updated": updated, "total": len(active)}


@api.post("/webhook/lad/{webhook_token}")
async def lad_webhook(webhook_token: str, payload: Dict[str, Any]):
    s = await db.stores.find_one({"webhook_token": webhook_token}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Webhook não encontrado")
    if not s.get("lad_token") and not s.get("lad_demo"):
        raise HTTPException(400, "Loja sem token LAD")
    lad_uuid = payload.get("uuid") or payload.get("pedido_uuid") or (payload.get("data") or {}).get("uuid")
    if not lad_uuid:
        raise HTTPException(400, "Payload sem uuid")
    result = await _import_lad_uuid(s, lad_uuid)
    return {"ok": True, **result}


# ============ PUBLIC TRACKING ============
@api.get("/track/{token}")
async def public_track(token: str):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "cliente_whatsapp": 0})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1, "telefone": 1})
    m = None
    if o.get("motoboy_id"):
        mo = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0})
        if mo:
            m = {"nome": mo["nome"], "veiculo": mo.get("veiculo"), "placa": mo.get("placa")}
    return {"order": o, "store": s, "motoboy": m}


@api.get("/track/{token}/location")
async def get_last_location(token: str):
    o = await db.orders.find_one({"tracking_token": token},
                                  {"_id": 0, "last_location": 1, "status": 1, "dest_lat": 1, "dest_lng": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    eta_min = None
    if o.get("last_location") and o.get("dest_lat") is not None and o.get("dest_lng") is not None:
        km = _haversine_km((o["last_location"]["lat"], o["last_location"]["lng"]),
                            (o["dest_lat"], o["dest_lng"]))
        eta_min = max(1, int(round(km / 25 * 60)))
    return {**o, "eta_minutes": eta_min}


@api.get("/track/{token}/route")
async def get_route(token: str):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "id": 1, "dest_lat": 1, "dest_lng": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    points = await db.locations.find({"order_id": o["id"]}, {"_id": 0, "lat": 1, "lng": 1, "at": 1}).sort("at", 1).to_list(500)
    return {"points": points, "destination": {"lat": o.get("dest_lat"), "lng": o.get("dest_lng")}}


@api.post("/track/{token}/note")
async def customer_note(token: str, body: NoteIn):
    o = await db.orders.find_one({"tracking_token": token})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "telefone": 1, "nome": 1})
    note = {
        "id": str(uuid.uuid4()), "order_id": o["id"], "store_id": o["store_id"],
        "mensagem": body.mensagem[:500], "cliente_nome": o["cliente_nome"],
        "at": utcnow(), "lida": False,
    }
    await db.notes.insert_one(note)
    phone = "".join(ch for ch in (s.get("telefone") or "") if ch.isdigit())
    if phone and not phone.startswith("55"):
        phone = "55" + phone
    text = f"📝 Nota de {o['cliente_nome']} (pedido #{o['id'][:8]}):\n{body.mensagem}"
    wa = f"https://wa.me/{phone}?text={text}" if phone else None
    return {"ok": True, "wa_url": wa, "store": s.get("nome")}


@api.get("/notes")
async def list_notes(user: User = Depends(_require_store)):
    notes = await db.notes.find({"store_id": user.store_id}, {"_id": 0}).sort("at", -1).to_list(100)
    return notes


@api.patch("/notes/{nid}/read")
async def mark_note_read(nid: str, user: User = Depends(_require_store)):
    await db.notes.update_one({"id": nid, "store_id": user.store_id}, {"$set": {"lida": True}})
    return {"ok": True}


@api.get("/alerts")
async def live_alerts(user: User = Depends(_require_store), stale_min: int = 5):
    now = utcnow()
    orders = await db.orders.find({"store_id": user.store_id, "status": "dispatched"},
                                    {"_id": 0, "id": 1, "cliente_nome": 1, "motoboy_id": 1,
                                     "last_location": 1, "dispatched_at": 1, "dest_lat": 1, "dest_lng": 1}).to_list(200)
    alerts = []
    for o in orders:
        loc = o.get("last_location")
        if not loc:
            dispatched_at = o.get("dispatched_at")
            if dispatched_at:
                da = dispatched_at if isinstance(dispatched_at, datetime) else datetime.fromisoformat(dispatched_at)
                if da.tzinfo is None:
                    da = da.replace(tzinfo=timezone.utc)
                delta = (now - da).total_seconds() / 60
                if delta > stale_min:
                    alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"],
                                    "type": "no_location", "minutes": int(delta),
                                    "message": f"Sem localização há {int(delta)} min desde o despacho"})
            continue
        la = loc["at"] if isinstance(loc["at"], datetime) else datetime.fromisoformat(loc["at"])
        if la.tzinfo is None:
            la = la.replace(tzinfo=timezone.utc)
        delta = (now - la).total_seconds() / 60
        if delta > stale_min:
            alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"],
                            "type": "stale_location", "minutes": int(delta),
                            "message": f"Motoboy parou de enviar localização há {int(delta)} min"})
            continue
        if o.get("dest_lat") is not None and o.get("dest_lng") is not None:
            recent = await db.locations.find({"order_id": o["id"]}, {"_id": 0, "lat": 1, "lng": 1}).sort("at", -1).to_list(3)
            if len(recent) == 3:
                dests = (o["dest_lat"], o["dest_lng"])
                d0 = _haversine_km((recent[2]["lat"], recent[2]["lng"]), dests)
                d1 = _haversine_km((recent[1]["lat"], recent[1]["lng"]), dests)
                d2 = _haversine_km((recent[0]["lat"], recent[0]["lng"]), dests)
                if d2 > d1 > d0 and (d2 - d0) > 0.3:
                    alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"],
                                    "type": "off_route", "distance_km": round(d2, 2),
                                    "message": f"Se afastando do destino ({round((d2 - d0) * 1000)}m nos últimos pings)"})
    return {"alerts": alerts, "count": len(alerts)}


# ============ MOTOBOY SHARE ============
@api.get("/motoboy-track/{token}")
async def motoboy_track_info(token: str):
    o = await db.orders.find_one({"motoboy_share_token": token}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Sessão não encontrada")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1})
    m = None
    if o.get("motoboy_id"):
        m = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "nome": 1, "telefone": 1})
    return {
        "order": {"id": o["id"], "cliente_nome": o["cliente_nome"], "endereco": o["endereco"],
                  "total": o["total"], "status": o["status"], "observacao": o.get("observacao"),
                  "tracking_token": o["tracking_token"]},
        "store": s, "motoboy": m,
    }


@api.post("/motoboy-track/{token}/location")
async def post_location(token: str, body: LocationIn):
    o = await db.orders.find_one({"motoboy_share_token": token})
    if not o:
        raise HTTPException(404, "Sessão inválida")
    loc = {**body.model_dump(), "at": utcnow()}
    await db.orders.update_one({"id": o["id"]}, {"$set": {"last_location": loc}})
    await db.locations.insert_one({"order_id": o["id"], **loc})
    if o.get("dest_lat") is not None and o.get("dest_lng") is not None and not o.get("push_arrival_sent"):
        km = _haversine_km((body.lat, body.lng), (o["dest_lat"], o["dest_lng"]))
        if km <= PUSH_RADIUS_KM:
            subs = await db.push_subs.find({"order_id": o["id"]}, {"_id": 0}).to_list(20)
            store = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1})
            url = f"/track/{o['tracking_token']}"
            sent = 0
            for s in subs:
                if _send_push(s, "🛵 Está chegando!",
                                f"O entregador da {store.get('nome', 'loja')} está a menos de 500m. Prepare-se!",
                                url):
                    sent += 1
            if sent:
                await db.orders.update_one({"id": o["id"]}, {"$set": {"push_arrival_sent": utcnow()}})
    return {"ok": True}


# ============ PUSH ============
@api.get("/push/vapid-public")
async def vapid_public():
    return {"key": VAPID_PUBLIC_KEY}


@api.post("/track/{token}/push-subscribe")
async def push_subscribe(token: str, body: PushSubscribeIn):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "id": 1})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    await db.push_subs.update_one(
        {"order_id": o["id"], "endpoint": body.endpoint},
        {"$set": {"order_id": o["id"], "endpoint": body.endpoint, "keys": body.keys, "at": utcnow()}},
        upsert=True,
    )
    return {"ok": True}


# ============ startup ============
@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await ensure_admin_seed()
    logger.info("ZapPedidos + Tracker API up. LAD=%s", LAD_BASE_URL)


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
