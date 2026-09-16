"""Cliente da API Pública LAD Delivery v1 com fallback para dados de demonstração."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from lib.net_retry import RetriesExhausted, with_retry

LAD_BASE_URL = os.environ.get("LAD_BASE_URL", "https://api2.laddelivery.com.br")
TIMEOUT = 25.0


class LadError(Exception):
    def __init__(self, status: int, descricao: str):
        super().__init__(descricao)
        self.status = status
        self.descricao = descricao


# ---------------------------------------------------------------- demo dataset
DEMO_LOJA: Dict[str, Any] = {
    "id": 1508,
    "nome": "Du Cheff Burguer (Demo)",
    "telefone": "(51) 99999-9999",
    "endereco": "Rua Natal, 123, Centro, Porto Alegre",
    "abertaAgora": True,
    "horarios": [
        {"diaDaSemana": d, "diaDaSemanaLabel": lbl, "abre": "18:00", "fecha": "23:30"}
        for d, lbl in [
            (1, "Domingo"), (2, "Segunda-feira"), (3, "Terça-feira"), (4, "Quarta-feira"),
            (5, "Quinta-feira"), (6, "Sexta-feira"), (7, "Sábado"),
        ]
    ],
    "pedidoMinimo": 20.0,
    "entregaDisponivel": True,
    "retiradaDisponivel": True,
    "formasPagamento": ["DINHEIRO", "PIX", "CREDITO", "DEBITO"],
    "mensagemRetirada": "Retire em 40 minutos",
    "moeda": "BRL",
}

DEMO_CARDAPIO: Dict[str, Any] = {
    "idLoja": 1508,
    "nomeLoja": "Du Cheff Burguer (Demo)",
    "lojaAbertaAgora": True,
    "categorias": [
        {
            "id": 12,
            "nome": "Lanches",
            "produtos": [
                {
                    "id": 320599, "nome": "X-Salada",
                    "descricao": "Pão, hambúrguer 160g, queijo, alface e tomate",
                    "preco": 29.9, "precoOriginal": None, "imagemUrl": None,
                    "quantidadeMultipla": 1.0, "tamanhos": [],
                    "gruposOpcionais": [{
                        "id": 55, "nome": "Adicionais", "minimo": 0, "maximo": 3,
                        "regraPreco": "SOMA",
                        "opcoes": [
                            {"id": 1001, "nome": "Bacon extra", "preco": 3.5},
                            {"id": 1002, "nome": "Queijo extra", "preco": 3.0},
                            {"id": 1003, "nome": "Ovo", "preco": 2.5},
                        ],
                    }],
                },
                {
                    "id": 320600, "nome": "X-Bacon",
                    "descricao": "Pão, hambúrguer 160g, queijo e bacon crocante",
                    "preco": 34.9, "precoOriginal": None, "imagemUrl": None,
                    "quantidadeMultipla": 1.0, "tamanhos": [], "gruposOpcionais": [],
                },
            ],
        },
        {
            "id": 13,
            "nome": "Pizzas",
            "produtos": [{
                "id": 330100, "nome": "Pizza Calabresa",
                "descricao": "Molho, mussarela, calabresa e cebola",
                "preco": 49.9, "precoOriginal": None, "imagemUrl": None,
                "quantidadeMultipla": 1.0,
                "tamanhos": [
                    {"id": 4, "nome": "Grande", "preco": 59.9},
                    {"id": 5, "nome": "Pequena", "preco": 39.9},
                ],
                "gruposOpcionais": [],
            }],
        },
        {
            "id": 14,
            "nome": "Bebidas",
            "produtos": [
                {"id": 340001, "nome": "Coca-Cola Lata 350ml", "descricao": "Gelada",
                 "preco": 7.0, "precoOriginal": None, "imagemUrl": None,
                 "quantidadeMultipla": 1.0, "tamanhos": [], "gruposOpcionais": []},
                {"id": 340002, "nome": "Suco de Laranja 500ml", "descricao": "Natural",
                 "preco": 12.0, "precoOriginal": None, "imagemUrl": None,
                 "quantidadeMultipla": 1.0, "tamanhos": [], "gruposOpcionais": []},
            ],
        },
    ],
    "avisos": ["Dados de demonstração — conecte um token LAD válido para o cardápio real."],
}


class LadClient:
    """Chama a API LAD. Se `demo` estiver ligado, responde com dados locais."""

    def __init__(self, token: str, demo: bool = False):
        self.token = token
        self.demo = demo

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, json_body: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            try:
                resp = await with_retry(
                    lambda: http.request(method, f"{LAD_BASE_URL}{path}",
                                         headers=self._headers, json=json_body),
                    nome="API LAD",
                )
            except RetriesExhausted as exc:
                raise LadError(503, f"API LAD indisponível (rede instável): {exc}") from exc
            except httpx.HTTPError as exc:
                raise LadError(503, f"Falha de rede ao contatar a API LAD: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                descricao = body.get("descricao") or body.get("titulo") or resp.text
            except Exception:
                descricao = resp.text or f"Erro HTTP {resp.status_code}"
            raise LadError(resp.status_code, descricao)
        return resp.json()

    async def loja(self) -> Dict[str, Any]:
        if self.demo:
            return DEMO_LOJA
        return await self._request("GET", "/v1/loja")

    async def cardapio(self) -> Dict[str, Any]:
        if self.demo:
            return DEMO_CARDAPIO
        return await self._request("GET", "/v1/cardapio")

    async def frete(self, payload: dict) -> Dict[str, Any]:
        if self.demo:
            return {"valorEntrega": 7.0, "moeda": "BRL",
                    "mensagem": "Entrega disponível para o endereço informado. (demo)"}
        return await self._request("POST", "/v1/frete", payload)

    async def criar_pedido(self, payload: dict) -> Dict[str, Any]:
        if self.demo:
            return _demo_pedido(payload)
        return await self._request("POST", "/v1/pedidos", payload)

    async def pedido(self, uuid_: str) -> Dict[str, Any]:
        if self.demo:
            raise LadError(404, "Pedido não encontrado (modo demonstração).")
        return await self._request("GET", f"/v1/pedidos/{uuid_}")


def _find_produto(id_produto: int):
    for cat in DEMO_CARDAPIO["categorias"]:
        for prod in cat["produtos"]:
            if prod["id"] == id_produto:
                return prod
    return None


def _demo_pedido(payload: dict) -> Dict[str, Any]:
    """Calcula o pedido localmente, imitando a resposta oficial da LAD."""
    from datetime import datetime
    import uuid as _uuid

    itens_out = []
    total_itens = 0.0
    for item in payload.get("itens", []):
        prod = _find_produto(int(item["idProduto"]))
        if prod is None:
            raise LadError(400, f"Produto {item['idProduto']} não existe no cardápio de demonstração.")
        if prod["tamanhos"] and not item.get("idTamanho"):
            opcoes = ", ".join(f"{t['id']}={t['nome']}" for t in prod["tamanhos"])
            raise LadError(400, f"Item ({prod['nome']}): informe 'idTamanho'. Tamanhos disponíveis: {opcoes}.")
        unit = prod["preco"]
        if item.get("idTamanho"):
            tam = next((t for t in prod["tamanhos"] if t["id"] == int(item["idTamanho"])), None)
            if tam is None:
                opcoes = ", ".join(f"{t['id']}={t['nome']}" for t in prod["tamanhos"])
                raise LadError(400, f"Item ({prod['nome']}): idTamanho inválido. Disponíveis: {opcoes}.")
            unit = tam["preco"]
        nomes_opcionais = []
        for grupo in item.get("opcionais") or []:
            g = next((g for g in prod["gruposOpcionais"] if g["id"] == int(grupo["idGrupo"])), None)
            if g is None:
                continue
            for oid in grupo.get("idsOpcoes", []):
                o = next((o for o in g["opcoes"] if o["id"] == int(oid)), None)
                if o:
                    unit += o["preco"]
                    nomes_opcionais.append(o["nome"])
        qtd = float(item.get("quantidade", 1))
        total = round(unit * qtd, 2)
        total_itens += total
        itens_out.append({
            "idProduto": prod["id"], "nome": prod["nome"], "quantidade": qtd,
            "opcionais": nomes_opcionais, "valorUnitario": round(unit, 2),
            "valorTotal": total, "observacao": item.get("observacao"),
        })

    total_itens = round(total_itens, 2)
    if total_itens < DEMO_LOJA["pedidoMinimo"]:
        raise LadError(400, f"Pedido mínimo da loja é R$ {DEMO_LOJA['pedidoMinimo']:.2f}. "
                            f"Total dos itens: R$ {total_itens:.2f}.")
    entrega = 7.0 if payload.get("tipo") == "DELIVERY" else 0.0
    forma = (payload.get("pagamento") or {}).get("forma", "DINHEIRO")
    if forma.strip().upper() not in DEMO_LOJA["formasPagamento"]:
        raise LadError(400, "Forma de pagamento inválida. Aceitas: "
                            + ", ".join(DEMO_LOJA["formasPagamento"]) + ".")
    forma = forma.strip().upper()
    return {
        "uuid": payload.get("idempotencyKey") or str(_uuid.uuid4()),
        "jaExistia": False,
        "status": {"codigo": "P" if forma == "PIX" else "E",
                   "descricao": "Aguardando pagamento" if forma == "PIX" else "Pendente"},
        "dataPedido": datetime.now().isoformat(timespec="seconds"),
        "tipo": payload.get("tipo", "DELIVERY"),
        "itens": itens_out,
        "valorItens": total_itens,
        "valorEntrega": entrega,
        "desconto": 0.0,
        "valorTotal": round(total_itens + entrega, 2),
        "pagamento": {
            "forma": forma,
            "pixCopiaECola": "00020126DEMO-PIX-COPIA-E-COLA-5204000053039865802BR" if forma == "PIX" else None,
            "checkoutUrl": None,
            "mensagem": "Aguardando pagamento via PIX." if forma == "PIX"
                        else "Pagamento combinado na entrega/retirada.",
        },
        "motivoCancelamento": None,
        "acompanhamentoUrl": None,
    }
