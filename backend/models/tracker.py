"""Schemas Pydantic (PT-BR) dos endpoints do tracker."""
from typing import Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    email: EmailStr
    senha: str = Field(min_length=6, max_length=128)
    nome_loja: str = Field(min_length=1, max_length=120)
    telefone: Optional[str] = Field(default=None, max_length=30)


class LoginIn(BaseModel):
    email: EmailStr
    senha: str = Field(max_length=128)


class MotoboyIn(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    telefone: str = Field(min_length=8, max_length=30)
    veiculo: Optional[str] = Field(default="Moto", max_length=40)
    placa: Optional[str] = Field(default=None, max_length=15)


class OrderIn(BaseModel):
    cliente_nome: str = Field(min_length=1, max_length=120)
    cliente_whatsapp: str = Field(min_length=8, max_length=30)
    endereco: str = Field(min_length=3, max_length=300)
    itens: str = Field(min_length=1, max_length=2000)
    total: float = Field(ge=0)
    forma_pagamento: Optional[str] = Field(default="PIX", max_length=30)
    observacao: Optional[str] = Field(default=None, max_length=500)


class DispatchIn(BaseModel):
    motoboy_id: str


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None


class StatusIn(BaseModel):
    status: str


class LadConfigIn(BaseModel):
    token: str = Field(max_length=500)
    demo: Optional[bool] = False


class LadImportIn(BaseModel):
    uuid: str = Field(min_length=1, max_length=80)


class NoteIn(BaseModel):
    mensagem: str = Field(min_length=1, max_length=500)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: Dict[str, str]


class AdminCreateStoreIn(BaseModel):
    nome_loja: str = Field(min_length=1, max_length=120)
    nome_dono: str = Field(min_length=1, max_length=120)
    email_dono: EmailStr
    senha_dono: str = Field(min_length=6, max_length=128)
    telefone: Optional[str] = Field(default=None, max_length=30)
    plano: Optional[str] = "free"


class PlanIn(BaseModel):
    plano: str


class StoreToggleIn(BaseModel):
    ativa: bool = True
