"""Auth: registro de loja, login (cookie zp_session + lockout), logout, me."""
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response

from lib.auth import User, check_senha, current_user, hash_senha
from lib.db import db
from lib.tracker import COOKIE_SECURE, set_session_cookie, utcnow
from lib.auth import COOKIE_NAME
from models.tracker import LoginIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(user: User) -> dict:
    return {"id": user.id, "email": user.email, "nome": user.nome, "role": user.role, "store_id": user.store_id}


@router.post("/register")
async def register(body: RegisterIn, response: Response):
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    sid = str(uuid.uuid4())
    user = User(email=body.email.lower(), nome=body.nome, role="lojista",
                store_id=sid, senha_hash=hash_senha(body.senha))
    await db.users.insert_one(user.model_dump())
    await db.stores.insert_one({
        "id": sid, "nome": body.nome_loja, "owner_id": user.id, "telefone": body.telefone,
        "lad_token": "", "lad_demo": False, "webhook_token": secrets.token_urlsafe(16),
        "plano": "free", "ativa": True, "created_at": utcnow(),
    })
    set_session_cookie(response, user)
    return {"user": _public(user)}


@router.post("/login")
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
    if user.role != "admin" and user.store_id:
        s = await db.stores.find_one({"id": user.store_id}, {"_id": 0, "ativa": 1})
        if s and s.get("ativa") is False:
            raise HTTPException(403, "Loja desativada. Fale com o revendedor.")
    set_session_cookie(response, user)
    return {"user": _public(user)}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE,
                           samesite="none" if COOKIE_SECURE else "lax")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return _public(user)
