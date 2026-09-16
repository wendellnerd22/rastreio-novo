# PRD — ZapPedidos + LAD Delivery Tracker

## Problema original (resumo)
Cliente pediu para implementar a tela de tracker para rastreio do pedido (cliente + motoboy) sobre o projeto ZapPedidos, com painel de administrador (revendedor) e painel de cadastro do cliente/loja, permitindo cadastrar motoboys com WhatsApp e disparar rastreio via `wa.me`. Integração com API LAD Delivery v1 (documentação fornecida).

## Arquitetura
- Backend: FastAPI + MongoDB + JWT (bcrypt) + httpx (proxy LAD)
- Frontend: React 19 + React Router 7 + Tailwind + Shadcn/UI + Leaflet/OpenStreetMap + sonner
- Auth: JWT no localStorage; roles `admin` (revendedor) e `store` (lojista)
- Rastreio: motoboy compartilha `navigator.geolocation.watchPosition`; cliente faz polling do backend a cada 8s

## Personas
- Master Admin (revendedor): gerencia todas as lojas, ativa/desativa contas, vê estatísticas
- Lojista: cadastra motoboys, cria pedidos, despacha (dispara WhatsApp) e configura token LAD
- Cliente final: acessa link público de rastreio (mapa + timeline de status)
- Motoboy: acessa link público para compartilhar localização ao vivo

## Feito (2026-02)
- [x] Auth JWT (register/login/me) + seed do master admin
- [x] Multi-tenant (users → stores)
- [x] CRUD Motoboys por loja
- [x] CRUD Pedidos + dispatch + status
- [x] Rastreamento público: `/track/:token` (cliente) e `/motoboy/:token` (motoboy)
- [x] Mapa Leaflet com marcadores customizados
- [x] Disparo WhatsApp via `wa.me` para motoboy + cliente ao despachar
- [x] Integração LAD Delivery: salvar token, testar `/v1/loja`
- [x] Landing page com hero
- [x] Painel Admin: stats, lista de lojas, ativar/desativar
- [x] Painel Loja: tabs Pedidos, Motoboys, Configurações LAD

## Backlog (P1)
- Sincronizar pedidos automáticos vindos da API LAD (`GET /v1/pedidos/{uuid}`)
- Histórico de rota (breadcrumb no mapa) e ETA calculado
- Notificação push do status para o cliente
- Envio automático via WAHA (WhatsApp HTTP API) em vez de `wa.me`
- Recuperação de senha e trocar senha

## Backlog (P2)
- Relatórios/analytics por loja
- Multi-idioma
- Aplicativo dedicado ao motoboy (PWA offline)
