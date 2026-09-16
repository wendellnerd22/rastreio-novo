import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StoreCreate(BaseModel):
    nome: str
    token: str = ""
    demo: bool = False
    bot_prompt: str = ""
    cobrar_antes: bool = True
    lojista_email: str = ""
    lojista_senha: str = ""


class StoreUpdate(BaseModel):
    nome: Optional[str] = None
    token: Optional[str] = None
    demo: Optional[bool] = None
    bot_prompt: Optional[str] = None
    cobrar_antes: Optional[bool] = None
    lojista_email: Optional[str] = None
    lojista_senha: Optional[str] = None


class Store(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nome: str
    token: str = ""
    demo: bool = False
    bot_prompt: str = ""
    cobrar_antes: bool = True
    conexao_ok: bool = False
    conexao_msg: str = "Nunca testada"
    api_key: str = Field(default_factory=lambda: uuid.uuid4().hex)
    lojista_email: str = ""
    created_at: datetime = Field(default_factory=_now)


class ConnectionResult(BaseModel):
    ok: bool
    mensagem: str
    nome_loja: Optional[str] = None
    aberta_agora: Optional[bool] = None


class OrderRecord(BaseModel):
    id: str
    store_id: str
    session_id: str = ""
    cliente_nome: str = ""
    cliente_telefone: str = ""
    tipo: str = "DELIVERY"
    status_codigo: str = "E"
    status_descricao: str = "Pendente"
    valor_total: float = 0.0
    data_pedido: str = ""
    demo: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    rota_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class Motoboy(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    store_id: str
    nome: str
    telefone: str
    ativo: bool = True
    traccar_device_id: Optional[int] = None
    traccar_unique_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class Route(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    store_id: str
    motoboy_id: str
    motoboy_nome: str
    pedido_ids: list[str] = Field(default_factory=list)
    traccar_device_id: Optional[int] = None
    tracking_url: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ToolTrace(BaseModel):
    name: str
    ok: bool
    resumo: str


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    store_id: str
    role: str  # "user" | "bot"
    text: str
    tools: List[ToolTrace] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


class ChatResponse(BaseModel):
    reply: str
    tools: List[ToolTrace] = Field(default_factory=list)
    order_uuid: Optional[str] = None
    payment_intent_id: Optional[str] = None


class PaymentIntent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    session_id: str = ""
    metodo: str = "pix"  # "pix" | "cartao"
    forma_lad: str = ""  # rótulo oficial da loja gravado no pedido
    status: str = "pendente"  # pendente | aprovado | rejeitado | expirado
    provider: str = "simulado"  # simulado | mercadopago
    provider_payment_id: str = ""
    valor: float = 0.0
    valor_itens: float = 0.0
    valor_entrega: float = 0.0
    cliente_nome: str = ""
    cliente_telefone: str = ""
    pix_copia_e_cola: str = ""
    pix_qr_base64: str = ""
    checkout_url: str = ""
    pedido_payload: dict[str, Any] = Field(default_factory=dict)
    lad_order_uuid: Optional[str] = None
    lad_erro: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    approved_at: Optional[datetime] = None
