from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, uuid, secrets, hashlib, hmac, base64, json, asyncio
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt as pyjwt
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'zappedidos-dev-secret-change-me')
JWT_ALG = 'HS256'
JWT_EXP_HOURS = 24 * 7

app = FastAPI(title="ZapPedidos + LAD Delivery Tracker API")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)


def utcnow():
    return datetime.now(timezone.utc)


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": utcnow() + timedelta(hours=JWT_EXP_HOURS),
        "iat": utcnow(),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds:
        raise HTTPException(401, "Token ausente")
    try:
        payload = pyjwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        raise HTTPException(401, "Token inválido")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(401, "Usuário não existe")
    return user


async def require_admin(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Requer administrador")
    return user


async def require_store(user=Depends(current_user)):
    if user.get("role") not in ("store", "admin"):
        raise HTTPException(403, "Requer loja")
    return user


# ============ MODELS ============
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str
    store_name: str
    phone: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MotoboyIn(BaseModel):
    name: str
    whatsapp: str
    vehicle: Optional[str] = "Moto"
    plate: Optional[str] = None


class OrderIn(BaseModel):
    customer_name: str
    customer_whatsapp: str
    address: str
    items: str
    total: float
    payment_method: Optional[str] = "PIX"
    notes: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class DispatchIn(BaseModel):
    motoboy_id: str


class LocationIn(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None


class StatusIn(BaseModel):
    status: str  # pending, preparing, dispatched, delivered, canceled


class LadConfigIn(BaseModel):
    api_token: str
    api_base: Optional[str] = "https://api2.laddelivery.com.br"


class AdminCreateStoreIn(BaseModel):
    store_name: str
    owner_name: str
    owner_email: EmailStr
    owner_password: str
    phone: Optional[str] = None
    plan: Optional[str] = "free"


class PlanIn(BaseModel):
    plan: str  # free | basic | pro


class LadImportIn(BaseModel):
    uuid: str


class NoteIn(BaseModel):
    message: str


PLAN_QUOTAS = {
    "free": {"max_motoboys": 2, "max_orders_month": 50},
    "basic": {"max_motoboys": 5, "max_orders_month": 500},
    "pro": {"max_motoboys": 999, "max_orders_month": 999999},
}


# ============ AUTH ============
@api.post("/auth/register")
async def register(body: RegisterIn):
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    uid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    now = utcnow().isoformat()
    await db.users.insert_one({
        "id": uid, "name": body.name, "email": body.email.lower(),
        "password": hash_pw(body.password), "role": "store", "store_id": sid,
        "created_at": now,
    })
    await db.stores.insert_one({
        "id": sid, "name": body.store_name, "owner_id": uid,
        "phone": body.phone, "lad_api_token": None,
        "lad_api_base": "https://api2.laddelivery.com.br",
        "waha_url": None, "waha_session": None,
        "webhook_token": secrets.token_urlsafe(16),
        "plan": "free", "active": True, "created_at": now,
    })
    token = create_token(uid, "store")
    return {"token": token, "user": {"id": uid, "name": body.name, "email": body.email.lower(), "role": "store", "store_id": sid}}


@api.post("/auth/login")
async def login(body: LoginIn):
    u = await db.users.find_one({"email": body.email.lower()})
    if not u or not verify_pw(body.password, u["password"]):
        raise HTTPException(401, "Credenciais inválidas")
    token = create_token(u["id"], u["role"])
    return {"token": token, "user": {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"], "store_id": u.get("store_id")}}


@api.get("/auth/me")
async def me(user=Depends(current_user)):
    return user


# ============ ADMIN ============
@api.get("/admin/stores")
async def admin_stores(user=Depends(require_admin)):
    stores = await db.stores.find({}, {"_id": 0}).to_list(500)
    for s in stores:
        s["motoboys_count"] = await db.motoboys.count_documents({"store_id": s["id"]})
        s["orders_count"] = await db.orders.count_documents({"store_id": s["id"]})
        s.setdefault("plan", "free")
    return stores


@api.get("/admin/stats")
async def admin_stats(user=Depends(require_admin)):
    return {
        "stores": await db.stores.count_documents({}),
        "users": await db.users.count_documents({}),
        "motoboys": await db.motoboys.count_documents({}),
        "orders": await db.orders.count_documents({}),
        "orders_today": await db.orders.count_documents({"created_at": {"$gte": utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()}}),
    }


@api.patch("/admin/stores/{sid}")
async def admin_toggle_store(sid: str, body: Dict[str, Any], user=Depends(require_admin)):
    await db.stores.update_one({"id": sid}, {"$set": {"active": bool(body.get("active", True))}})
    return {"ok": True}


@api.post("/admin/stores")
async def admin_create_store(body: AdminCreateStoreIn, user=Depends(require_admin)):
    if await db.users.find_one({"email": body.owner_email.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    if body.plan not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    uid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    now = utcnow().isoformat()
    await db.users.insert_one({
        "id": uid, "name": body.owner_name, "email": body.owner_email.lower(),
        "password": hash_pw(body.owner_password), "role": "store", "store_id": sid,
        "created_at": now,
    })
    await db.stores.insert_one({
        "id": sid, "name": body.store_name, "owner_id": uid,
        "phone": body.phone, "lad_api_token": None,
        "lad_api_base": "https://api2.laddelivery.com.br",
        "webhook_token": secrets.token_urlsafe(16),
        "plan": body.plan, "active": True, "created_at": now,
    })
    return {"id": sid, "plan": body.plan}


@api.put("/admin/stores/{sid}/plan")
async def admin_update_plan(sid: str, body: PlanIn, user=Depends(require_admin)):
    if body.plan not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    r = await db.stores.update_one({"id": sid}, {"$set": {"plan": body.plan}})
    if r.matched_count == 0:
        raise HTTPException(404, "Loja não encontrada")
    return {"ok": True, "plan": body.plan}


@api.get("/admin/plans")
async def admin_plans(user=Depends(require_admin)):
    return PLAN_QUOTAS


@api.delete("/admin/stores/{sid}")
async def admin_delete_store(sid: str, user=Depends(require_admin)):
    s = await db.stores.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Loja não encontrada")
    await db.users.delete_many({"store_id": sid})
    await db.motoboys.delete_many({"store_id": sid})
    await db.orders.delete_many({"store_id": sid})
    await db.stores.delete_one({"id": sid})
    return {"ok": True}


# ============ STORE / SETTINGS ============
@api.get("/store/me")
async def get_my_store(user=Depends(require_store)):
    s = await db.stores.find_one({"id": user.get("store_id")}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Loja não encontrada")
    return s


@api.put("/store/lad")
async def update_lad_config(body: LadConfigIn, user=Depends(require_store)):
    await db.stores.update_one(
        {"id": user["store_id"]},
        {"$set": {"lad_api_token": body.api_token, "lad_api_base": body.api_base}},
    )
    return {"ok": True}


@api.get("/store/lad/loja")
async def lad_loja(user=Depends(require_store)):
    s = await db.stores.find_one({"id": user["store_id"]}, {"_id": 0})
    if not s or not s.get("lad_api_token"):
        raise HTTPException(400, "Configure o token LAD primeiro")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{s['lad_api_base']}/v1/loja", headers={"Authorization": f"Bearer {s['lad_api_token']}"})
    return {"status": r.status_code, "data": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}


def _lad_to_internal(lad: Dict[str, Any]) -> Dict[str, Any]:
    """Convert LAD /v1/pedidos response to our internal order fields."""
    items = ", ".join([f"{i.get('quantidade', 1)}x {i.get('nome', '')}" for i in lad.get("itens", [])])
    addr = lad.get("enderecoEntrega") or {}
    endereco_parts = [addr.get("endereco"), addr.get("numero"), addr.get("bairro"), addr.get("cidade")]
    endereco = ", ".join([p for p in endereco_parts if p]) or "Retirada na loja"
    cliente = lad.get("cliente") or {}
    status_map = {"E": "pending", "A": "preparing", "V": "preparing", "X": "dispatched",
                  "D": "delivered", "P": "pending", "C": "canceled", "R": "canceled"}
    status_code = (lad.get("status") or {}).get("codigo", "E")
    return {
        "customer_name": cliente.get("nome") or "Cliente LAD",
        "customer_whatsapp": (cliente.get("telefone") or "").replace(" ", ""),
        "address": endereco,
        "items": items or "Pedido LAD",
        "total": float(lad.get("valorTotal") or 0),
        "payment_method": (lad.get("pagamento") or {}).get("forma", "—"),
        "notes": lad.get("observacao"),
        "status": status_map.get(status_code, "pending"),
        "lad_uuid": lad.get("uuid"),
    }


async def _geocode(query: str):
    """Best-effort geocoding via Nominatim (free, no key). Returns (lat, lng) or None."""
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


def _haversine_km(a, b):
    from math import radians, sin, cos, asin, sqrt
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(h))


async def _import_lad_uuid(store: Dict[str, Any], lad_uuid: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{store['lad_api_base']}/v1/pedidos/{lad_uuid}",
                        headers={"Authorization": f"Bearer {store['lad_api_token']}"})
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"LAD: {r.text[:200]}")
    lad = r.json()
    internal = _lad_to_internal(lad)
    existing = await db.orders.find_one({"store_id": store["id"], "lad_uuid": lad.get("uuid")})
    if existing:
        await db.orders.update_one({"id": existing["id"]}, {"$set": internal})
        doc = await db.orders.find_one({"id": existing["id"]}, {"_id": 0})
        return {"imported": False, "updated": True, "order": doc}
    dest = await _geocode(internal["address"])
    oid = str(uuid.uuid4())
    doc = {
        "id": oid, "store_id": store["id"], **internal,
        "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12),
        "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest[0] if dest else None,
        "dest_lng": dest[1] if dest else None,
        "created_at": utcnow().isoformat(), "dispatched_at": None, "delivered_at": None,
        "last_location": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return {"imported": True, "updated": False, "order": doc}


@api.post("/store/lad/import")
async def lad_import_order(body: LadImportIn, user=Depends(require_store)):
    s = await db.stores.find_one({"id": user["store_id"]}, {"_id": 0})
    if not s or not s.get("lad_api_token"):
        raise HTTPException(400, "Configure o token LAD primeiro")
    return await _import_lad_uuid(s, body.uuid)


# ============ PUBLIC LAD WEBHOOK ============
@api.post("/webhook/lad/{webhook_token}")
async def lad_webhook(webhook_token: str, payload: Dict[str, Any]):
    s = await db.stores.find_one({"webhook_token": webhook_token}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Webhook não encontrado")
    if not s.get("lad_api_token"):
        raise HTTPException(400, "Loja sem token LAD")
    lad_uuid = payload.get("uuid") or payload.get("pedido_uuid") or (payload.get("data") or {}).get("uuid")
    if not lad_uuid:
        raise HTTPException(400, "Payload sem uuid")
    result = await _import_lad_uuid(s, lad_uuid)
    return {"ok": True, **result}


@api.get("/store/webhook-url")
async def get_webhook_url(user=Depends(require_store)):
    s = await db.stores.find_one({"id": user["store_id"]}, {"_id": 0, "webhook_token": 1})
    if not s or not s.get("webhook_token"):
        # backfill if store was created before this feature
        tok = secrets.token_urlsafe(16)
        await db.stores.update_one({"id": user["store_id"]}, {"$set": {"webhook_token": tok}})
        return {"token": tok}
    return {"token": s["webhook_token"]}


@api.post("/store/webhook-url/rotate")
async def rotate_webhook_url(user=Depends(require_store)):
    tok = secrets.token_urlsafe(16)
    await db.stores.update_one({"id": user["store_id"]}, {"$set": {"webhook_token": tok}})
    return {"token": tok}


@api.post("/store/lad/refresh")
async def lad_refresh_all(user=Depends(require_store)):
    s = await db.stores.find_one({"id": user["store_id"]}, {"_id": 0})
    if not s or not s.get("lad_api_token"):
        raise HTTPException(400, "Configure o token LAD primeiro")
    active = await db.orders.find({"store_id": user["store_id"], "lad_uuid": {"$ne": None},
                                    "status": {"$nin": ["delivered", "canceled"]}}, {"_id": 0, "id": 1, "lad_uuid": 1}).to_list(50)
    updated = 0
    async with httpx.AsyncClient(timeout=15) as c:
        for o in active:
            r = await c.get(f"{s['lad_api_base']}/v1/pedidos/{o['lad_uuid']}",
                            headers={"Authorization": f"Bearer {s['lad_api_token']}"})
            if r.status_code == 200:
                lad = r.json()
                await db.orders.update_one({"id": o["id"]}, {"$set": {"status": _lad_to_internal(lad)["status"]}})
                updated += 1
    return {"updated": updated, "total": len(active)}


# ============ MOTOBOYS ============
@api.get("/motoboys")
async def list_motoboys(user=Depends(require_store)):
    return await db.motoboys.find({"store_id": user["store_id"]}, {"_id": 0}).to_list(500)


@api.post("/motoboys")
async def create_motoboy(body: MotoboyIn, user=Depends(require_store)):
    mid = str(uuid.uuid4())
    doc = {"id": mid, "store_id": user["store_id"], **body.dict(),
           "active": True, "created_at": utcnow().isoformat()}
    await db.motoboys.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.put("/motoboys/{mid}")
async def update_motoboy(mid: str, body: MotoboyIn, user=Depends(require_store)):
    r = await db.motoboys.update_one({"id": mid, "store_id": user["store_id"]}, {"$set": body.dict()})
    if r.matched_count == 0:
        raise HTTPException(404, "Motoboy não encontrado")
    return {"ok": True}


@api.delete("/motoboys/{mid}")
async def delete_motoboy(mid: str, user=Depends(require_store)):
    await db.motoboys.delete_one({"id": mid, "store_id": user["store_id"]})
    return {"ok": True}


# ============ ORDERS ============
@api.get("/orders")
async def list_orders(user=Depends(require_store)):
    orders = await db.orders.find({"store_id": user["store_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    # attach motoboy
    for o in orders:
        if o.get("motoboy_id"):
            m = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "name": 1, "whatsapp": 1})
            o["motoboy"] = m
    return orders


@api.post("/orders")
async def create_order(body: OrderIn, user=Depends(require_store)):
    oid = str(uuid.uuid4())
    dest_lat, dest_lng = body.lat, body.lng
    if dest_lat is None or dest_lng is None:
        g = await _geocode(body.address)
        if g:
            dest_lat, dest_lng = g
    doc = {
        "id": oid, "store_id": user["store_id"], **body.dict(),
        "status": "pending", "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12),
        "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest_lat, "dest_lng": dest_lng,
        "created_at": utcnow().isoformat(), "dispatched_at": None, "delivered_at": None,
        "last_location": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/orders/{oid}")
async def get_order(oid: str, user=Depends(require_store)):
    o = await db.orders.find_one({"id": oid, "store_id": user["store_id"]}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    return o


@api.post("/orders/{oid}/dispatch")
async def dispatch_order(oid: str, body: DispatchIn, user=Depends(require_store)):
    o = await db.orders.find_one({"id": oid, "store_id": user["store_id"]})
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    m = await db.motoboys.find_one({"id": body.motoboy_id, "store_id": user["store_id"]})
    if not m:
        raise HTTPException(400, "Motoboy inválido")
    await db.orders.update_one(
        {"id": oid},
        {"$set": {"motoboy_id": body.motoboy_id, "status": "dispatched",
                  "dispatched_at": utcnow().isoformat()}},
    )
    o2 = await db.orders.find_one({"id": oid}, {"_id": 0})
    o2["motoboy"] = {k: m[k] for k in ("id", "name", "whatsapp") if k in m}
    return o2


@api.patch("/orders/{oid}/status")
async def update_status(oid: str, body: StatusIn, user=Depends(require_store)):
    upd = {"status": body.status}
    if body.status == "delivered":
        upd["delivered_at"] = utcnow().isoformat()
    r = await db.orders.update_one({"id": oid, "store_id": user["store_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Pedido não encontrado")
    return {"ok": True}


@api.delete("/orders/{oid}")
async def delete_order(oid: str, user=Depends(require_store)):
    await db.orders.delete_one({"id": oid, "store_id": user["store_id"]})
    return {"ok": True}


# ============ PUBLIC TRACKING (no auth) ============
@api.get("/track/{token}")
async def public_track(token: str):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "customer_whatsapp": 0})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "name": 1, "phone": 1})
    m = None
    if o.get("motoboy_id"):
        mo = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0})
        if mo:
            m = {"name": mo["name"], "vehicle": mo.get("vehicle"), "plate": mo.get("plate")}
    return {"order": o, "store": s, "motoboy": m}


@api.get("/motoboy-track/{token}")
async def motoboy_track_info(token: str):
    o = await db.orders.find_one({"motoboy_share_token": token}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Sessão de motoboy não encontrada")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "name": 1})
    m = None
    if o.get("motoboy_id"):
        mo = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "name": 1, "whatsapp": 1})
        m = mo
    return {
        "order": {"id": o["id"], "customer_name": o["customer_name"], "address": o["address"],
                  "total": o["total"], "status": o["status"], "notes": o.get("notes"),
                  "tracking_token": o["tracking_token"]},
        "store": s, "motoboy": m,
    }


@api.post("/motoboy-track/{token}/location")
async def post_location(token: str, body: LocationIn):
    o = await db.orders.find_one({"motoboy_share_token": token})
    if not o:
        raise HTTPException(404, "Sessão inválida")
    loc = {**body.dict(), "at": utcnow().isoformat()}
    await db.orders.update_one({"id": o["id"]}, {"$set": {"last_location": loc}})
    await db.locations.insert_one({"order_id": o["id"], **loc})
    return {"ok": True}


@api.get("/track/{token}/location")
async def get_last_location(token: str):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "last_location": 1, "status": 1,
                                                              "dest_lat": 1, "dest_lng": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    eta_min = None
    if o.get("last_location") and o.get("dest_lat") is not None and o.get("dest_lng") is not None:
        km = _haversine_km((o["last_location"]["lat"], o["last_location"]["lng"]),
                            (o["dest_lat"], o["dest_lng"]))
        # assume avg 25 km/h in urban delivery
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
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "phone": 1, "name": 1})
    note = {
        "id": str(uuid.uuid4()), "order_id": o["id"], "store_id": o["store_id"],
        "message": body.message[:500], "customer_name": o["customer_name"],
        "at": utcnow().isoformat(), "read": False,
    }
    await db.notes.insert_one(note)
    phone = "".join(ch for ch in (s.get("phone") or "") if ch.isdigit())
    if phone and not phone.startswith("55"):
        phone = "55" + phone
    text = f"📝 Nota do cliente {o['customer_name']} (pedido #{o['id'][:8]}):\n{body.message}"
    wa = f"https://wa.me/{phone}?text={text}" if phone else None
    return {"ok": True, "wa_url": wa, "store": s.get("name")}


@api.get("/notes")
async def list_notes(user=Depends(require_store)):
    notes = await db.notes.find({"store_id": user["store_id"]}, {"_id": 0}).sort("at", -1).to_list(100)
    return notes


@api.patch("/notes/{nid}/read")
async def mark_note_read(nid: str, user=Depends(require_store)):
    await db.notes.update_one({"id": nid, "store_id": user["store_id"]}, {"$set": {"read": True}})
    return {"ok": True}


@api.get("/alerts")
async def live_alerts(user=Depends(require_store), stale_min: int = 5):
    """Compute alerts for currently dispatched orders of this store."""
    from datetime import datetime as _dt
    now = utcnow()
    orders = await db.orders.find({"store_id": user["store_id"], "status": "dispatched"},
                                    {"_id": 0, "id": 1, "customer_name": 1, "motoboy_id": 1,
                                     "last_location": 1, "dispatched_at": 1, "dest_lat": 1, "dest_lng": 1}).to_list(200)
    alerts = []
    for o in orders:
        loc = o.get("last_location")
        # rule 1: no location ping in stale_min
        if not loc:
            dispatched_at = o.get("dispatched_at")
            if dispatched_at:
                delta = (now - _dt.fromisoformat(dispatched_at)).total_seconds() / 60
                if delta > stale_min:
                    alerts.append({"order_id": o["id"], "customer_name": o["customer_name"],
                                    "type": "no_location", "minutes": int(delta),
                                    "message": f"Sem localização há {int(delta)} min desde o despacho"})
            continue
        last_at = _dt.fromisoformat(loc["at"])
        delta = (now - last_at).total_seconds() / 60
        if delta > stale_min:
            alerts.append({"order_id": o["id"], "customer_name": o["customer_name"],
                            "type": "stale_location", "minutes": int(delta),
                            "message": f"Motoboy parou de enviar localização há {int(delta)} min"})
            continue
        # rule 2: off-route — distance to destination is INCREASING over the last 3 points
        if o.get("dest_lat") is not None and o.get("dest_lng") is not None:
            recent = await db.locations.find({"order_id": o["id"]}, {"_id": 0, "lat": 1, "lng": 1}).sort("at", -1).to_list(3)
            if len(recent) == 3:
                dests = (o["dest_lat"], o["dest_lng"])
                d0 = _haversine_km((recent[2]["lat"], recent[2]["lng"]), dests)
                d1 = _haversine_km((recent[1]["lat"], recent[1]["lng"]), dests)
                d2 = _haversine_km((recent[0]["lat"], recent[0]["lng"]), dests)
                if d2 > d1 > d0 and (d2 - d0) > 0.3:  # moved 300m+ AWAY over 3 pings
                    alerts.append({"order_id": o["id"], "customer_name": o["customer_name"],
                                    "type": "off_route", "distance_km": round(d2, 2),
                                    "message": f"Se afastando do destino ({round((d2 - d0) * 1000)}m nos últimos pings)"})
    return {"alerts": alerts, "count": len(alerts)}


# ============ SEED ============
@app.on_event("startup")
async def seed_admin():
    if not await db.users.find_one({"role": "admin"}):
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "name": "Master Admin",
            "email": "admin@zappedidos.com", "password": hash_pw("admin123"),
            "role": "admin", "store_id": None,
            "created_at": utcnow().isoformat(),
        })
        logging.info("Master admin criado: admin@zappedidos.com / admin123")
    await db.orders.create_index("tracking_token")
    await db.orders.create_index("motoboy_share_token")


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
