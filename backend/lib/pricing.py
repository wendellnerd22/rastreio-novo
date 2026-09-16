"""Cotação local do pedido a partir do cardápio oficial da LAD.

Necessário porque o pagamento é cobrado ANTES de criar o pedido: sem enviar o pedido
não existe total oficial da LAD, então reproduzimos o cálculo com os preços do cardápio
(`GET /v1/cardapio`) — a mesma fonte que o servidor da LAD usa.

Limitação conhecida: cupons e grupos com regra de preço diferente de SOMA não são
cotáveis aqui; nesses casos `erros` volta preenchido e o fluxo deve cair para pagamento
na entrega / PIX nativo da LAD.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

REGRAS_SUPORTADAS = {"SOMA", "SEM_COBRANCA"}


def _find_produto(cardapio: Dict[str, Any], id_produto: int) -> Optional[Dict[str, Any]]:
    for cat in cardapio.get("categorias", []):
        for prod in cat.get("produtos", []):
            if int(prod.get("id", -1)) == int(id_produto):
                return prod
    return None


def quote(
    cardapio: Dict[str, Any],
    itens: List[Dict[str, Any]],
    valor_entrega: float = 0.0,
) -> Tuple[Dict[str, Any], List[str]]:
    """Devolve (cotacao, erros). Com erros preenchidos, não cobre nada antes."""
    erros: List[str] = []
    linhas: List[Dict[str, Any]] = []
    total_itens = 0.0

    for item in itens or []:
        prod = _find_produto(cardapio, int(item.get("idProduto", -1)))
        if prod is None:
            erros.append(f"Produto {item.get('idProduto')} não está no cardápio.")
            continue

        tamanhos = prod.get("tamanhos") or []
        unit = float(prod.get("preco") or 0)
        if tamanhos:
            if not item.get("idTamanho"):
                opcoes = ", ".join(f"{t['id']}={t['nome']}" for t in tamanhos)
                erros.append(f"Item ({prod['nome']}): informe 'idTamanho'. Disponíveis: {opcoes}.")
                continue
            tam = next((t for t in tamanhos if int(t["id"]) == int(item["idTamanho"])), None)
            if tam is None:
                erros.append(f"Item ({prod['nome']}): idTamanho inválido.")
                continue
            unit = float(tam.get("preco") or 0)

        nomes: List[str] = []
        for grupo_sel in item.get("opcionais") or []:
            grupo = next(
                (g for g in prod.get("gruposOpcionais", [])
                 if int(g["id"]) == int(grupo_sel.get("idGrupo", -1))),
                None,
            )
            if grupo is None:
                erros.append(f"Item ({prod['nome']}): grupo de opcionais inválido.")
                continue
            if str(grupo.get("regraPreco", "SOMA")).upper() not in REGRAS_SUPORTADAS:
                erros.append(
                    f"Item ({prod['nome']}): grupo '{grupo['nome']}' usa regra de preço "
                    f"{grupo.get('regraPreco')} e não pode ser cobrado antecipadamente."
                )
                continue
            for oid in grupo_sel.get("idsOpcoes") or []:
                opcao = next((o for o in grupo.get("opcoes", []) if int(o["id"]) == int(oid)), None)
                if opcao is None:
                    erros.append(f"Item ({prod['nome']}): opcional {oid} inválido.")
                    continue
                unit += float(opcao.get("preco") or 0)
                nomes.append(opcao["nome"])

        qtd = float(item.get("quantidade") or 1)
        total_linha = round(unit * qtd, 2)
        total_itens += total_linha
        linhas.append({
            "idProduto": prod["id"], "nome": prod["nome"], "quantidade": qtd,
            "opcionais": nomes, "valorUnitario": round(unit, 2), "valorTotal": total_linha,
        })

    total_itens = round(total_itens, 2)
    entrega = round(float(valor_entrega or 0), 2)
    cotacao = {
        "itens": linhas,
        "valorItens": total_itens,
        "valorEntrega": entrega,
        "valorTotal": round(total_itens + entrega, 2),
    }
    return cotacao, erros
