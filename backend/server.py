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
        "active": True, "created_at": now,
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
    doc = {
        "id": oid, "store_id": user["store_id"], **body.dict(),
        "status": "pending", "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12),
        "motoboy_share_token": secrets.token_urlsafe(12),
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
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "last_location": 1, "status": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    return o


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
