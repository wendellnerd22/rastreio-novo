"""Sessão por cookie httpOnly (JWT assinado) + hashing de senha."""
from __future__ import annotations

import os
import secrets
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Cookie, Depends, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from lib.db import db

logger = logging.getLogger(__name__)

COOKIE_NAME = "zp_session"
_env_secret = os.environ.get("SESSION_SECRET", "").strip()
if _env_secret:
    SECRET = _env_secret
else:
    # Sem SESSION_SECRET no .env: gera um segredo aleatório por processo em vez de um
    # valor fixo (o antigo "zappedidos-dev-secret" está público no repositório do GitHub —
    # qualquer um poderia forjar um cookie de admin com ele). Isso não é ideal (sessões
    # antigas expiram a cada reinício), mas é seguro; configure SESSION_SECRET em produção.
    SECRET = secrets.token_hex(32)
    logger.warning(
        "SESSION_SECRET não definido no .env — usando um valor aleatório temporário. "
        "Configure SESSION_SECRET em produção ou todas as sessões caem a cada reinício."
    )
ALGO = "HS256"
TTL_DAYS = 7

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    nome: str = ""
    role: str = "lojista"  # "admin" | "lojista"
    store_id: Optional[str] = None
    senha_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserPublic(BaseModel):
    id: str
    email: str
    nome: str
    role: str
    store_id: Optional[str] = None


def hash_senha(senha: str) -> str:
    return pwd.hash(senha)


def check_senha(senha: str, senha_hash: str) -> bool:
    try:
        return pwd.verify(senha, senha_hash)
    except Exception:  # noqa: BLE001
        return False


def make_token(user: User) -> str:
    payload = {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)}
    return jwt.encode(payload, SECRET, algorithm=ALGO)


async def optional_user(zp_session: Optional[str] = Cookie(default=None)) -> Optional[User]:
    if not zp_session:
        return None
    try:
        payload = jwt.decode(zp_session, SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    doc = await db.users.find_one({"id": payload.get("sub")})
    if not doc:
        return None
    doc.pop("_id", None)
    return User(**doc)


async def current_user(user: Optional[User] = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar")
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas o revendedor pode fazer isso")
    return user


def can_access_store(user: User, store_id: str) -> bool:
    return user.role == "admin" or user.store_id == store_id


async def ensure_admin_seed() -> None:
    """Cria a conta inicial do revendedor se ainda não existir nenhum admin."""
    existing = await db.users.find_one({"role": "admin"})
    if existing:
        return
    senha = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not senha:
        # A antiga senha padrão "Zap@2026" está pública no repositório do GitHub —
        # qualquer um poderia logar como admin com ela. Gera uma senha aleatória e
        # só mostra nos logs do servidor uma única vez, na criação da conta.
        senha = secrets.token_urlsafe(12)
        logger.warning(
            "ADMIN_PASSWORD não definido — senha do admin gerada automaticamente: %s "
            "(troque assim que entrar; isso não aparece de novo)", senha,
        )
    admin = User(
        email=os.environ.get("ADMIN_EMAIL", "admin@zappedidos.com"),
        nome="Revendedor",
        role="admin",
        senha_hash=hash_senha(senha),
    )
    await db.users.insert_one(admin.model_dump())
