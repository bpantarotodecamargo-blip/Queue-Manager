# Workspace

## Overview

This project hosts a Portuguese-language Discord queue bot (`bot/`) plus the original pnpm monorepo scaffolding.

## Discord Queue Bot

Located in `bot/` (Python 3.11, discord.py 2.7+). Runs via the `Discord Queue Bot` workflow (`python bot/main.py`).

### Features

- **4 categorias × até 4 modos** (Mobile, Emulador, Misto, Tático).
- **Painel `/painel`** com botões para cada categoria + Config Geral, Embed Global, Filas ON/OFF e Publicar.
- **Embed Global** (botão 🎨 no painel): banner, thumbnail e cor padrão aplicados a todos os embeds. Filas individuais podem sobrescrever banner/thumb.
- **Cargos configuráveis:**
  - 👑 **Permissão Máxima** — pode usar todos os comandos administrativos.
  - 🛡️ **Cargo ADM** — pingado nas partidas e adicionado ao canal após confirmação.
  - 🤝 **Cargo Mediador** — pode entrar no painel de mediadores; pingado se nenhum mediador estiver na fila.
- **Filas ON/OFF** (botão no painel ou `/filas_off` / `/filas_on`): bloqueia entrada nas filas e atualiza mensagem de status nos canais.
- **Painel de Mediadores** (`/painel_mediador`): mediadores cadastram PIX (nome, tipo, chave) e entram em fila própria. Quando uma partida é confirmada, o próximo mediador é puxado e o PIX dele é exibido no canal da partida.
- **Persistência** — toda config em `bot/config.json`. Views persistentes via `add_view` no `setup_hook`.
- **Health server opcional** — se `PORT` estiver definido, abre HTTP em `0.0.0.0:PORT` para keep-alive.

### Slash commands

- `/painel` — painel de config (admin/permissão máxima)
- `/criarfilas` — publica os embeds nas channels configuradas
- `/painel_mediador` — publica o painel de mediadores no canal atual
- `/filas_off` — desativa filas globalmente
- `/filas_on` — reativa filas
- `/aparencia` — personaliza apelido, foto, banner e bio (informativa) do bot **por servidor**
- `/vencedor <usuario>` — define o vencedor da partida atual (canal `partida-...`), exibe embed de vitória e fecha o canal em 10 segundos. Disponível para admin/permissão máxima/mediador.
- `/painel_streamer` — publica o painel da fila do streamer no canal atual.
- `/streamer <usuario>` — define quem é o streamer da fila (admin only).

### Fila do Streamer

Painel persistente onde jogadores entram para enfrentar o streamer:
- **Modos:** 1v1, 2v2, 3v3, 4v4 — define quantas pessoas são chamadas por vez (modo/2).
- **Botões:** Entrar, Sair, Chamar Próximo (streamer/admin), Abrir/Fechar (streamer/admin), Configurar (admin), **Editar Embed (admin)**.
- **Editar Embed:** título, banner e thumbnail próprios do painel (mesmo sistema disponível também no painel de mediadores). Vazio = usa o embed global como fallback.
- Quando o streamer chama o próximo, é criado um canal `streamer-<modo>-<id>` com permissões só para o streamer + os chamados, com mention de todos.
- Use `/vencedor` no canal da partida para fechar.

### Limitações conhecidas (Discord API)

- A "Bio" / "Sobre Mim" do bot é **global** e só pode ser editada no Developer Portal. O `/aparencia` salva a bio como texto informativo deste servidor.
- Trocas de avatar/banner/apelido são limitadas pela API do Discord (rate limit).

### Pré-requisitos no Discord Developer Portal

- **Server Members Intent** ativado (necessário para resolver cargos de membros).
- **Message Content Intent** ativado.
- Token do bot em `DISCORD_TOKEN` (secret do Replit).

## Monorepo (legado)

pnpm workspace monorepo using TypeScript. Cada pacote gerencia suas próprias dependências.

### Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

### Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.
