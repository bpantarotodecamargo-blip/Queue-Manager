import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, ChannelSelect, RoleSelect, Select
import aiohttp
import json
import os
import asyncio
import uuid
import re
import threading
import http.server
from pathlib import Path

TOKEN = os.environ.get("DISCORD_TOKEN")
CONFIG_FILE = Path(__file__).parent / "config.json"

# ──────────────────────────────────────────────
# Estrutura de categorias e modos
# ──────────────────────────────────────────────

CATEGORIAS = ["Mobile", "Emulador", "Misto", "Tático"]

MODOS_POR_CATEGORIA = {
    "Mobile":   ["1v1", "2v2", "3v3", "4v4"],
    "Emulador": ["1v1", "2v2", "3v3", "4v4"],
    "Misto":    ["2v2", "3v3", "4v4"],
    "Tático":   ["1v1", "2v2", "3v3", "4v4"],
}

EMOJI_CATEGORIA = {
    "Mobile":   "📱",
    "Emulador": "💻",
    "Misto":    "🔀",
    "Tático":   "🎯",
}

EMOJI_MODO = {"1v1": "⚔️", "2v2": "👥", "3v3": "🛡️", "4v4": "🎮"}

JOGADORES_MODO = {"1v1": 2, "2v2": 4, "3v3": 6, "4v4": 8}

COR_PADRAO = 0x2ECC71

# Lista plana de todas as chaves de modo
ALL_MODOS: list[str] = [
    f"{cat}_{m}"
    for cat in CATEGORIAS
    for m in MODOS_POR_CATEGORIA[cat]
]


def chave(categoria: str, modo: str) -> str:
    return f"{categoria}_{modo}"


def split_chave(ch: str):
    """Retorna (categoria, modo) a partir de uma chave."""
    partes = ch.split("_", 1)
    return partes[0], partes[1]


def display(ch: str) -> str:
    """Ex: 'Mobile_1v1' → 'Mobile 1v1'"""
    cat, m = split_chave(ch)
    return f"{cat} {m}"


def jogadores_da_chave(ch: str) -> int:
    _, m = split_chave(ch)
    return JOGADORES_MODO[m]


# ──────────────────────────────────────────────
# Helpers de emoji customizado
# ──────────────────────────────────────────────

_CUSTOM_EMOJI_RE   = re.compile(r'^(<a?:\w+:\d+>)\s+(.*)', re.DOTALL)
_CUSTOM_EMOJI_BARE = re.compile(r'^<(a?):(\w+):(\d+)>$')


def parse_emoji_label(text: str):
    text = text.strip()
    m = _CUSTOM_EMOJI_RE.match(text)
    if m:
        return m.group(1), m.group(2).strip()
    parts = text.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) <= 8:
        return parts[0], parts[1]
    return "🎮", text


def to_discord_emoji(emoji_str: str):
    m = _CUSTOM_EMOJI_BARE.match(emoji_str.strip())
    if m:
        return discord.PartialEmoji(animated=bool(m.group(1)), name=m.group(2), id=int(m.group(3)))
    return emoji_str


def gerar_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:10]


def parse_cor(valor: str) -> int:
    """Aceita '#2ecc71', '2ecc71', '0x2ecc71' ou número."""
    if not valor:
        return COR_PADRAO
    s = str(valor).strip().lstrip("#").lstrip("0x").lstrip("0X")
    try:
        return int(s, 16)
    except Exception:
        try:
            return int(valor)
        except Exception:
            return COR_PADRAO


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

def _modo_padrao(ch: str) -> dict:
    _, m = split_chave(ch)
    return {
        "titulo":    display(ch),
        "banner":    "",
        "thumbnail": "",
        "canal_id":  None,
        "botao1":    {"emoji": "🎮", "label": "Opção 1"},
        "botao2":    {"emoji": "🔫", "label": "Opção 2"},
        "precos":    [{"id": gerar_id(), "valor": "R$ 1,00", "jogadores": []}],
    }


def carregar_config() -> dict:
    data: dict = {}

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)

    # Global config
    data.setdefault("global", {})
    g = data["global"]
    g.setdefault("cargo_adm_id",       None)   # cargo notificado nas partidas
    g.setdefault("cargo_max_id",       None)   # permissão máxima (usar painel)
    g.setdefault("cargo_mediador_id",  None)   # cargo dos mediadores
    g.setdefault("categoria_id",       None)
    g.setdefault("filas_ativas",       True)
    g.setdefault("embed_global", {
        "banner":    "",
        "thumbnail": "",
        "cor":       f"#{COR_PADRAO:06X}",
    })
    g.setdefault("mediadores",     {})   # {user_id_str: {"tipo": "...", "chave": "...", "nome": "..."}}
    g.setdefault("fila_mediador",  [])   # [user_id_str, ...]

    # Aparência por servidor: {guild_id_str: {"bio": "..."}}
    data.setdefault("aparencias", {})

    # Garantir todas as chaves de modo
    for ch in ALL_MODOS:
        if ch not in data:
            data[ch] = _modo_padrao(ch)
            continue

        cfg = data[ch]

        # Migrar formato antigo (filas → precos)
        if "filas" in cfg and "precos" not in cfg:
            filas = cfg.pop("filas")
            if filas:
                cfg["botao1"] = {"emoji": filas[0].get("emoji", "🎮"), "label": filas[0].get("label", "Opção 1")}
            if len(filas) >= 2:
                cfg["botao2"] = {"emoji": filas[1].get("emoji", "🔫"), "label": filas[1].get("label", "Opção 2")}
            cfg["precos"] = [
                {"id": f.get("id", gerar_id()), "valor": f.get("preco", "R$ 1,00"), "jogadores": f.get("jogadores", [])}
                for f in filas
            ]

        cfg.setdefault("titulo",    display(ch))
        cfg.setdefault("banner",    "")
        cfg.setdefault("thumbnail", "")
        cfg.setdefault("canal_id",  None)
        cfg.setdefault("botao1",    {"emoji": "🎮", "label": "Opção 1"})
        cfg.setdefault("botao2",    {"emoji": "🔫", "label": "Opção 2"})
        cfg.setdefault("precos",    [{"id": gerar_id(), "valor": "R$ 1,00", "jogadores": []}])

        for p in cfg["precos"]:
            p.setdefault("id",        gerar_id())
            p.setdefault("jogadores", [])

    return data


def salvar_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)


def encontrar_preco(config: dict, preco_id: str):
    for ch in ALL_MODOS:
        for p in config[ch].get("precos", []):
            if p["id"] == preco_id:
                return ch, p
    return None, None


def cor_global(config: dict) -> int:
    return parse_cor(config.get("global", {}).get("embed_global", {}).get("cor", ""))


def banner_efetivo(config: dict, ch: str) -> str:
    cfg = config[ch]
    return cfg.get("banner") or config.get("global", {}).get("embed_global", {}).get("banner", "")


def thumb_efetiva(config: dict, ch: str) -> str:
    cfg = config[ch]
    return cfg.get("thumbnail") or config.get("global", {}).get("embed_global", {}).get("thumbnail", "")


def usuario_pode_admin(member: discord.Member, config: dict) -> bool:
    """True se for admin do servidor OU tem cargo_max."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_channels:
        return True
    cargo_max = config.get("global", {}).get("cargo_max_id")
    if cargo_max and any(r.id == cargo_max for r in member.roles):
        return True
    return False


def usuario_e_mediador(member: discord.Member, config: dict) -> bool:
    cargo_med = config.get("global", {}).get("cargo_mediador_id")
    if cargo_med and any(r.id == cargo_med for r in member.roles):
        return True
    return usuario_pode_admin(member, config)


# ──────────────────────────────────────────────
# Embeds
# ──────────────────────────────────────────────

def build_embed_fila(ch: str, preco: dict, config: dict) -> discord.Embed:
    cfg       = config[ch]
    cat, m    = split_chave(ch)
    jogadores = preco.get("jogadores", [])
    total     = jogadores_da_chave(ch)
    g         = config.get("global", {})

    embed = discord.Embed(title=cfg["titulo"], color=cor_global(config))
    embed.add_field(name="Categoria", value=f"{EMOJI_CATEGORIA[cat]} {cat}", inline=True)
    embed.add_field(name="Modo",      value=f"{EMOJI_MODO[m]} {m}",          inline=True)
    embed.add_field(name="Valor",     value=f"**{preco['valor']}**",          inline=True)

    if not g.get("filas_ativas", True):
        embed.add_field(name="\u200b", value="🛑 **FILAS DESATIVADAS**", inline=False)
    elif jogadores:
        lista = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(jogadores))
        embed.add_field(name=f"Jogadores ({len(jogadores)}/{total})", value=lista, inline=False)
    else:
        embed.add_field(name="Jogadores", value="Nenhum jogador na fila.", inline=False)

    if g.get("filas_ativas", True) and len(jogadores) >= total:
        embed.add_field(name="\u200b", value="🔥 **Fila completa! Partida iniciando...**", inline=False)

    thumb = thumb_efetiva(config, ch)
    banner = banner_efetivo(config, ch)
    if thumb:
        embed.set_thumbnail(url=thumb)
    if banner:
        embed.set_image(url=banner)
    return embed


def build_embed_config_modo(ch: str, config: dict) -> discord.Embed:
    cfg    = config[ch]
    cat, m = split_chave(ch)
    cid    = cfg.get("canal_id")
    canal  = f"<#{cid}>" if cid else "`Não definido`"
    b1, b2 = cfg["botao1"], cfg["botao2"]
    precos = cfg.get("precos", [])

    embed = discord.Embed(title=f"{EMOJI_CATEGORIA[cat]}  Configuração — {display(ch)}", color=cor_global(config))
    embed.add_field(name="📌 Título",    value=f"`{cfg['titulo']}`",                          inline=True)
    embed.add_field(name="📢 Canal",     value=canal,                                          inline=True)
    embed.add_field(name="\u200b",       value="\u200b",                                       inline=True)
    embed.add_field(name=f"{b1['emoji']} Botão 1", value=f"`{b1['label']}`",                  inline=True)
    embed.add_field(name=f"{b2['emoji']} Botão 2", value=f"`{b2['label']}`",                  inline=True)
    embed.add_field(name="\u200b",       value="\u200b",                                       inline=True)

    txt = "\n".join(f"• `{p['valor']}` — {len(p.get('jogadores',[]))} jogadores" for p in precos) or "*sem preços*"
    embed.add_field(name=f"💰 Preços ({len(precos)} embed{'s' if len(precos)!=1 else ''})", value=txt, inline=False)
    embed.add_field(name="🖼️ Banner",   value=f"`{'✅' if cfg.get('banner') else '⬜ usa global'}`",    inline=True)
    embed.add_field(name="🔷 Thumbnail", value=f"`{'✅' if cfg.get('thumbnail') else '⬜ usa global'}`", inline=True)
    embed.set_footer(text="Cada preço gera um embed separado. Banner/thumb vazios usam o embed global.")
    th = thumb_efetiva(config, ch)
    if th:
        embed.set_thumbnail(url=th)
    return embed


def build_embed_categoria(cat: str, config: dict) -> discord.Embed:
    modos  = MODOS_POR_CATEGORIA[cat]
    embed  = discord.Embed(title=f"{EMOJI_CATEGORIA[cat]}  {cat} — Selecione o Modo", color=cor_global(config))
    for m in modos:
        ch     = chave(cat, m)
        cfg    = config[ch]
        cid    = cfg.get("canal_id")
        canal  = f"<#{cid}>" if cid else "`sem canal`"
        precos = cfg.get("precos", [])
        txt    = "\n".join(f"• `{p['valor']}`" for p in precos) or "*sem preços*"
        embed.add_field(name=f"{EMOJI_MODO[m]} {m}", value=f"Canal: {canal}\n{txt}", inline=True)
    embed.set_footer(text="Clique no modo para configurar.")
    return embed


def build_embed_gerenciar_precos(ch: str, config: dict, selected_id: str = None) -> discord.Embed:
    precos = config[ch].get("precos", [])
    embed  = discord.Embed(
        title=f"💰  Preços — {display(ch)}",
        description=f"**{len(precos)}** preço(s). Cada preço cria um embed separado com os mesmos botões.",
        color=cor_global(config),
    )
    for i, p in enumerate(precos):
        sel = "  ◀ selecionado" if p["id"] == selected_id else ""
        embed.add_field(name=f"{i+1}. {p['valor']}{sel}", value=f"Jogadores: `{len(p.get('jogadores',[]))}`", inline=False)
    if not precos:
        embed.add_field(name="Sem preços", value="Clique em **➕ Adicionar**.", inline=False)
    return embed


def build_embed_config_geral(config: dict) -> discord.Embed:
    g     = config.get("global", {})
    cargo_adm = f"<@&{g['cargo_adm_id']}>" if g.get("cargo_adm_id") else "`Não definido`"
    cargo_max = f"<@&{g['cargo_max_id']}>" if g.get("cargo_max_id") else "`Não definido`"
    cargo_med = f"<@&{g['cargo_mediador_id']}>" if g.get("cargo_mediador_id") else "`Não definido`"
    cat   = f"<#{g['categoria_id']}>"   if g.get("categoria_id") else "`Não definida`"
    embed = discord.Embed(title="⚙️  Configuração Global", color=cor_global(config))
    embed.add_field(name="👑 Cargo Permissão Máxima", value=cargo_max, inline=False)
    embed.add_field(name="🛡️ Cargo ADM (notificado nas partidas)", value=cargo_adm, inline=False)
    embed.add_field(name="🤝 Cargo Mediador",         value=cargo_med, inline=False)
    embed.add_field(name="📁 Categoria de canais",    value=cat,       inline=False)
    embed.add_field(
        name="ℹ️ Como funciona",
        value=(
            "Quando a fila encher:\n"
            "• Canal privado criado para os jogadores\n"
            "• Embed de confirmação enviado\n"
            "• **Cargo ADM** é notificado\n"
            "• Mediador da fila (ou cargo Mediador) é puxado\n"
            "• Quando todos confirmarem, o ADM é adicionado ao canal"
        ),
        inline=False,
    )
    return embed


def build_embed_config_embed_global(config: dict) -> discord.Embed:
    g  = config.get("global", {}).get("embed_global", {})
    embed = discord.Embed(
        title="🎨  Embed Global",
        description="Estes valores são aplicados em **todas as filas** que não tenham banner/thumbnail próprios. A **cor** é usada em todos os embeds do bot.",
        color=cor_global(config),
    )
    embed.add_field(name="🖼️ Banner padrão",    value=f"`{g.get('banner','') or '— vazio —'}`", inline=False)
    embed.add_field(name="🔷 Thumbnail padrão", value=f"`{g.get('thumbnail','') or '— vazio —'}`", inline=False)
    embed.add_field(name="🎨 Cor",              value=f"`{g.get('cor','') or '#2ECC71'}`",       inline=False)
    if g.get("thumbnail"):
        embed.set_thumbnail(url=g["thumbnail"])
    if g.get("banner"):
        embed.set_image(url=g["banner"])
    return embed


def build_embed_painel_geral(config: dict) -> discord.Embed:
    g     = config.get("global", {})
    cargo_max = f"<@&{g['cargo_max_id']}>" if g.get("cargo_max_id") else "`—`"
    cargo_adm = f"<@&{g['cargo_adm_id']}>" if g.get("cargo_adm_id") else "`—`"
    cargo_med = f"<@&{g['cargo_mediador_id']}>" if g.get("cargo_mediador_id") else "`—`"
    status_filas = "🟢 **ATIVAS**" if g.get("filas_ativas", True) else "🛑 **DESATIVADAS**"
    embed = discord.Embed(
        title="⚙️  Painel — Bot de Filas",
        description=(
            f"Selecione uma categoria para configurar os modos.\n\n"
            f"**👑 Permissão máxima:** {cargo_max}\n"
            f"**🛡️ Cargo ADM:** {cargo_adm}\n"
            f"**🤝 Cargo Mediador:** {cargo_med}\n"
            f"**Status:** {status_filas}"
        ),
        color=cor_global(config),
    )
    for cat in CATEGORIAS:
        modos  = MODOS_POR_CATEGORIA[cat]
        linhas = []
        for m in modos:
            ch    = chave(cat, m)
            cfg   = config[ch]
            cid   = cfg.get("canal_id")
            canal = f"<#{cid}>" if cid else "`sem canal`"
            n_precos = len(cfg.get("precos", []))
            linhas.append(f"{EMOJI_MODO[m]} **{m}** — {canal} — {n_precos} preço(s)")
        embed.add_field(name=f"{EMOJI_CATEGORIA[cat]} {cat}", value="\n".join(linhas), inline=False)
    embed.set_footer(text="Apenas administradores e cargo de permissão máxima podem usar este painel.")
    return embed


# ──────────────────────────────────────────────
# Embeds — Mediador
# ──────────────────────────────────────────────

def build_embed_painel_mediador(config: dict) -> discord.Embed:
    g          = config.get("global", {})
    fila       = g.get("fila_mediador", [])
    mediadores = g.get("mediadores", {})

    embed = discord.Embed(
        title="🤝  Painel de Mediadores",
        description=(
            "Mediadores cadastram seu **PIX** e entram na fila.\n"
            "Quando uma partida for confirmada, o **próximo mediador da fila** é puxado e seu PIX é exibido aos jogadores."
        ),
        color=cor_global(config),
    )

    if fila:
        linhas = []
        for i, uid in enumerate(fila):
            med = mediadores.get(str(uid), {})
            nome = med.get("nome") or "?"
            linhas.append(f"`{i+1}.` <@{uid}> — {nome}")
        embed.add_field(name=f"📋 Fila de mediadores ({len(fila)})", value="\n".join(linhas), inline=False)
    else:
        embed.add_field(name="📋 Fila de mediadores", value="*Vazia — nenhum mediador disponível.*", inline=False)

    if mediadores:
        embed.add_field(
            name=f"💳 Mediadores cadastrados ({len(mediadores)})",
            value="\n".join(f"• <@{uid}> — `{m.get('tipo','?')}` `{m.get('chave','?')}`" for uid, m in list(mediadores.items())[:15]) or "—",
            inline=False,
        )
    else:
        embed.add_field(name="💳 Mediadores cadastrados", value="*Nenhum mediador cadastrou PIX ainda.*", inline=False)

    embed.set_footer(text="Use os botões abaixo para cadastrar PIX, entrar ou sair da fila de mediadores.")
    return embed


def build_embed_pix_mediador(mediador_uid: str, mediador_data: dict, ch: str, preco: dict) -> discord.Embed:
    embed = discord.Embed(
        title="💳  Mediador da Partida",
        description=f"Por favor, façam o pagamento ao mediador abaixo:",
        color=0xF1C40F,
    )
    embed.add_field(name="🤝 Mediador",     value=f"<@{mediador_uid}>",                inline=False)
    embed.add_field(name="👤 Nome",         value=f"`{mediador_data.get('nome','—')}`", inline=True)
    embed.add_field(name="🏦 Tipo de PIX",  value=f"`{mediador_data.get('tipo','—')}`", inline=True)
    embed.add_field(name="🔑 Chave PIX",    value=f"```{mediador_data.get('chave','—')}```", inline=False)
    embed.add_field(name="💰 Valor",        value=f"**{preco['valor']}** — {display(ch)}", inline=False)
    embed.set_footer(text="Após o pagamento, o mediador irá liberar a partida.")
    return embed


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

async def _atualizar_painel(painel_msg, config):
    if painel_msg:
        try:
            await painel_msg.edit(embed=build_embed_painel_geral(config))
        except Exception:
            pass


# ──────────────────────────────────────────────
# Modais
# ──────────────────────────────────────────────

class EditarEmbedModal(Modal):
    def __init__(self, ch: str, config: dict, painel_msg=None):
        super().__init__(title=f"Editar Embed — {display(ch)}"[:45])
        self.ch, self.painel_msg = ch, painel_msg
        cfg = config[ch]
        self.titulo    = TextInput(label="Título",              default=cfg.get("titulo",""),    max_length=100, required=True)
        self.banner    = TextInput(label="URL do Banner (vazio = global)", default=cfg.get("banner",""),    required=False, placeholder="https://...")
        self.thumbnail = TextInput(label="URL da Thumbnail (vazio = global)", default=cfg.get("thumbnail",""), required=False, placeholder="https://...")
        self.add_item(self.titulo); self.add_item(self.banner); self.add_item(self.thumbnail)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        config[self.ch]["titulo"]    = self.titulo.value
        config[self.ch]["banner"]    = self.banner.value.strip()
        config[self.ch]["thumbnail"] = self.thumbnail.value.strip()
        salvar_config(config)
        cat, _ = split_chave(self.ch)
        await interaction.response.edit_message(embed=build_embed_config_modo(self.ch, config), view=ModoConfigView(self.ch, cat, self.painel_msg))
        await _atualizar_painel(self.painel_msg, config)


class EditarEmbedGlobalModal(Modal):
    def __init__(self, config: dict, painel_msg=None):
        super().__init__(title="Editar Embed Global")
        self.painel_msg = painel_msg
        g = config.get("global", {}).get("embed_global", {})
        self.banner    = TextInput(label="Banner padrão (URL)",    default=g.get("banner",""),    required=False, placeholder="https://...")
        self.thumbnail = TextInput(label="Thumbnail padrão (URL)", default=g.get("thumbnail",""), required=False, placeholder="https://...")
        self.cor       = TextInput(label="Cor (hex, ex: #2ecc71)", default=g.get("cor","#2ECC71"), required=False, max_length=10, placeholder="#2ECC71")
        self.add_item(self.banner); self.add_item(self.thumbnail); self.add_item(self.cor)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        eg = config["global"].setdefault("embed_global", {})
        eg["banner"]    = self.banner.value.strip()
        eg["thumbnail"] = self.thumbnail.value.strip()
        eg["cor"]       = self.cor.value.strip() or "#2ECC71"
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_embed_global(config), view=EmbedGlobalView(self.painel_msg))
        await _atualizar_painel(self.painel_msg, config)


class EditarBotoesModal(Modal):
    def __init__(self, ch: str, config: dict, painel_msg=None):
        super().__init__(title=f"Editar Botões — {display(ch)}"[:45])
        self.ch, self.painel_msg = ch, painel_msg
        b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
        self.b1 = TextInput(label="Botão 1 — emoji + nome", default=f"{b1['emoji']} {b1['label']}", max_length=100, required=True, placeholder="🎮 Jogar normal  ou  <:emoji:id> Nome")
        self.b2 = TextInput(label="Botão 2 — emoji + nome", default=f"{b2['emoji']} {b2['label']}", max_length=100, required=True, placeholder="🔫 Ranked  ou  <:emoji:id> Nome")
        self.add_item(self.b1); self.add_item(self.b2)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        e1, l1 = parse_emoji_label(self.b1.value)
        e2, l2 = parse_emoji_label(self.b2.value)
        config[self.ch]["botao1"] = {"emoji": e1, "label": l1}
        config[self.ch]["botao2"] = {"emoji": e2, "label": l2}
        salvar_config(config)
        cat, _ = split_chave(self.ch)
        await interaction.response.edit_message(embed=build_embed_config_modo(self.ch, config), view=ModoConfigView(self.ch, cat, self.painel_msg))
        await _atualizar_painel(self.painel_msg, config)


class AdicionarPrecoModal(Modal):
    def __init__(self, ch: str, painel_msg=None):
        super().__init__(title=f"Adicionar Preço — {display(ch)}"[:45])
        self.ch, self.painel_msg = ch, painel_msg
        self.valor = TextInput(label="Valor (ex: R$ 1,00)", placeholder="R$ 1,00", max_length=30, required=True)
        self.add_item(self.valor)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        novo = {"id": gerar_id(), "valor": self.valor.value.strip(), "jogadores": []}
        config[self.ch]["precos"].append(novo)
        salvar_config(config)
        b1 = config[self.ch]["botao1"]; b2 = config[self.ch]["botao2"]
        bot.add_view(FilaView(self.ch, novo["id"], b1, b2))
        view = GerenciarPrecosView(self.ch, self.painel_msg)
        view.selected_id = novo["id"]
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.ch, config, novo["id"]), view=view)
        await _atualizar_painel(self.painel_msg, config)


class EditarPrecoModal(Modal):
    def __init__(self, ch: str, preco_id: str, config: dict, gv):
        preco = next((p for p in config[ch]["precos"] if p["id"] == preco_id), None)
        super().__init__(title=f"Editar Preço — {preco['valor'] if preco else ch}"[:45])
        self.ch, self.preco_id, self.gv = ch, preco_id, gv
        self.valor = TextInput(label="Valor", default=preco["valor"] if preco else "", max_length=30, required=True)
        self.add_item(self.valor)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        for p in config[self.ch]["precos"]:
            if p["id"] == self.preco_id:
                p["valor"] = self.valor.value.strip()
                break
        salvar_config(config)
        view = GerenciarPrecosView(self.ch, self.gv.painel_msg)
        view.selected_id = self.preco_id
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.ch, config, self.preco_id), view=view)
        await _atualizar_painel(self.gv.painel_msg, config)


class CadastrarPixModal(Modal):
    def __init__(self, painel_med_msg=None):
        super().__init__(title="Cadastrar PIX — Mediador")
        self.painel_med_msg = painel_med_msg
        self.nome  = TextInput(label="Seu nome (titular)",   max_length=80, required=True, placeholder="Nome completo")
        self.tipo  = TextInput(label="Tipo de PIX",          max_length=30, required=True, placeholder="CPF, E-mail, Telefone, Aleatória")
        self.chave = TextInput(label="Chave PIX",            max_length=120, required=True, placeholder="000.000.000-00")
        self.add_item(self.nome); self.add_item(self.tipo); self.add_item(self.chave)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"].setdefault("mediadores", {})
        config["global"]["mediadores"][str(interaction.user.id)] = {
            "nome":  self.nome.value.strip(),
            "tipo":  self.tipo.value.strip(),
            "chave": self.chave.value.strip(),
        }
        salvar_config(config)
        await _atualizar_painel_mediador(self.painel_med_msg, config)
        await interaction.response.send_message(f"✅ PIX cadastrado!\n• **Nome:** `{self.nome.value}`\n• **Tipo:** `{self.tipo.value}`\n• **Chave:** `{self.chave.value}`", ephemeral=True)


# ──────────────────────────────────────────────
# View: Gerenciar Preços
# ──────────────────────────────────────────────

class PrecoSelectMenu(Select):
    def __init__(self, precos: list, parent_view):
        opts = [discord.SelectOption(label=p["valor"], value=p["id"], description=f"{len(p.get('jogadores',[]))} jogadores") for p in precos[:25]]
        super().__init__(placeholder="Selecione um preço...", options=opts, min_values=1, max_values=1, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_id = self.values[0]
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.parent_view.ch, config, self.parent_view.selected_id), view=self.parent_view)


class GerenciarPrecosView(View):
    def __init__(self, ch: str, painel_msg=None):
        super().__init__(timeout=300)
        self.ch, self.painel_msg = ch, painel_msg
        self.selected_id = None
        config = carregar_config()
        precos = config[ch].get("precos", [])
        if precos:
            self.add_item(PrecoSelectMenu(precos, self))
        self.add_item(_BtnEditarPreco(self))
        self.add_item(_BtnRemoverPreco(self))
        self.add_item(_BtnAdicionarPreco(ch, painel_msg))
        self.add_item(_BtnVoltarModo(ch, painel_msg))


class _BtnEditarPreco(Button):
    def __init__(self, pv):
        super().__init__(label="✏️  Editar", style=discord.ButtonStyle.primary, row=1)
        self.pv = pv

    async def callback(self, interaction: discord.Interaction):
        if not self.pv.selected_id:
            await interaction.response.send_message("⚠️ Selecione um preço primeiro!", ephemeral=True); return
        config = carregar_config()
        await interaction.response.send_modal(EditarPrecoModal(self.pv.ch, self.pv.selected_id, config, self.pv))


class _BtnRemoverPreco(Button):
    def __init__(self, pv):
        super().__init__(label="🗑️  Remover", style=discord.ButtonStyle.danger, row=1)
        self.pv = pv

    async def callback(self, interaction: discord.Interaction):
        if not self.pv.selected_id:
            await interaction.response.send_message("⚠️ Selecione um preço primeiro!", ephemeral=True); return
        config = carregar_config()
        ch = self.pv.ch
        preco = next((p for p in config[ch]["precos"] if p["id"] == self.pv.selected_id), None)
        if not preco:
            await interaction.response.send_message("❌ Preço não encontrado.", ephemeral=True); return
        config[ch]["precos"] = [p for p in config[ch]["precos"] if p["id"] != self.pv.selected_id]
        salvar_config(config)
        new_view = GerenciarPrecosView(ch, self.pv.painel_msg)
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(ch, config), view=new_view)
        await interaction.followup.send(f"🗑️ Preço **{preco['valor']}** removido!", ephemeral=True)
        await _atualizar_painel(self.pv.painel_msg, config)


class _BtnAdicionarPreco(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(label="➕  Adicionar", style=discord.ButtonStyle.success, row=1)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AdicionarPrecoModal(self.ch, self.painel_msg))


class _BtnVoltarModo(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=1)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        cat, _ = split_chave(self.ch)
        config  = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_modo(self.ch, config), view=ModoConfigView(self.ch, cat, self.painel_msg))


# ──────────────────────────────────────────────
# View: Configuração do modo
# ──────────────────────────────────────────────

class ModoConfigView(View):
    def __init__(self, ch: str, cat: str, painel_msg=None):
        super().__init__(timeout=300)
        self.ch, self.cat, self.painel_msg = ch, cat, painel_msg
        self.add_item(_CanalSelect(ch, painel_msg))
        self.add_item(_BtnEditarEmbed(ch, painel_msg))
        self.add_item(_BtnEditarBotoes(ch, painel_msg))
        self.add_item(_BtnGerenciarPrecos(ch, painel_msg))
        self.add_item(_BtnVoltarCategoria(cat, painel_msg))


class _CanalSelect(ChannelSelect):
    def __init__(self, ch, painel_msg):
        super().__init__(placeholder=f"📢 Canal dos embeds — {display(ch)}", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=0)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        canal = self.values[0]
        config = carregar_config()
        config[self.ch]["canal_id"] = canal.id
        salvar_config(config)
        cat, _ = split_chave(self.ch)
        await interaction.response.edit_message(embed=build_embed_config_modo(self.ch, config), view=ModoConfigView(self.ch, cat, self.painel_msg))
        await interaction.followup.send(f"✅ Canal definido: {canal.mention}", ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _BtnEditarEmbed(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(label="✏️  Título/Banner", style=discord.ButtonStyle.primary, row=1)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarEmbedModal(self.ch, config, self.painel_msg))


class _BtnEditarBotoes(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(label="🎮  Editar Botões", style=discord.ButtonStyle.secondary, row=1)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarBotoesModal(self.ch, config, self.painel_msg))


class _BtnGerenciarPrecos(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(label="💰  Preços", style=discord.ButtonStyle.secondary, row=1)
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.ch, config), view=GerenciarPrecosView(self.ch, self.painel_msg))


class _BtnVoltarCategoria(Button):
    def __init__(self, cat, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=1)
        self.cat, self.painel_msg = cat, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_categoria(self.cat, config), view=CategoriaView(self.cat, self.painel_msg))


# ──────────────────────────────────────────────
# View: Categoria
# ──────────────────────────────────────────────

class CategoriaView(View):
    def __init__(self, cat: str, painel_msg=None):
        super().__init__(timeout=300)
        for m in MODOS_POR_CATEGORIA[cat]:
            self.add_item(_BtnModoConfig(cat, m, painel_msg))
        self.add_item(_BtnVoltarPainelDaCategoria(painel_msg))


class _BtnModoConfig(Button):
    def __init__(self, cat, modo, painel_msg):
        super().__init__(label=f"{EMOJI_MODO[modo]}  {modo}", style=discord.ButtonStyle.secondary)
        self.cat, self.modo, self.painel_msg = cat, modo, painel_msg

    async def callback(self, interaction: discord.Interaction):
        ch     = chave(self.cat, self.modo)
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_modo(ch, config), view=ModoConfigView(ch, self.cat, self.painel_msg))


class _BtnVoltarPainelDaCategoria(Button):
    def __init__(self, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_painel_geral(config), view=PainelPrincipalView(self.painel_msg))


# ──────────────────────────────────────────────
# View: Config Global
# ──────────────────────────────────────────────

class ConfigGeralView(View):
    def __init__(self, painel_msg=None):
        super().__init__(timeout=300)
        self.painel_msg = painel_msg
        self.add_item(_RoleSelectMax(painel_msg))
        self.add_item(_RoleSelectAdm(painel_msg))
        self.add_item(_RoleSelectMediador(painel_msg))
        self.add_item(_CanalSelectCategoria(painel_msg))
        self.add_item(_BtnVoltarPainelGeral(painel_msg))


class _RoleSelectMax(RoleSelect):
    def __init__(self, painel_msg):
        super().__init__(placeholder="👑 Selecione o Cargo de Permissão Máxima...", min_values=0, max_values=1, row=0)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["cargo_max_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))
        txt = f"✅ Permissão máxima: {self.values[0].mention}" if self.values else "✅ Permissão máxima removida."
        await interaction.followup.send(txt, ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _RoleSelectAdm(RoleSelect):
    def __init__(self, painel_msg):
        super().__init__(placeholder="🛡️ Selecione o Cargo ADM (notificado)...", min_values=0, max_values=1, row=1)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["cargo_adm_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))
        txt = f"✅ Cargo ADM: {self.values[0].mention}" if self.values else "✅ Cargo ADM removido."
        await interaction.followup.send(txt, ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _RoleSelectMediador(RoleSelect):
    def __init__(self, painel_msg):
        super().__init__(placeholder="🤝 Selecione o Cargo Mediador...", min_values=0, max_values=1, row=2)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["cargo_mediador_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))
        txt = f"✅ Cargo Mediador: {self.values[0].mention}" if self.values else "✅ Cargo Mediador removido."
        await interaction.followup.send(txt, ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _CanalSelectCategoria(ChannelSelect):
    def __init__(self, painel_msg):
        super().__init__(placeholder="📁 Categoria dos canais de partida (opcional)...", channel_types=[discord.ChannelType.category], min_values=0, max_values=1, row=3)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["categoria_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))
        txt = f"✅ Categoria: **{self.values[0].name}**" if self.values else "✅ Categoria removida."
        await interaction.followup.send(txt, ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _BtnVoltarPainelGeral(Button):
    def __init__(self, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_painel_geral(config), view=PainelPrincipalView(self.painel_msg))


# ──────────────────────────────────────────────
# View: Embed Global
# ──────────────────────────────────────────────

class EmbedGlobalView(View):
    def __init__(self, painel_msg=None):
        super().__init__(timeout=300)
        self.painel_msg = painel_msg
        self.add_item(_BtnEditarEmbedGlobal(painel_msg))
        self.add_item(_BtnVoltarPainelDeEmbedGlobal(painel_msg))


class _BtnEditarEmbedGlobal(Button):
    def __init__(self, painel_msg):
        super().__init__(label="✏️  Editar Embed Global", style=discord.ButtonStyle.primary, row=0)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarEmbedGlobalModal(config, self.painel_msg))


class _BtnVoltarPainelDeEmbedGlobal(Button):
    def __init__(self, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=0)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_painel_geral(config), view=PainelPrincipalView(self.painel_msg))


# ──────────────────────────────────────────────
# View: Painel Principal
# ──────────────────────────────────────────────

class PainelPrincipalView(View):
    def __init__(self, painel_msg=None):
        super().__init__(timeout=600)
        self.painel_msg = painel_msg
        # Row 0: categorias
        for cat in CATEGORIAS:
            self.add_item(_BtnCategoria(cat, painel_msg))
        # Row 1: ações globais
        self.add_item(_BtnConfigGeral(painel_msg))
        self.add_item(_BtnEmbedGlobal(painel_msg))
        self.add_item(_BtnFilasToggle(painel_msg))
        self.add_item(_BtnPublicar(painel_msg))

    def set_message(self, msg):
        self.painel_msg = msg
        for item in self.children:
            if hasattr(item, "painel_msg"):
                item.painel_msg = msg


class _BtnCategoria(Button):
    def __init__(self, cat, painel_msg):
        super().__init__(label=f"{EMOJI_CATEGORIA[cat]}  {cat}", style=discord.ButtonStyle.secondary, row=0)
        self.cat, self.painel_msg = cat, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_categoria(self.cat, config), view=CategoriaView(self.cat, self.painel_msg))


class _BtnConfigGeral(Button):
    def __init__(self, painel_msg):
        super().__init__(label="⚙️  Config Geral", style=discord.ButtonStyle.primary, row=1)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))


class _BtnEmbedGlobal(Button):
    def __init__(self, painel_msg):
        super().__init__(label="🎨  Embed Global", style=discord.ButtonStyle.primary, row=1)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_embed_global(config), view=EmbedGlobalView(self.painel_msg))


class _BtnFilasToggle(Button):
    def __init__(self, painel_msg):
        config = carregar_config()
        ativas = config.get("global", {}).get("filas_ativas", True)
        super().__init__(
            label="🛑  Filas OFF" if ativas else "🟢  Filas ON",
            style=discord.ButtonStyle.danger if ativas else discord.ButtonStyle.success,
            row=1,
        )
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        atual = config["global"].get("filas_ativas", True)
        config["global"]["filas_ativas"] = not atual
        salvar_config(config)

        # Atualiza painel
        view = PainelPrincipalView(self.painel_msg)
        view.set_message(self.painel_msg)
        await interaction.response.edit_message(embed=build_embed_painel_geral(config), view=view)

        # Atualiza mensagens de status nos canais
        await _atualizar_status_filas(interaction.guild, config)

        await interaction.followup.send(
            f"🛑 **Filas DESATIVADAS**" if atual else "🟢 **Filas ATIVADAS**",
            ephemeral=True,
        )


class _BtnPublicar(Button):
    def __init__(self, painel_msg):
        super().__init__(label="🚀  Publicar Filas", style=discord.ButtonStyle.success, row=1)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão!", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        sem_canal  = [ch for ch in ALL_MODOS if not config[ch].get("canal_id")]
        sem_precos = [ch for ch in ALL_MODOS if not config[ch].get("precos")]
        erros = []
        if sem_canal:  erros.append(f"Sem canal ({len(sem_canal)} modos)")
        if sem_precos: erros.append(f"Sem preços ({len(sem_precos)} modos)")
        if erros:
            await interaction.followup.send("⚠️ " + "\n".join(erros), ephemeral=True); return
        await _publicar_filas(interaction, config)


# ──────────────────────────────────────────────
# View: Fila de jogadores
# ──────────────────────────────────────────────

class FilaView(View):
    def __init__(self, ch: str, preco_id: str, botao1: dict, botao2: dict):
        super().__init__(timeout=None)
        self.add_item(_EntrarBtn(ch, preco_id, 1, botao1["emoji"], botao1["label"]))
        self.add_item(_EntrarBtn(ch, preco_id, 2, botao2["emoji"], botao2["label"]))
        self.add_item(_SairBtn(preco_id))
        self.add_item(_LimparBtn(preco_id))


class _EntrarBtn(Button):
    def __init__(self, ch, preco_id, num, emoji, label):
        super().__init__(label=f"  {label}", emoji=to_discord_emoji(emoji), style=discord.ButtonStyle.secondary, custom_id=f"entrar{num}_{preco_id}")
        self.ch, self.preco_id = ch, preco_id

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()

        if not config.get("global", {}).get("filas_ativas", True):
            await interaction.response.send_message("🛑 As filas estão **desativadas** no momento.", ephemeral=True); return

        ch, preco = encontrar_preco(config, self.preco_id)
        if preco is None:
            await interaction.response.send_message("❌ Esta fila não existe mais.", ephemeral=True); return

        uid   = str(interaction.user.id)
        total = jogadores_da_chave(ch)

        if uid in preco["jogadores"]:
            await interaction.response.send_message("⚠️ Você já está nesta fila!", ephemeral=True); return
        if len(preco["jogadores"]) >= total:
            await interaction.response.send_message("❌ A fila está cheia!", ephemeral=True); return

        preco["jogadores"].append(uid)
        salvar_config(config)

        b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
        view   = FilaView(ch, self.preco_id, b1, b2)
        await interaction.response.edit_message(embed=build_embed_fila(ch, preco, config), view=view)

        if len(preco["jogadores"]) >= total:
            jogadores_partida = list(preco["jogadores"])
            preco["jogadores"] = []
            salvar_config(config)
            view2 = FilaView(ch, self.preco_id, b1, b2)
            await interaction.edit_original_response(embed=build_embed_fila(ch, preco, config), view=view2)
            await _fila_completa(interaction, ch, preco, jogadores_partida, config)


class _SairBtn(Button):
    def __init__(self, preco_id):
        super().__init__(label="Sair da fila", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"sair_{preco_id}")
        self.preco_id = preco_id

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        ch, preco = encontrar_preco(config, self.preco_id)
        if preco is None:
            await interaction.response.send_message("❌ Esta fila não existe mais.", ephemeral=True); return
        uid = str(interaction.user.id)
        if uid not in preco["jogadores"]:
            await interaction.response.send_message("⚠️ Você não está nesta fila!", ephemeral=True); return
        preco["jogadores"].remove(uid)
        salvar_config(config)
        b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
        await interaction.response.edit_message(embed=build_embed_fila(ch, preco, config), view=FilaView(ch, self.preco_id, b1, b2))


class _LimparBtn(Button):
    def __init__(self, preco_id):
        super().__init__(label="Limpar", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id=f"limpar_{preco_id}")
        self.preco_id = preco_id

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão!", ephemeral=True); return
        ch, preco = encontrar_preco(config, self.preco_id)
        if preco is None:
            await interaction.response.send_message("❌ Esta fila não existe mais.", ephemeral=True); return
        preco["jogadores"] = []
        salvar_config(config)
        b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
        await interaction.response.edit_message(embed=build_embed_fila(ch, preco, config), view=FilaView(ch, self.preco_id, b1, b2))
        await interaction.followup.send(f"🗑️ Fila limpa por {interaction.user.mention}.")


# ──────────────────────────────────────────────
# View: Painel Mediador
# ──────────────────────────────────────────────

# Dicionário {channel_id: message_id} para rastrear painéis de mediador publicados (em RAM)
_painel_mediador_msgs: dict[int, int] = {}


async def _atualizar_painel_mediador(painel_med_msg, config):
    if painel_med_msg:
        try:
            await painel_med_msg.edit(embed=build_embed_painel_mediador(config))
        except Exception:
            pass

    # Atualiza todos os painéis de mediador conhecidos
    for canal_id, msg_id in list(_painel_mediador_msgs.items()):
        try:
            canal = bot.get_channel(canal_id)
            if not canal:
                continue
            msg = await canal.fetch_message(msg_id)
            await msg.edit(embed=build_embed_painel_mediador(config))
        except Exception:
            pass


class PainelMediadorView(View):
    def __init__(self, painel_med_msg=None):
        super().__init__(timeout=None)
        self.add_item(_BtnCadastrarPix(painel_med_msg))
        self.add_item(_BtnEntrarFilaMediador(painel_med_msg))
        self.add_item(_BtnSairFilaMediador(painel_med_msg))
        self.add_item(_BtnLimparFilaMediador(painel_med_msg))


class _BtnCadastrarPix(Button):
    def __init__(self, painel_med_msg):
        super().__init__(label="Cadastrar PIX", emoji="💳", style=discord.ButtonStyle.primary, custom_id="med_cadastrar_pix")
        self.painel_med_msg = painel_med_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_e_mediador(interaction.user, config):
            await interaction.response.send_message("❌ Apenas mediadores podem usar este painel.", ephemeral=True); return
        await interaction.response.send_modal(CadastrarPixModal(self.painel_med_msg))


class _BtnEntrarFilaMediador(Button):
    def __init__(self, painel_med_msg):
        super().__init__(label="Entrar na Fila", emoji="✅", style=discord.ButtonStyle.success, custom_id="med_entrar_fila")
        self.painel_med_msg = painel_med_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_e_mediador(interaction.user, config):
            await interaction.response.send_message("❌ Apenas mediadores podem usar este painel.", ephemeral=True); return

        uid = str(interaction.user.id)
        if uid not in config["global"].get("mediadores", {}):
            await interaction.response.send_message("⚠️ Você precisa **cadastrar seu PIX** antes de entrar na fila!", ephemeral=True); return

        fila = config["global"].setdefault("fila_mediador", [])
        if uid in fila:
            await interaction.response.send_message("⚠️ Você já está na fila de mediadores!", ephemeral=True); return

        fila.append(uid)
        salvar_config(config)
        await _atualizar_painel_mediador(self.painel_med_msg, config)
        await interaction.response.send_message(f"✅ Você entrou na fila de mediadores! Posição: **#{len(fila)}**", ephemeral=True)


class _BtnSairFilaMediador(Button):
    def __init__(self, painel_med_msg):
        super().__init__(label="Sair da Fila", emoji="❌", style=discord.ButtonStyle.danger, custom_id="med_sair_fila")
        self.painel_med_msg = painel_med_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        uid = str(interaction.user.id)
        fila = config["global"].setdefault("fila_mediador", [])
        if uid not in fila:
            await interaction.response.send_message("⚠️ Você não está na fila!", ephemeral=True); return
        fila.remove(uid)
        salvar_config(config)
        await _atualizar_painel_mediador(self.painel_med_msg, config)
        await interaction.response.send_message("✅ Você saiu da fila de mediadores.", ephemeral=True)


class _BtnLimparFilaMediador(Button):
    def __init__(self, painel_med_msg):
        super().__init__(label="Limpar Fila", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="med_limpar_fila")
        self.painel_med_msg = painel_med_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão!", ephemeral=True); return
        config["global"]["fila_mediador"] = []
        salvar_config(config)
        await _atualizar_painel_mediador(self.painel_med_msg, config)
        await interaction.response.send_message("🗑️ Fila de mediadores limpa.", ephemeral=True)


# ──────────────────────────────────────────────
# Confirmação de partida
# ──────────────────────────────────────────────

def build_embed_confirmar(ch: str, preco: dict, confirmados: set, jogadores: list, config: dict) -> discord.Embed:
    cat, m = split_chave(ch)
    embed  = discord.Embed(title="🎮  Partida Encontrada!", color=cor_global(config))
    embed.add_field(name="Categoria", value=f"{EMOJI_CATEGORIA[cat]} {cat}", inline=True)
    embed.add_field(name="Modo",      value=f"{EMOJI_MODO[m]} {m}",          inline=True)
    embed.add_field(name="Valor",     value=preco["valor"],                   inline=True)
    linhas = [f"{'✅' if uid in confirmados else '⬜'} <@{uid}>" for uid in jogadores]
    embed.add_field(name="Confirmações", value="\n".join(linhas), inline=False)
    if len(confirmados) >= len(jogadores):
        embed.color = discord.Color.green()
        embed.add_field(name="\u200b", value="🔥 **Todos confirmaram! Mediador e ADM sendo notificados...**", inline=False)
    else:
        restam = len(jogadores) - len(confirmados)
        embed.add_field(name="\u200b", value=f"⏳ Aguardando **{restam}** confirmação(ões)...", inline=False)
        embed.set_footer(text="Você tem 2 minutos para confirmar ou a partida será cancelada.")
    return embed


class ConfirmarPartidaView(View):
    def __init__(self, ch, preco, jogadores, canal_partida, cargo_adm_id, mediador_uid, mediador_data, cargo_mediador_id, config_ref):
        super().__init__(timeout=120)
        self.ch, self.preco         = ch, preco
        self.jogadores              = jogadores
        self.confirmados            = set()
        self.canal_partida          = canal_partida
        self.cargo_adm_id           = cargo_adm_id
        self.mediador_uid           = mediador_uid
        self.mediador_data          = mediador_data
        self.cargo_mediador_id      = cargo_mediador_id
        self.config_ref             = config_ref
        self.finalizado             = False
        self.add_item(_BtnConfirmar(self))

    async def _atualizar_embed(self, interaction):
        await interaction.response.edit_message(embed=build_embed_confirmar(self.ch, self.preco, self.confirmados, self.jogadores, self.config_ref), view=self)

    async def _todos_confirmaram(self, interaction):
        self.finalizado = True
        self.stop()
        await interaction.response.edit_message(embed=build_embed_confirmar(self.ch, self.preco, self.confirmados, self.jogadores, self.config_ref), view=None)

        # Mostra o PIX do mediador (se houver)
        if self.mediador_uid and self.mediador_data:
            pix_embed = build_embed_pix_mediador(self.mediador_uid, self.mediador_data, self.ch, self.preco)
            await self.canal_partida.send(content=f"<@{self.mediador_uid}>", embed=pix_embed)
        elif self.cargo_mediador_id:
            cargo_med = interaction.guild.get_role(self.cargo_mediador_id)
            if cargo_med:
                await self.canal_partida.send(f"⚠️ {cargo_med.mention} — partida `{self.preco['valor']}` ({display(self.ch)}) **sem mediador na fila**! Algum mediador disponível?")

        # Notifica o cargo ADM
        if self.cargo_adm_id:
            cargo = interaction.guild.get_role(self.cargo_adm_id)
            if cargo:
                await self.canal_partida.set_permissions(cargo, view_channel=True, send_messages=True, read_message_history=True)
                await self.canal_partida.send(f"✅ **Todos confirmaram!**\n{cargo.mention} — partida `{self.preco['valor']}` ({display(self.ch)}) pronta! 🏆")
        else:
            await self.canal_partida.send("✅ **Todos os jogadores confirmaram!**")

    async def on_timeout(self):
        if self.finalizado:
            return
        nao = [uid for uid in self.jogadores if uid not in self.confirmados]

        # Devolve o mediador à fila se ele tinha sido puxado (a partida não rolou)
        if self.mediador_uid:
            try:
                cfg = carregar_config()
                fila = cfg["global"].setdefault("fila_mediador", [])
                if self.mediador_uid not in fila:
                    fila.insert(0, self.mediador_uid)
                    salvar_config(cfg)
            except Exception:
                pass

        try:
            embed = discord.Embed(title="⏰ Tempo Esgotado!", description="Não confirmaram: " + " ".join(f"<@{u}>" for u in nao) + "\n\nCanal fecha em 15 segundos.", color=discord.Color.red())
            await self.canal_partida.send(embed=embed)
            await asyncio.sleep(15)
            await self.canal_partida.delete(reason="Confirmação expirada")
        except Exception:
            pass


class _BtnConfirmar(Button):
    def __init__(self, pv):
        super().__init__(label="✅  Confirmar Presença", style=discord.ButtonStyle.success)
        self.pv = pv

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid not in self.pv.jogadores:
            await interaction.response.send_message("⚠️ Você não faz parte desta partida.", ephemeral=True); return
        if uid in self.pv.confirmados:
            await interaction.response.send_message("✅ Você já confirmou!", ephemeral=True); return
        self.pv.confirmados.add(uid)
        if len(self.pv.confirmados) >= len(self.pv.jogadores):
            await self.pv._todos_confirmaram(interaction)
        else:
            await self.pv._atualizar_embed(interaction)


async def _fila_completa(interaction: discord.Interaction, ch: str, preco: dict, jogadores: list, config: dict):
    guild      = interaction.guild
    global_cfg = config.get("global", {})
    cargo_id   = global_cfg.get("cargo_adm_id")
    cargo_med  = global_cfg.get("cargo_mediador_id")
    cat_id     = global_cfg.get("categoria_id")

    # Puxa o próximo mediador da fila (se houver)
    mediador_uid  = None
    mediador_data = None
    fila_med = global_cfg.setdefault("fila_mediador", [])
    if fila_med:
        mediador_uid = fila_med.pop(0)
        mediadores = global_cfg.get("mediadores", {})
        mediador_data = mediadores.get(str(mediador_uid))
        salvar_config(config)
        # Atualiza painéis de mediador publicados
        await _atualizar_painel_mediador(None, config)

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for uid in jogadores:
        m = guild.get_member(int(uid))
        if m:
            overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    # Mediador também vê o canal
    if mediador_uid:
        m = guild.get_member(int(mediador_uid))
        if m:
            overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    categoria = guild.get_channel(cat_id) if cat_id else None
    cat, modo = split_chave(ch)
    nome      = f"partida-{cat.lower()}-{modo}"
    try:
        canal = await guild.create_text_channel(name=nome, category=categoria, overwrites=overwrites, reason="Bot de filas")
    except discord.Forbidden:
        await interaction.followup.send("❌ Sem permissão para criar canais.", ephemeral=True); return

    view  = ConfirmarPartidaView(ch, preco, jogadores, canal, cargo_id, mediador_uid, mediador_data, cargo_med, config)
    embed = build_embed_confirmar(ch, preco, set(), jogadores, config)
    mencoes = " ".join(f"<@{uid}>" for uid in jogadores)
    await canal.send(content=mencoes, embed=embed, view=view)

    # Notifica ADM já no início da partida (apenas pinga, sem permissão ainda)
    if cargo_id:
        cargo = guild.get_role(cargo_id)
        if cargo:
            await canal.send(f"⚠️ {cargo.mention} — Nova partida `{preco['valor']}` ({display(ch)}) aguardando confirmação!")


# ──────────────────────────────────────────────
# FILAS ON / OFF — mensagem rotativa a cada 5 minutos
# ──────────────────────────────────────────────

_filas_on_msgs: dict[int, int] = {}


async def _atualizar_status_filas(guild: discord.Guild, config: dict):
    """Atualiza imediatamente as mensagens de status FILAS ON/OFF nos canais publicados."""
    ativas = config.get("global", {}).get("filas_ativas", True)
    texto = "@everyone  **🟢 FILAS ON**" if ativas else "**🛑 FILAS OFF — entrada desabilitada**"

    for canal_id, msg_id in list(_filas_on_msgs.items()):
        try:
            canal = bot.get_channel(canal_id)
            if not canal:
                continue
            try:
                antiga = await canal.fetch_message(msg_id)
                await antiga.delete()
            except Exception:
                pass
            nova = await canal.send(texto)
            _filas_on_msgs[canal_id] = nova.id
        except Exception:
            pass

    # Re-renderiza embeds das filas para refletir o status (opcional — apenas tenta)
    # Os embeds são atualizados quando alguém clica num botão.


async def _renovar_filas_on():
    while True:
        await asyncio.sleep(300)
        config = carregar_config()
        ativas = config.get("global", {}).get("filas_ativas", True)
        texto = "@everyone  **🟢 FILAS ON**" if ativas else "**🛑 FILAS OFF — entrada desabilitada**"
        for canal_id, msg_id in list(_filas_on_msgs.items()):
            try:
                canal = bot.get_channel(canal_id)
                if not canal:
                    continue
                try:
                    antiga = await canal.fetch_message(msg_id)
                    await antiga.delete()
                except Exception:
                    pass
                nova = await canal.send(texto)
                _filas_on_msgs[canal_id] = nova.id
            except Exception:
                pass


# ──────────────────────────────────────────────
# Publicar
# ──────────────────────────────────────────────

async def _publicar_filas(interaction: discord.Interaction, config: dict):
    header = discord.Embed(
        title="🎮  Central de Filas",
        description="Bem-vindo!\n• Clique no botão do modo para entrar\n• **❌ Sair da fila** para desistir\n• Quando a fila encher, a partida começa! 🏆",
        color=cor_global(config),
    )
    canais_header: set = set()
    for ch in ALL_MODOS:
        cid = config[ch].get("canal_id")
        if cid and cid not in canais_header:
            canal = interaction.guild.get_channel(cid)
            if canal:
                await canal.send(embed=header)
                canais_header.add(cid)

    publicados = []
    for ch in ALL_MODOS:
        canal = interaction.guild.get_channel(config[ch].get("canal_id"))
        if not canal:
            continue
        b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
        for preco in config[ch].get("precos", []):
            embed = build_embed_fila(ch, preco, config)
            view  = FilaView(ch, preco["id"], b1, b2)
            await canal.send(embed=embed, view=view)
            publicados.append(f"{EMOJI_CATEGORIA[split_chave(ch)[0]]} **{display(ch)}** `{preco['valor']}` → {canal.mention}")
            await asyncio.sleep(0.3)

    # Status (FILAS ON / OFF) em cada canal único
    ativas = config.get("global", {}).get("filas_ativas", True)
    texto  = "@everyone  **🟢 FILAS ON**" if ativas else "**🛑 FILAS OFF — entrada desabilitada**"
    canais_notif: set = set()
    for ch in ALL_MODOS:
        cid = config[ch].get("canal_id")
        if cid and cid not in canais_notif:
            canal = interaction.guild.get_channel(cid)
            if canal:
                msg = await canal.send(texto)
                _filas_on_msgs[cid] = msg.id
                canais_notif.add(cid)

    await interaction.followup.send("✅ **Filas publicadas!**\n\n" + "\n".join(publicados), ephemeral=True)


# ──────────────────────────────────────────────
# Aparência (por servidor)
# ──────────────────────────────────────────────

async def _baixar_imagem(url: str) -> bytes | None:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > 8 * 1024 * 1024:
                    return None
                data = await resp.read()
                if len(data) > 8 * 1024 * 1024:
                    return None
                return data
    except Exception:
        return None


def build_embed_aparencia(guild: discord.Guild, config: dict) -> discord.Embed:
    me = guild.me if guild else None
    ap = config.get("aparencias", {}).get(str(guild.id), {}) if guild else {}

    embed = discord.Embed(
        title="🎨  Aparência do Bot neste Servidor",
        description=(
            f"Personalize como o bot aparece em **{guild.name if guild else '?'}**.\n\n"
            "ℹ️ A **bio** (Sobre Mim) do Discord é global e só pode ser alterada no Developer Portal — aqui ela fica como texto informativo deste servidor."
        ),
        color=cor_global(config),
    )
    embed.add_field(
        name="📛 Apelido (nome no servidor)",
        value=f"`{me.nick}`" if (me and me.nick) else "*— sem apelido (usa o nome global) —*",
        inline=False,
    )
    avatar_status = "✅ definido neste servidor" if (me and getattr(me, "guild_avatar", None)) else "⬜ usando avatar global"
    banner_status = "✅ definido neste servidor" if (me and getattr(me, "guild_banner", None)) else "⬜ não definido"
    embed.add_field(name="🖼️ Foto (avatar)", value=avatar_status, inline=True)
    embed.add_field(name="🎴 Banner",         value=banner_status, inline=True)
    embed.add_field(name="📝 Bio (informativa)", value=ap.get("bio") or "*— não definida —*", inline=False)
    if me and me.display_avatar:
        embed.set_thumbnail(url=me.display_avatar.url)
    if me and getattr(me, "guild_banner", None):
        embed.set_image(url=me.guild_banner.url)
    return embed


class ApelidoModal(Modal):
    def __init__(self, guild):
        super().__init__(title="Editar Apelido")
        self.guild = guild
        atual = guild.me.nick or ""
        self.nick = TextInput(
            label="Apelido (vazio = remover)",
            default=atual, max_length=32, required=False,
            placeholder="Bot Filas",
        )
        self.add_item(self.nick)

    async def on_submit(self, interaction: discord.Interaction):
        novo = self.nick.value.strip() or None
        try:
            await self.guild.me.edit(nick=novo)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot sem permissão **Change Nickname**.", ephemeral=True); return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Discord recusou: `{e}`", ephemeral=True); return
        config = carregar_config()
        try:
            await interaction.response.edit_message(embed=build_embed_aparencia(self.guild, config), view=AparenciaView())
        except Exception:
            await interaction.response.send_message(f"✅ Apelido atualizado: `{novo or '— removido —'}`", ephemeral=True)


class AvatarUrlModal(Modal):
    def __init__(self, guild):
        super().__init__(title="Editar Avatar (Foto)")
        self.guild = guild
        self.url = TextInput(
            label="URL da imagem (PNG/JPG, ≤ 8MB)",
            required=True, placeholder="https://...",
        )
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = await _baixar_imagem(self.url.value.strip())
        if not data:
            await interaction.followup.send("❌ Não consegui baixar a imagem (URL inválida ou maior que 8MB).", ephemeral=True); return
        try:
            await self.guild.me.edit(avatar=data)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Discord recusou: `{e}`", ephemeral=True); return
        config = carregar_config()
        try:
            await interaction.message.edit(embed=build_embed_aparencia(self.guild, config), view=AparenciaView())
        except Exception:
            pass
        await interaction.followup.send("✅ Avatar atualizado neste servidor!", ephemeral=True)


class BannerUrlModal(Modal):
    def __init__(self, guild):
        super().__init__(title="Editar Banner")
        self.guild = guild
        self.url = TextInput(
            label="URL do banner (PNG/JPG/GIF, ≤ 8MB)",
            required=True, placeholder="https://...",
        )
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = await _baixar_imagem(self.url.value.strip())
        if not data:
            await interaction.followup.send("❌ Não consegui baixar a imagem (URL inválida ou maior que 8MB).", ephemeral=True); return
        try:
            await self.guild.me.edit(banner=data)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Discord recusou: `{e}`", ephemeral=True); return
        config = carregar_config()
        try:
            await interaction.message.edit(embed=build_embed_aparencia(self.guild, config), view=AparenciaView())
        except Exception:
            pass
        await interaction.followup.send("✅ Banner atualizado neste servidor!", ephemeral=True)


class BioModal(Modal):
    def __init__(self, guild, config):
        super().__init__(title="Editar Bio (informativa)")
        self.guild = guild
        ap = config.get("aparencias", {}).get(str(guild.id), {})
        self.bio = TextInput(
            label="Texto da bio neste servidor",
            default=ap.get("bio", ""),
            style=discord.TextStyle.paragraph,
            max_length=300, required=False,
            placeholder="Bot oficial de filas. Suporte: @admin",
        )
        self.add_item(self.bio)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        ap = config.setdefault("aparencias", {}).setdefault(str(self.guild.id), {})
        ap["bio"] = self.bio.value.strip()
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_aparencia(self.guild, config), view=AparenciaView())


class AparenciaView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(_BtnEditarApelido())
        self.add_item(_BtnEditarAvatar())
        self.add_item(_BtnEditarBanner())
        self.add_item(_BtnEditarBio())
        self.add_item(_BtnResetarAparencia())


class _BtnEditarApelido(Button):
    def __init__(self):
        super().__init__(label="Apelido", emoji="📛", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ApelidoModal(interaction.guild))


class _BtnEditarAvatar(Button):
    def __init__(self):
        super().__init__(label="Foto", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AvatarUrlModal(interaction.guild))


class _BtnEditarBanner(Button):
    def __init__(self):
        super().__init__(label="Banner", emoji="🎴", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BannerUrlModal(interaction.guild))


class _BtnEditarBio(Button):
    def __init__(self):
        super().__init__(label="Bio", emoji="📝", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(BioModal(interaction.guild, config))


class _BtnResetarAparencia(Button):
    def __init__(self):
        super().__init__(label="Resetar tudo", emoji="🔄", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.guild.me.edit(nick=None, avatar=None, banner=None)
        except discord.HTTPException:
            pass
        config = carregar_config()
        config.setdefault("aparencias", {}).pop(str(interaction.guild.id), None)
        salvar_config(config)
        try:
            await interaction.message.edit(embed=build_embed_aparencia(interaction.guild, config), view=AparenciaView())
        except Exception:
            pass
        await interaction.followup.send("🔄 Aparência resetada neste servidor (apelido, foto, banner e bio).", ephemeral=True)


# ──────────────────────────────────────────────
# Bot
# ──────────────────────────────────────────────

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        config = carregar_config()
        for ch in ALL_MODOS:
            b1 = config[ch]["botao1"]
            b2 = config[ch]["botao2"]
            for preco in config[ch].get("precos", []):
                self.add_view(FilaView(ch, preco["id"], b1, b2))
        # Painel mediador persistente
        self.add_view(PainelMediadorView())
        # Sync global (pode demorar até 1h pra propagar)
        await self.tree.sync()
        print("✅ Slash commands globais sincronizados.")

    async def on_ready(self):
        print(f"🤖 Bot conectado como {self.user} (ID: {self.user.id})")
        # Sync por guild — comandos aparecem imediatamente em cada servidor
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"   ↳ {len(synced)} comandos sincronizados em '{guild.name}'")
            except Exception as e:
                print(f"   ⚠️ Falha ao sincronizar em '{guild.name}': {e}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="as filas 🎮"))
        asyncio.create_task(_renovar_filas_on())

    async def on_guild_join(self, guild: discord.Guild):
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"✅ Comandos sincronizados ao entrar em '{guild.name}'")
        except Exception as e:
            print(f"⚠️ Erro ao sincronizar em '{guild.name}': {e}")


bot = MyBot()


# ──────────────────────────────────────────────
# Permission check para slash commands
# ──────────────────────────────────────────────

async def _check_pode_admin(interaction: discord.Interaction) -> bool:
    config = carregar_config()
    if usuario_pode_admin(interaction.user, config):
        return True
    await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
    return False


@bot.tree.command(name="painel", description="Abre o painel de configuração das filas")
async def painel(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    view   = PainelPrincipalView()
    await interaction.response.send_message(embed=build_embed_painel_geral(config), view=view, ephemeral=True)
    msg = await interaction.original_response()
    view.set_message(msg)


@bot.tree.command(name="criarfilas", description="Publica os embeds de fila nos canais configurados")
async def criarfilas(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    config    = carregar_config()
    sem_canal = [ch for ch in ALL_MODOS if not config[ch].get("canal_id")]
    if sem_canal:
        await interaction.followup.send(f"⚠️ Configure os canais com `/painel`. Sem canal: {len(sem_canal)} modo(s).", ephemeral=True)
        return
    await _publicar_filas(interaction, config)


@bot.tree.command(name="painel_mediador", description="Publica o painel de mediadores no canal atual")
async def painel_mediador(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    embed  = build_embed_painel_mediador(config)
    view   = PainelMediadorView()
    msg    = await interaction.channel.send(embed=embed, view=view)
    _painel_mediador_msgs[interaction.channel.id] = msg.id
    # Atualiza a view com a referência da msg
    novaview = PainelMediadorView(msg)
    await msg.edit(view=novaview)
    await interaction.response.send_message("✅ Painel de mediadores publicado!", ephemeral=True)


@bot.tree.command(name="filas_off", description="Desativa as filas (ninguém pode entrar)")
async def filas_off(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    config["global"]["filas_ativas"] = False
    salvar_config(config)
    await _atualizar_status_filas(interaction.guild, config)
    await interaction.response.send_message("🛑 **Filas DESATIVADAS** — ninguém pode entrar nas filas até serem reativadas.", ephemeral=True)


@bot.tree.command(name="filas_on", description="Reativa as filas")
async def filas_on(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    config["global"]["filas_ativas"] = True
    salvar_config(config)
    await _atualizar_status_filas(interaction.guild, config)
    await interaction.response.send_message("🟢 **Filas ATIVADAS** — os jogadores já podem entrar.", ephemeral=True)


@bot.tree.command(name="aparencia", description="Personalize a aparência do bot neste servidor (apelido, foto, banner, bio)")
async def aparencia(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    if not interaction.guild:
        await interaction.response.send_message("❌ Use este comando dentro de um servidor.", ephemeral=True); return
    config = carregar_config()
    await interaction.response.send_message(
        embed=build_embed_aparencia(interaction.guild, config),
        view=AparenciaView(),
        ephemeral=True,
    )


def _run_health_server():
    port = int(os.environ.get("PORT", 8080))

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    try:
        server = http.server.HTTPServer(("0.0.0.0", port), _Handler)
        server.serve_forever()
    except OSError:
        pass


if os.environ.get("PORT"):
    _health_thread = threading.Thread(target=_run_health_server, daemon=True)
    _health_thread.start()

bot.run(TOKEN)
