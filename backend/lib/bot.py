"""Agente de atendimento (Gemini 3 Flash) que monta pedidos usando a API LAD v1."""
from __future__ import annotations

import json
import os
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from lib import orders, payments, pricing
from lib.lad import LadClient, LadError
from models.schemas import PaymentIntent, Store


@dataclass
class BotContext:
    store: Store
    session_id: str
    lad: LadClient
    payment_intent_id: Optional[str] = None


MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "consultar_loja",
        "description": "Consulta dados da loja: se está aberta, horários, formas de pagamento aceitas, pedido mínimo, entrega/retirada.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "consultar_cardapio",
        "description": "Retorna o cardápio: categorias, produtos, preços, tamanhos e grupos de opcionais com os IDs usados em criar_pedido.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "cotar_frete",
        "description": "Calcula o valor da entrega para um endereço. Use antes de fechar pedidos DELIVERY.",
        "parameters": {"type": "object", "properties": {
            "endereco": {"type": "string"}, "numero": {"type": "string"},
            "bairro": {"type": "string"}, "cidade": {"type": "string"},
            "estado": {"type": "string"}, "cep": {"type": "string"},
        }, "required": ["bairro", "cidade"]},
    }},
    {"type": "function", "function": {
        "name": "criar_pedido",
        "description": "Cria o pedido na loja. NÃO envie preços — o servidor calcula tudo. Confirme o total com o cliente usando a resposta.",
        "parameters": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": ["DELIVERY", "RETIRADA"]},
            "cliente": {"type": "object", "properties": {
                "nome": {"type": "string"}, "telefone": {"type": "string"}},
                "required": ["nome", "telefone"]},
            "itens": {"type": "array", "items": {"type": "object", "properties": {
                "idProduto": {"type": "integer"},
                "idTamanho": {"type": "integer"},
                "quantidade": {"type": "number"},
                "observacao": {"type": "string"},
                "opcionais": {"type": "array", "items": {"type": "object", "properties": {
                    "idGrupo": {"type": "integer"},
                    "idsOpcoes": {"type": "array", "items": {"type": "integer"}},
                }, "required": ["idGrupo", "idsOpcoes"]}},
            }, "required": ["idProduto", "quantidade"]}},
            "enderecoEntrega": {"type": "object", "properties": {
                "endereco": {"type": "string"}, "numero": {"type": "string"},
                "bairro": {"type": "string"}, "complemento": {"type": "string"},
                "cidade": {"type": "string"}, "estado": {"type": "string"},
                "cep": {"type": "string"}, "pontoReferencia": {"type": "string"},
            }},
            "pagamento": {"type": "object", "properties": {
                "forma": {"type": "string"}, "trocoPara": {"type": "number"},
                "observacao": {"type": "string"}}, "required": ["forma"]},
            "cupom": {"type": "string"},
            "observacao": {"type": "string"},
        }, "required": ["tipo", "cliente", "itens", "pagamento"]},
    }},
    {"type": "function", "function": {
        "name": "consultar_pedido",
        "description": "Consulta o status atual de um pedido pelo uuid.",
        "parameters": {"type": "object", "properties": {"uuid": {"type": "string"}}, "required": ["uuid"]},
    }},
    {"type": "function", "function": {
        "name": "verificar_pagamento",
        "description": ("Verifica se a cobrança gerada por criar_pedido já foi paga. Use quando o cliente "
                        "disser que pagou. Se voltar status 'aprovado', o pedido é enviado à loja "
                        "automaticamente e a resposta traz o uuid do pedido."),
        "parameters": {"type": "object", "properties": {
            "intentId": {"type": "string", "description": "id da cobrança devolvido por criar_pedido"},
        }, "required": ["intentId"]},
    }},
]

BASE_PROMPT = """Você é o atendente virtual de WhatsApp da loja "{nome_loja}".
Fale em português do Brasil, com mensagens curtas, cordiais e objetivas — estilo WhatsApp.

REGRAS ABSOLUTAS:
- Nunca calcule nem prometa preços por conta própria: use SEMPRE os valores retornados pelas ferramentas.
- Consulte o cardápio antes de sugerir produtos; só ofereça o que existe nele.
- Se o produto tiver tamanhos, pergunte o tamanho antes de adicionar.
- Antes de criar o pedido você precisa de: tipo (entrega ou retirada), nome e telefone do cliente,
  itens, endereço completo (se entrega) e forma de pagamento (use apenas as formas de consultar_loja).
- Antes de chamar criar_pedido, confirme com o cliente o resumo do pedido e espere um "sim".
- Depois de criar_pedido, repita ao cliente os itens e o valorTotal retornado pela ferramenta.
- Se uma ferramenta devolver erro, leia a descrição e corrija exatamente o que ela pede, sem culpar o cliente.
- Nunca invente formas de pagamento genéricas como "cartão": use os rótulos exatos da loja.
- PAGAMENTO ANTECIPADO: quando criar_pedido devolver "aguardandoPagamento", o pedido AINDA NÃO foi
  enviado à loja. Envie ao cliente o código PIX (copia e cola) ou o link de pagamento exatamente como
  vier na resposta, informe o valor total e diga que a loja recebe o pedido assim que o pagamento for
  confirmado. Quando o cliente disser que pagou, chame verificar_pagamento com o intentId.
  Nunca afirme que o pedido foi feito antes de verificar_pagamento retornar status "aprovado".
{extra}"""

_SESSIONS: Dict[str, Any] = {}
_CLIENT: Optional[genai.Client] = None


def _client() -> genai.Client:
    global _CLIENT
    if _CLIENT is None:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY não configurado no .env — crie uma chave gratuita em "
                "aistudio.google.com/apikey"
            )
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def _tool() -> types.Tool:
    declarations = [
        types.FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters_json_schema=t["function"]["parameters"],
        )
        for t in TOOLS
    ]
    return types.Tool(function_declarations=declarations)


def _new_chat(session_key: str, system_message: str):
    config = types.GenerateContentConfig(
        system_instruction=system_message,
        tools=[_tool()],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return _client().aio.chats.create(model=MODEL_NAME, config=config)


def reset_session(session_key: str) -> None:
    _SESSIONS.pop(session_key, None)


async def _dispatch(ctx: "BotContext", name: str, args: Dict[str, Any]) -> Tuple[Any, bool]:
    lad = ctx.lad
    try:
        if name == "consultar_loja":
            return await lad.loja(), True
        if name == "consultar_cardapio":
            return await lad.cardapio(), True
        if name == "cotar_frete":
            return await lad.frete(args), True
        if name == "criar_pedido":
            return await _criar_pedido(ctx, dict(args))
        if name == "consultar_pedido":
            return await lad.pedido(args.get("uuid", "")), True
        if name == "verificar_pagamento":
            return await _verificar_pagamento(ctx, str(args.get("intentId", "")))
    except LadError as exc:
        return {"codigo": exc.status, "titulo": "Erro", "descricao": exc.descricao}, False
    except Exception as exc:  # noqa: BLE001
        return {"codigo": 500, "titulo": "Erro", "descricao": str(exc)}, False
    return {"codigo": 400, "descricao": f"Ferramenta desconhecida: {name}"}, False


def _normaliza(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).upper().strip()


def metodo_para_forma(forma: str) -> Optional[str]:
    """"pix" / "cartao" quando a forma exige pagamento online; None = pagar na entrega."""
    norm = _normaliza(forma)
    if "PIX" in norm:
        return "pix"
    if "CREDIT" in norm or "DEBIT" in norm or "CARTAO" in norm or "CARD" in norm:
        return "cartao"
    return None


async def _criar_pedido(ctx: "BotContext", payload: Dict[str, Any]) -> Tuple[Any, bool]:
    """Com cobrança antecipada ligada, gera a cobrança e NÃO envia o pedido à LAD ainda."""
    forma = str((payload.get("pagamento") or {}).get("forma", ""))
    metodo = metodo_para_forma(forma)
    cobrar = ctx.store.cobrar_antes and metodo is not None and not payload.get("cupom")

    if not cobrar:
        payload.setdefault("idempotencyKey", str(uuid.uuid4()))
        return await ctx.lad.criar_pedido(payload), True

    cardapio = await ctx.lad.cardapio()
    valor_entrega = 0.0
    if str(payload.get("tipo", "")).upper() == "DELIVERY":
        endereco = payload.get("enderecoEntrega") or {}
        frete = await ctx.lad.frete(endereco)
        valor_entrega = float(frete.get("valorEntrega") or 0)

    cotacao, erros = pricing.quote(cardapio, payload.get("itens") or [], valor_entrega)
    if erros:
        return {"codigo": 400, "titulo": "BAD REQUEST",
                "descricao": " ".join(erros) + " Corrija os itens ou ofereça pagamento na entrega."}, False

    cliente = payload.get("cliente") or {}
    intent = PaymentIntent(
        store_id=ctx.store.id, session_id=ctx.session_id, metodo=metodo, forma_lad=forma,
        valor=cotacao["valorTotal"], valor_itens=cotacao["valorItens"],
        valor_entrega=cotacao["valorEntrega"],
        cliente_nome=cliente.get("nome", ""), cliente_telefone=str(cliente.get("telefone", "")),
        pedido_payload=payload,
    )
    descricao = f"Pedido {ctx.store.nome}"
    email = f"cliente-{intent.id[:8]}@zappedidos.com"
    cobranca = (await payments.criar_cobranca_pix(intent.id, intent.valor, descricao, email)
                if metodo == "pix"
                else await payments.criar_checkout_cartao(intent.id, intent.valor, descricao, email))

    intent.provider = cobranca["provider"]
    intent.provider_payment_id = cobranca["provider_payment_id"]
    intent.status = cobranca["status"]
    intent.pix_copia_e_cola = cobranca["pix_copia_e_cola"]
    intent.pix_qr_base64 = cobranca["pix_qr_base64"]
    intent.checkout_url = cobranca["checkout_url"]
    await orders.save_intent(intent)
    ctx.payment_intent_id = intent.id

    resposta = {
        "aguardandoPagamento": True,
        "intentId": intent.id,
        "metodo": metodo,
        "forma": forma,
        "valorItens": intent.valor_itens,
        "valorEntrega": intent.valor_entrega,
        "valorTotal": intent.valor,
        "itens": cotacao["itens"],
        "instrucoes": ("Envie o código PIX abaixo ao cliente para copiar e colar no banco."
                       if metodo == "pix"
                       else "Envie o link de pagamento abaixo para o cliente pagar com cartão."),
        "avisoObrigatorio": ("O pedido só será enviado à loja após a confirmação do pagamento. "
                             "Chame verificar_pagamento com este intentId quando o cliente disser que pagou."),
    }
    if intent.pix_copia_e_cola:
        resposta["pixCopiaECola"] = intent.pix_copia_e_cola
    if intent.checkout_url:
        resposta["linkPagamento"] = intent.checkout_url
    return resposta, True


async def _verificar_pagamento(ctx: "BotContext", intent_id: str) -> Tuple[Any, bool]:
    intent = await orders.load_intent(intent_id)
    if intent is None or intent.store_id != ctx.store.id:
        return {"codigo": 404, "descricao": "Cobrança não encontrada para esta loja."}, False
    intent = await orders.sincronizar(intent)
    ctx.payment_intent_id = intent.id
    if intent.status == payments.APROVADO and intent.lad_order_uuid:
        return {"status": "aprovado", "pedidoUuid": intent.lad_order_uuid,
                "valorTotal": intent.valor,
                "mensagem": "Pagamento confirmado e pedido enviado à loja."}, True
    if intent.status == payments.APROVADO:
        return {"status": "aprovado", "pedidoUuid": None, "erroLad": intent.lad_erro,
                "mensagem": "Pagamento confirmado, mas a loja recusou o pedido. Leia erroLad."}, False
    return {"status": intent.status, "valorTotal": intent.valor,
            "mensagem": "Pagamento ainda não confirmado. Peça ao cliente para concluir o pagamento."}, True


RESUMOS = {
    "consultar_loja": "Consultou os dados da loja",
    "consultar_cardapio": "Consultou o cardápio",
    "cotar_frete": "Cotou o frete",
    "criar_pedido": "Criou o pedido",
    "consultar_pedido": "Consultou o pedido",
    "verificar_pagamento": "Verificou o pagamento",
}


async def run_turn(session_key: str, system_message: str, ctx: BotContext, message: str):
    """Executa um turno da conversa. Devolve (texto, traces, pedido, intent_id)."""
    chat = _SESSIONS.get(session_key)
    if chat is None:
        chat = _new_chat(session_key, system_message)
        _SESSIONS[session_key] = chat

    response = await chat.send_message(message)
    traces: List[Dict[str, Any]] = []
    pedido: Any = None
    guard = 0

    while getattr(response, "function_calls", None) and guard < 8:
        guard += 1
        partes_resposta: List[types.Part] = []
        for fc in response.function_calls:
            args = dict(fc.args or {})
            result, ok = await _dispatch(ctx, fc.name, args)
            if fc.name == "criar_pedido" and ok and not result.get("aguardandoPagamento"):
                pedido = result
            if fc.name == "criar_pedido" and ok and result.get("aguardandoPagamento"):
                traces.append({"name": "cobranca_gerada", "ok": True,
                               "resumo": f"Cobrança {result['metodo']} de R$ {result['valorTotal']:.2f} gerada"})
            traces.append({
                "name": fc.name,
                "ok": ok,
                "resumo": RESUMOS.get(fc.name, fc.name) if ok else str(result.get("descricao") or result.get("mensagem", "erro"))[:180],
            })
            partes_resposta.append(
                types.Part.from_function_response(
                    name=fc.name, response={"result": json.loads(json.dumps(result, ensure_ascii=False, default=str))}
                )
            )
        response = await chat.send_message(partes_resposta)

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        text = "Desculpe, não consegui responder agora. Pode repetir?"
    return text, traces, pedido, ctx.payment_intent_id
