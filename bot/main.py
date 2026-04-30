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


def get_admin_btn(key: str) -> dict:
    """Lê a configuração do botão do painel admin (com fallback ao default)."""
    try:
        cfg = carregar_config()
        b = cfg.get("global", {}).get("painel_admin_botoes", {}).get(key, {})
    except Exception:
        b = {}
    base = PAINEL_ADMIN_BOTOES_DEFAULT.get(key, {"emoji": "", "label": key})
    return {"emoji": b.get("emoji") or base["emoji"], "label": b.get("label", base["label"])}


def aplicar_btn_admin(btn, key: str):
    """Aplica emoji + label personalizados a um Button já criado."""
    info = get_admin_btn(key)
    btn.label = info["label"] or None
    if info["emoji"]:
        btn.emoji = to_discord_emoji(info["emoji"])
    else:
        btn.emoji = None


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

PAINEL_ADMIN_BOTOES_DEFAULT = {
    # Painel Principal
    "config_geral":    {"emoji": "⚙️", "label": "Config Geral"},
    "embed_global":    {"emoji": "🎨", "label": "Embed Global"},
    "filas_on":        {"emoji": "🟢", "label": "Filas ON"},
    "filas_off":       {"emoji": "🛑", "label": "Filas OFF"},
    "publicar":        {"emoji": "🚀", "label": "Publicar Filas"},
    "personalizar":    {"emoji": "🎛️", "label": "Personalizar Painel"},
    # Painel do Modo
    "editar_embed":    {"emoji": "✏️", "label": "Título/Banner"},
    "editar_botoes":   {"emoji": "🎮", "label": "Editar Botões"},
    "texto_layout":    {"emoji": "📝", "label": "Texto/Layout"},
    "placeholders":    {"emoji": "❓", "label": "Placeholders"},
    "visualizar":      {"emoji": "👁️", "label": "Visualizar"},
    "precos":          {"emoji": "💰", "label": "Preços"},
    "voltar":          {"emoji": "◀️", "label": "Voltar"},
}


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
        # Layout/texto personalizável.
        # Placeholders no formato [[chave]] — válidos:
        # [[modo_jogo]], [[valor_partida]], [[jogadores_fila]]
        "descricao_template":     "",
        "cor":                    "",   # HEX por modo (vazio = usa global)
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
    g.setdefault("cargo_autorole_id",  None)   # cargo dado automaticamente a novos membros
    g.setdefault("categoria_id",       None)
    g.setdefault("logs", {
        "iniciadas":     None,   # logs-iniciadas — quando uma partida começa
        "confirmadas":   None,   # logs-confirmadas — quando todos confirmam
        "cancelada":     None,   # logs-cancelada — quando alguém cancela
        "finalizadas":   None,   # logs-finalizadas — quando /vencedor é usado
        "mediador":      None,   # logs-mediador — entrar/sair/puxar mediador
        "ticket":        None,   # logs-ticket — abertura/fechamento de tickets
        "vitorias_ws":   None,   # logs-vitorias-ws — vencedores de partida do streamer
        "saiu_servidor": None,   # saiu-do-servidor — quando alguém sai do servidor
    })
    _logs = g["logs"]
    for k in ("iniciadas", "confirmadas", "cancelada", "finalizadas",
              "mediador", "ticket", "vitorias_ws", "saiu_servidor"):
        _logs.setdefault(k, None)
    g.setdefault("filas_ativas",       True)
    g.setdefault("embed_global", {
        "banner":    "",
        "thumbnail": "",
        "cor":       f"#{COR_PADRAO:06X}",
    })
    g.setdefault("mediadores",     {})   # {user_id_str: {"tipo": "...", "chave": "...", "nome": "..."}}
    g.setdefault("fila_mediador",  [])   # [user_id_str, ...]

    # Fila do Streamer
    g.setdefault("streamer", {
        "user_id": None,    # quem é o streamer
        "modo":    "1v1",   # 1v1 / 2v2 / 3v3 / 4v4
        "fila":    [],      # [user_id_str, ...] — pessoas esperando enfrentar
        "aberta":  False,   # se está aceitando entradas
    })

    # Embeds personalizáveis dos painéis
    g.setdefault("painel_streamer_embed", {
        "titulo":    "🎮 Fila Contra 5 INVIT 3 NO PIX! | #1K",
        "descricao": "",   # vazio = usa texto padrão
        "subtitulo": "SO FREE FIRE",
        "instrucoes": "• Clique em **Jogar Contra** para abrir um desafio.\n• O desafio expira automaticamente se não for aceito.",
        "info_jogo":  "Jogando contra membros em live, tiktok @olipesick",
        "banner":    "",
        "thumbnail": "",
    })
    # Migração: garantir campos novos em configs antigos
    _pse = g["painel_streamer_embed"]
    _pse.setdefault("subtitulo",  "SO FREE FIRE")
    _pse.setdefault("instrucoes", "• Clique em **Jogar Contra** para abrir um desafio.\n• O desafio expira automaticamente se não for aceito.")
    _pse.setdefault("info_jogo",  "Jogando contra membros em live, tiktok @olipesick")

    g.setdefault("painel_mediador_embed", {
        "titulo":    "🤝  Painel de Mediadores",
        "descricao": "",
        "banner":    "",
        "thumbnail": "",
    })

    # Botões personalizáveis do painel do streamer
    g.setdefault("painel_streamer_botoes", {
        "jogar_contra": {"emoji": "🚪", "label": "Jogar Contra"},
        "gear":         {"emoji": "⚙️", "label": ""},
        "entrar":       {"emoji": "✅", "label": "Entrar na Fila"},
        "sair":         {"emoji": "❌", "label": "Sair da Fila"},
        "proximo":      {"emoji": "🎮", "label": "Chamar Próximo"},
        "toggle":       {"emoji": "🔁", "label": "Abrir/Fechar"},
    })
    # Migração: garantir botões novos em configs antigos
    _psb = g["painel_streamer_botoes"]
    _psb.setdefault("jogar_contra", {"emoji": "🚪", "label": "Jogar Contra"})
    _psb.setdefault("gear",         {"emoji": "⚙️", "label": ""})

    # Botões personalizáveis dos painéis de administração
    g.setdefault("painel_admin_botoes", {})
    pab = g["painel_admin_botoes"]
    for k, v in PAINEL_ADMIN_BOTOES_DEFAULT.items():
        pab.setdefault(k, dict(v))

    # Sistema de Tickets
    g.setdefault("tickets", {
        "embed": {
            "titulo":    "🎫 Central de Tickets",
            "descricao": "Precisa de ajuda? Clique num dos botões abaixo pra abrir um ticket.",
            "thumbnail": "",
            "banner":    "",
            "cor":       "",   # vazio = usa cor global
        },
        "botoes": [],   # [{id, emoji, label, estilo, canal_id, mensagem_inicial, cargo_atendimento_id}]
    })
    _tk = g["tickets"]
    _tk.setdefault("embed", {})
    _tke = _tk["embed"]
    _tke.setdefault("titulo",    "🎫 Central de Tickets")
    _tke.setdefault("descricao", "Precisa de ajuda? Clique num dos botões abaixo pra abrir um ticket.")
    _tke.setdefault("thumbnail", "")
    _tke.setdefault("banner",    "")
    _tke.setdefault("cor",       "")
    _tk.setdefault("botoes", [])
    for b in _tk["botoes"]:
        b.setdefault("id", gerar_id())
        b.setdefault("emoji", "🎫")
        b.setdefault("label", "Abrir Ticket")
        b.setdefault("estilo", "primary")
        b.setdefault("canal_id", None)
        b.setdefault("mensagem_inicial", "Olá {user}! Descreva sua questão e aguarde um atendente.")
        b.setdefault("cargo_atendimento_id", None)

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
        cfg.setdefault("descricao_template", "")
        cfg.setdefault("cor",                "")

        for p in cfg["precos"]:
            p.setdefault("id",        gerar_id())
            p.setdefault("jogadores", [])

    return data


def salvar_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Sistema de Logs
# ──────────────────────────────────────────────

LOG_TIPOS = [
    ("iniciadas",     "📥  Logs Iniciadas",     "Quando uma partida começa (canal criado).",        0x3498DB),
    ("confirmadas",   "✅  Logs Confirmadas",   "Quando todos os jogadores confirmam presença.",     0x2ECC71),
    ("cancelada",     "❌  Logs Cancelada",     "Quando uma aposta é cancelada por alguém.",         0xE74C3C),
    ("finalizadas",   "🏆  Logs Finalizadas",   "Quando o vencedor é definido com /vencedor.",       0xF1C40F),
    ("mediador",      "🤝  Logs Mediador",      "Mediadores entrando/saindo da fila ou sendo puxados.", 0x9B59B6),
    ("ticket",        "🎫  Logs Ticket",        "Tickets abertos e fechados.",                        0x1ABC9C),
    ("vitorias_ws",   "🎬  Logs Vitórias WS",   "Vencedores de partidas do streamer.",               0xE91E63),
    ("saiu_servidor", "👋  Saiu do Servidor",   "Quando um membro sai do servidor.",                  0x95A5A6),
]

LOG_LABEL = {k: l for k, l, _, _ in LOG_TIPOS}
LOG_COR   = {k: c for k, _, _, c in LOG_TIPOS}


def _log_canal(guild: discord.Guild, tipo: str, config: dict | None = None):
    if not guild:
        return None
    if config is None:
        config = carregar_config()
    cid = config.get("global", {}).get("logs", {}).get(tipo)
    if not cid:
        return None
    return guild.get_channel(cid)


async def _send_log(guild: discord.Guild | None, tipo: str, embed: discord.Embed | None = None,
                    content: str | None = None, config: dict | None = None):
    """Envia uma mensagem ao canal de log configurado para esse tipo, se houver."""
    try:
        canal = _log_canal(guild, tipo, config)
        if not canal:
            return
        await canal.send(content=content, embed=embed)
    except Exception as e:
        print(f"⚠️ Falha ao enviar log [{tipo}]: {e}")


def _log_embed(tipo: str, titulo: str, descricao: str = "", autor: discord.abc.User | None = None) -> discord.Embed:
    embed = discord.Embed(title=titulo, description=descricao, color=LOG_COR.get(tipo, 0x2F3136))
    embed.timestamp = discord.utils.utcnow()
    if autor:
        embed.set_author(name=str(autor), icon_url=autor.display_avatar.url if autor.display_avatar else None)
        embed.set_footer(text=f"ID: {autor.id}")
    return embed


def encontrar_preco(config: dict, preco_id: str):
    for ch in ALL_MODOS:
        for p in config[ch].get("precos", []):
            if p["id"] == preco_id:
                return ch, p
    return None, None


def cor_global(config: dict) -> int:
    return parse_cor(config.get("global", {}).get("embed_global", {}).get("cor", ""))


def cor_efetiva(config: dict, ch: str) -> int:
    """Cor por modo se definida; senão a global."""
    cor_modo = config.get(ch, {}).get("cor", "")
    if cor_modo:
        return parse_cor(cor_modo)
    return cor_global(config)


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

# Parâmetros aceitos no template — sintaxe: [[chave]]
PARAMETROS_INFO = [
    ("modo_jogo",      "Responsável por informar o modo de jogo (1x1 Mobile, 2x2 Emulador e etc)."),
    ("valor_partida",  "Responsável por informar o valor das partidas."),
    ("jogadores_fila", "Responsável por informar os jogadores presentes na fila."),
]


def _ctx_fila(ch: str, preco: dict, config: dict) -> dict:
    """Valores reais de cada parâmetro [[...]] para essa fila."""
    cat, m    = split_chave(ch)
    jogadores = preco.get("jogadores", [])
    total     = jogadores_da_chave(ch)
    lista_jog = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(jogadores)) or "*Nenhum jogador na fila.*"
    return {
        "modo_jogo":      m,
        "valor_partida":  preco.get("valor", ""),
        "jogadores_fila": lista_jog,
    }


def _render_template(tpl: str, ctx: dict) -> str:
    """Substitui placeholders no formato [[chave]]."""
    if not tpl:
        return ""
    out = tpl
    for k, v in ctx.items():
        out = out.replace(f"[[{k}]]", str(v))
    return out


def build_embed_fila(ch: str, preco: dict, config: dict) -> discord.Embed:
    cfg       = config[ch]
    cat, m    = split_chave(ch)
    jogadores = preco.get("jogadores", [])
    total     = jogadores_da_chave(ch)
    g         = config.get("global", {})

    ctx  = _ctx_fila(ch, preco, config)
    cor  = cor_efetiva(config, ch)

    descricao_template = cfg.get("descricao_template", "")
    if descricao_template:
        embed = discord.Embed(
            title=cfg.get("titulo", display(ch)),
            description=_render_template(descricao_template, ctx),
            color=cor,
        )
        if not g.get("filas_ativas", True):
            embed.add_field(name="\u200b", value="🛑 **FILAS DESATIVADAS**", inline=False)
        elif len(jogadores) >= total:
            embed.add_field(name="\u200b", value="🔥 **Fila completa! Partida iniciando...**", inline=False)
    else:
        # Layout clássico (campos separados)
        embed = discord.Embed(title=cfg.get("titulo", display(ch)), color=cor)
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
    cargo_auto = f"<@&{g['cargo_autorole_id']}>" if g.get("cargo_autorole_id") else "`Não definido`"
    cat   = f"<#{g['categoria_id']}>"   if g.get("categoria_id") else "`Não definida`"
    embed = discord.Embed(title="⚙️  Configuração Global", color=cor_global(config))
    embed.add_field(name="👑 Cargo Permissão Máxima", value=cargo_max, inline=False)
    embed.add_field(name="🛡️ Cargo ADM (notificado nas partidas)", value=cargo_adm, inline=False)
    embed.add_field(name="🤝 Cargo Mediador",         value=cargo_med, inline=False)
    embed.add_field(name="🎟️ Cargo Autorole (novos membros)", value=cargo_auto, inline=False)
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
    custom     = g.get("painel_mediador_embed", {})
    titulo     = custom.get("titulo") or "🤝  Painel de Mediadores"

    embed = discord.Embed(
        title=titulo,
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

    thumb  = custom.get("thumbnail") or g.get("embed_global", {}).get("thumbnail", "")
    banner = custom.get("banner")    or g.get("embed_global", {}).get("banner", "")
    if thumb:
        embed.set_thumbnail(url=thumb)
    if banner:
        embed.set_image(url=banner)
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


class EditarLayoutModal(Modal):
    """Modal: Editar Template — descrição, thumbnail e cor."""
    def __init__(self, ch: str, config: dict, painel_msg=None):
        super().__init__(title=f"Editar Template: {display(ch)}"[:45])
        self.ch, self.painel_msg = ch, painel_msg
        cfg = config[ch]

        self.descricao = TextInput(
            label="ADICIONE A DESCRIÇÃO DO EMBED",
            default=cfg.get("descricao_template", ""),
            required=True, max_length=2000,
            style=discord.TextStyle.paragraph,
            placeholder="Ex: [[modo_jogo]] • [[valor_partida]]\n[[jogadores_fila]]",
        )
        self.thumb = TextInput(
            label="ADICIONE A URL DO AVATAR (Thumbnail)",
            default=cfg.get("thumbnail", ""),
            required=False, max_length=500,
            placeholder="https://...",
        )
        self.cor = TextInput(
            label="ADICIONE A COR (HEX: #FFFFFF)",
            default=cfg.get("cor", "") or "#FFDF00",
            required=True, max_length=9,
            placeholder="#FFDF00",
        )
        for it in (self.descricao, self.thumb, self.cor):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        cfg = config[self.ch]
        cfg["descricao_template"] = self.descricao.value.strip()
        cfg["thumbnail"]          = self.thumb.value.strip()
        cfg["cor"]                = self.cor.value.strip()
        salvar_config(config)
        cat, _ = split_chave(self.ch)
        await interaction.response.edit_message(
            embed=build_embed_config_modo(self.ch, config),
            view=ModoConfigView(self.ch, cat, self.painel_msg),
        )
        await _republicar_embeds_modo(self.ch, config)
        await interaction.followup.send(
            "✅ **Template atualizado!**\n"
            "Use o botão **❓ Placeholders** para ver os parâmetros disponíveis.",
            ephemeral=True,
        )


# Registro de mensagens de fila publicadas para republicação ao editar layout.
# Estrutura: { preco_id: (canal_id, message_id) }
_filas_msg_ids: dict[str, tuple] = {}


async def _republicar_embeds_modo(ch: str, config: dict):
    """Atualiza todas as mensagens de fila publicadas deste modo (em todos os preços)."""
    for preco in config[ch].get("precos", []):
        info = _filas_msg_ids.get(preco["id"])
        if not info:
            continue
        canal_id, msg_id = info
        canal = bot.get_channel(canal_id)
        if not canal:
            continue
        try:
            msg = await canal.fetch_message(msg_id)
            b1, b2 = config[ch]["botao1"], config[ch]["botao2"]
            await msg.edit(
                embed=build_embed_fila(ch, preco, config),
                view=FilaView(ch, preco["id"], b1, b2),
            )
        except Exception:
            pass


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


# ──────────────────────────────────────────────
# Helpers de parsing/ordenação de preços
# ──────────────────────────────────────────────

def _parse_valor_preco(texto: str) -> float | None:
    """Extrai o valor numérico de um texto. Retorna None se não for um preço válido.

    Aceita formatos como: "R$ 1,00", "1.50", "10,00", "R$1", "5", "R$  100,50"
    """
    if not texto:
        return None
    s = texto.strip()
    # Remove tudo que não for dígito, vírgula, ponto ou sinal
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    # Trata o caso "1.234,56" (vírgula decimal, ponto milhar) → "1234.56"
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def _formatar_valor_preco(valor: str) -> str:
    """Normaliza a apresentação de um preço para o formato 'R$ X,YZ'."""
    n = _parse_valor_preco(valor)
    if n is None:
        return valor.strip()
    if n == int(n):
        return f"R$ {int(n):,}".replace(",", ".") + ",00"
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ordenar_precos(precos: list) -> list:
    """Ordena a lista de preços do menor pro maior. Inválidos vão pro fim."""
    def _key(p):
        v = _parse_valor_preco(p.get("valor", ""))
        return (1, 0.0) if v is None else (0, v)
    return sorted(precos, key=_key)


class AdicionarPrecoModal(Modal):
    def __init__(self, ch: str, painel_msg=None):
        super().__init__(title=f"Adicionar Preços — {display(ch)}"[:45])
        self.ch, self.painel_msg = ch, painel_msg
        self.valor = TextInput(
            label="Valores (um por linha)",
            placeholder="R$ 1,00\nR$ 2,50\nR$ 10,00",
            style=discord.TextStyle.paragraph,
            max_length=500, required=True,
        )
        self.add_item(self.valor)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        linhas = [l.strip() for l in self.valor.value.splitlines() if l.strip()]
        if not linhas:
            await interaction.response.send_message("❌ Você não digitou nenhum preço.", ephemeral=True); return

        validos: list[tuple[str, float]] = []
        invalidos: list[str] = []
        for ln in linhas:
            v = _parse_valor_preco(ln)
            if v is None:
                invalidos.append(ln)
            else:
                validos.append((_formatar_valor_preco(ln), v))

        if not validos:
            msg = "❌ **Nenhum preço válido foi reconhecido.**\n"
            msg += "\n".join(f"• `{x}`" for x in invalidos[:10])
            msg += "\n\n**Exemplos válidos:** `R$ 1,00`, `2.50`, `10`"
            await interaction.response.send_message(msg, ephemeral=True); return

        novos_ids = []
        for valor_fmt, _ in validos:
            novo = {"id": gerar_id(), "valor": valor_fmt, "jogadores": []}
            config[self.ch]["precos"].append(novo)
            novos_ids.append(novo["id"])

        # Ordena do menor pro maior
        config[self.ch]["precos"] = _ordenar_precos(config[self.ch]["precos"])
        salvar_config(config)

        b1 = config[self.ch]["botao1"]; b2 = config[self.ch]["botao2"]
        for nid in novos_ids:
            bot.add_view(FilaView(self.ch, nid, b1, b2))

        view = GerenciarPrecosView(self.ch, self.painel_msg)
        view.selected_id = novos_ids[-1]
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.ch, config, novos_ids[-1]), view=view)
        await _atualizar_painel(self.painel_msg, config)

        resumo = f"✅ **{len(validos)}** preço(s) adicionado(s) e ordenado(s) do menor pro maior."
        if invalidos:
            resumo += f"\n⚠️ **{len(invalidos)}** linha(s) ignorada(s) por não ser(em) preço válido:\n"
            resumo += "\n".join(f"• `{x}`" for x in invalidos[:10])
        await interaction.followup.send(resumo, ephemeral=True)


class EditarPrecoModal(Modal):
    def __init__(self, ch: str, preco_id: str, config: dict, gv):
        preco = next((p for p in config[ch]["precos"] if p["id"] == preco_id), None)
        super().__init__(title=f"Editar Preço — {preco['valor'] if preco else ch}"[:45])
        self.ch, self.preco_id, self.gv = ch, preco_id, gv
        self.valor = TextInput(label="Valor (ex: R$ 1,00)", default=preco["valor"] if preco else "", max_length=30, required=True)
        self.add_item(self.valor)

    async def on_submit(self, interaction: discord.Interaction):
        v = _parse_valor_preco(self.valor.value)
        if v is None:
            await interaction.response.send_message(
                f"❌ `{self.valor.value}` não é um preço válido.\n**Exemplos:** `R$ 1,00`, `2.50`, `10`",
                ephemeral=True,
            ); return

        config = carregar_config()
        for p in config[self.ch]["precos"]:
            if p["id"] == self.preco_id:
                p["valor"] = _formatar_valor_preco(self.valor.value)
                break
        # Reordena do menor pro maior
        config[self.ch]["precos"] = _ordenar_precos(config[self.ch]["precos"])
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
        self.add_item(_BtnEditarLayout(ch, painel_msg))
        self.add_item(_BtnVerPlaceholders(ch))
        self.add_item(_BtnVisualizar(ch))
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
        super().__init__(style=discord.ButtonStyle.primary, row=1)
        aplicar_btn_admin(self, "editar_embed")
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarEmbedModal(self.ch, config, self.painel_msg))


class _BtnEditarBotoes(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(style=discord.ButtonStyle.secondary, row=1)
        aplicar_btn_admin(self, "editar_botoes")
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarBotoesModal(self.ch, config, self.painel_msg))


class _BtnEditarLayout(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(style=discord.ButtonStyle.secondary, row=2)
        aplicar_btn_admin(self, "texto_layout")
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_modal(EditarLayoutModal(self.ch, config, self.painel_msg))


class _BtnVerPlaceholders(Button):
    def __init__(self, ch):
        super().__init__(style=discord.ButtonStyle.secondary, row=2)
        aplicar_btn_admin(self, "placeholders")
        self.ch = ch

    async def callback(self, interaction: discord.Interaction):
        linhas = [f"- `[[{chave}]]`: {desc}" for chave, desc in PARAMETROS_INFO]
        texto = (
            "## **PARÂMETROS OBRIGATÓRIOS:**\n"
            + "\n".join(linhas)
            + "\n\n*Todos os parâmetros, obrigatoriamente, tem que estar dentro "
              "das chaves \" `[[]]` \", igual os exemplos a cima.*"
        )
        await interaction.response.send_message(texto, ephemeral=True)


class _BtnVisualizar(Button):
    def __init__(self, ch):
        super().__init__(style=discord.ButtonStyle.success, row=2)
        aplicar_btn_admin(self, "visualizar")
        self.ch = ch

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        cfg = config[self.ch]
        precos = cfg.get("precos", [])
        if not precos:
            await interaction.response.send_message(
                "⚠️ Esse modo ainda não tem nenhum preço cadastrado para gerar a prévia.",
                ephemeral=True,
            )
            return
        embed = build_embed_fila(self.ch, precos[0], config)
        await interaction.response.send_message(
            content="**Prévia do embed da fila:**",
            embed=embed,
            ephemeral=True,
        )


class _BtnGerenciarPrecos(Button):
    def __init__(self, ch, painel_msg):
        super().__init__(style=discord.ButtonStyle.secondary, row=1)
        aplicar_btn_admin(self, "precos")
        self.ch, self.painel_msg = ch, painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_gerenciar_precos(self.ch, config), view=GerenciarPrecosView(self.ch, self.painel_msg))


class _BtnVoltarCategoria(Button):
    def __init__(self, cat, painel_msg):
        super().__init__(style=discord.ButtonStyle.secondary, row=1)
        aplicar_btn_admin(self, "voltar")
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
        self.add_item(_BtnAbrirAutorole(painel_msg))
        self.add_item(_BtnAbrirLogs(painel_msg))


class ConfigAutoroleView(View):
    def __init__(self, painel_msg=None):
        super().__init__(timeout=300)
        self.painel_msg = painel_msg
        self.add_item(_RoleSelectAutorole(painel_msg))
        self.add_item(_BtnVoltarConfigGeral(painel_msg))


def build_embed_config_autorole(config: dict) -> discord.Embed:
    g = config.get("global", {})
    cargo_auto = f"<@&{g['cargo_autorole_id']}>" if g.get("cargo_autorole_id") else "`Não definido`"
    embed = discord.Embed(
        title="🎟️  Autorole — Cargo automático",
        description=(
            "Escolha um cargo abaixo. Todo membro novo que entrar no servidor "
            "vai receber esse cargo automaticamente.\n\n"
            "Para **desativar**, abra o seletor e clique fora sem escolher nada."
        ),
        color=cor_global(config),
    )
    embed.add_field(name="Cargo atual", value=cargo_auto, inline=False)
    embed.add_field(
        name="⚠️ Importante",
        value=(
            "• O cargo do bot precisa estar **acima** do cargo do autorole na lista de cargos.\n"
            "• O bot precisa da permissão **Gerenciar Cargos**.\n"
            "• Não funciona com bots que entrarem no servidor (apenas usuários)."
        ),
        inline=False,
    )
    return embed


class _RoleSelectAutorole(RoleSelect):
    def __init__(self, painel_msg):
        super().__init__(placeholder="🎟️ Selecione o Cargo Autorole...", min_values=0, max_values=1, row=0)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["cargo_autorole_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(embed=build_embed_config_autorole(config), view=ConfigAutoroleView(self.painel_msg))
        txt = f"✅ Autorole definido: {self.values[0].mention}" if self.values else "✅ Autorole removido."
        await interaction.followup.send(txt, ephemeral=True)
        await _atualizar_painel(self.painel_msg, config)


class _BtnAbrirAutorole(Button):
    def __init__(self, painel_msg):
        super().__init__(label="🎟️  Autorole", style=discord.ButtonStyle.primary, row=4)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_autorole(config), view=ConfigAutoroleView(self.painel_msg))


class _BtnVoltarConfigGeral(Button):
    def __init__(self, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))


# ──────────────────────────────────────────────
# View: Configuração de Logs (com paginação)
# ──────────────────────────────────────────────

LOGS_POR_PAGINA = 4


def build_embed_config_logs(config: dict, pagina: int = 0) -> discord.Embed:
    g = config.get("global", {})
    logs = g.get("logs", {})
    embed = discord.Embed(
        title="📜  Sistema de Logs",
        description=(
            f"Configure um canal para cada tipo de evento.\n"
            f"Para **desativar** um log, abra o seletor e clique fora sem escolher.\n\n"
            f"**Página {pagina + 1}/{(len(LOG_TIPOS) + LOGS_POR_PAGINA - 1) // LOGS_POR_PAGINA}**"
        ),
        color=cor_global(config),
    )
    inicio = pagina * LOGS_POR_PAGINA
    fim    = inicio + LOGS_POR_PAGINA
    for chave, label, descricao, _ in LOG_TIPOS[inicio:fim]:
        cid = logs.get(chave)
        canal_txt = f"<#{cid}>" if cid else "`Não configurado`"
        embed.add_field(name=label, value=f"{descricao}\n→ {canal_txt}", inline=False)
    return embed


class ConfigLogsView(View):
    def __init__(self, painel_msg=None, pagina: int = 0):
        super().__init__(timeout=300)
        self.painel_msg = painel_msg
        self.pagina = pagina
        inicio = pagina * LOGS_POR_PAGINA
        fim    = inicio + LOGS_POR_PAGINA
        for i, (chave, label, _, _) in enumerate(LOG_TIPOS[inicio:fim]):
            self.add_item(_CanalSelectLog(painel_msg, chave, label, row=i, pagina=pagina))
        # Linha de navegação (row 4)
        total_pgs = (len(LOG_TIPOS) + LOGS_POR_PAGINA - 1) // LOGS_POR_PAGINA
        if pagina > 0:
            self.add_item(_BtnLogsPaginaAnterior(painel_msg, pagina))
        if pagina < total_pgs - 1:
            self.add_item(_BtnLogsProximaPagina(painel_msg, pagina))
        self.add_item(_BtnVoltarConfigGeralFromLogs(painel_msg))


class _CanalSelectLog(ChannelSelect):
    def __init__(self, painel_msg, chave: str, label: str, row: int, pagina: int):
        super().__init__(
            placeholder=f"{label} — escolha o canal…",
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1, row=row,
        )
        self.painel_msg = painel_msg
        self.chave      = chave
        self.pagina     = pagina

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"].setdefault("logs", {})[self.chave] = self.values[0].id if self.values else None
        salvar_config(config)
        await interaction.response.edit_message(
            embed=build_embed_config_logs(config, self.pagina),
            view=ConfigLogsView(self.painel_msg, self.pagina),
        )
        if self.values:
            await interaction.followup.send(f"✅ Log **{LOG_LABEL[self.chave]}** → <#{self.values[0].id}>", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Log **{LOG_LABEL[self.chave]}** desativado.", ephemeral=True)


class _BtnLogsProximaPagina(Button):
    def __init__(self, painel_msg, pagina: int):
        super().__init__(label="Próxima  ▶", style=discord.ButtonStyle.primary, row=4)
        self.painel_msg = painel_msg
        self.pagina     = pagina

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        nova = self.pagina + 1
        await interaction.response.edit_message(
            embed=build_embed_config_logs(config, nova),
            view=ConfigLogsView(self.painel_msg, nova),
        )


class _BtnLogsPaginaAnterior(Button):
    def __init__(self, painel_msg, pagina: int):
        super().__init__(label="◀  Anterior", style=discord.ButtonStyle.primary, row=4)
        self.painel_msg = painel_msg
        self.pagina     = pagina

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        nova = self.pagina - 1
        await interaction.response.edit_message(
            embed=build_embed_config_logs(config, nova),
            view=ConfigLogsView(self.painel_msg, nova),
        )


class _BtnVoltarConfigGeralFromLogs(Button):
    def __init__(self, painel_msg):
        super().__init__(label="◀️  Voltar", style=discord.ButtonStyle.secondary, row=4)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))


class _BtnAbrirLogs(Button):
    def __init__(self, painel_msg):
        super().__init__(label="📜  Logs", style=discord.ButtonStyle.primary, row=4)
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_logs(config, 0), view=ConfigLogsView(self.painel_msg, 0))


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
        self.add_item(_BtnPersonalizarPainel(painel_msg))

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
        super().__init__(style=discord.ButtonStyle.primary, row=1)
        aplicar_btn_admin(self, "config_geral")
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_geral(config), view=ConfigGeralView(self.painel_msg))


class _BtnEmbedGlobal(Button):
    def __init__(self, painel_msg):
        super().__init__(style=discord.ButtonStyle.primary, row=1)
        aplicar_btn_admin(self, "embed_global")
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.edit_message(embed=build_embed_config_embed_global(config), view=EmbedGlobalView(self.painel_msg))


class _BtnFilasToggle(Button):
    def __init__(self, painel_msg):
        config = carregar_config()
        ativas = config.get("global", {}).get("filas_ativas", True)
        super().__init__(
            style=discord.ButtonStyle.danger if ativas else discord.ButtonStyle.success,
            row=1,
        )
        # Quando filas estão ATIVAS, o botão oferece DESLIGAR (filas_off);
        # quando DESATIVADAS, oferece LIGAR (filas_on).
        aplicar_btn_admin(self, "filas_off" if ativas else "filas_on")
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


class _BtnPersonalizarPainel(Button):
    def __init__(self, painel_msg):
        super().__init__(style=discord.ButtonStyle.secondary, row=1)
        aplicar_btn_admin(self, "personalizar")
        self.painel_msg = painel_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        embed = discord.Embed(
            title="🎛️ Personalizar Painel",
            description=(
                "Escolha qual grupo de botões você quer customizar.\n\n"
                "**Como funciona:** em cada campo você cola `emoji texto` "
                "(ex: `🎮 Editar`) ou um emoji custom no formato "
                "`<:nome:id> Texto`.\n"
                "Para deixar **só emoji**, escreva apenas ele.\n"
                "Pra usar emoji custom do seu servidor, digite no chat "
                "`\\:nome_emoji:` e copie o código que aparecer."
            ),
            color=cor_global(config),
        )
        await interaction.response.send_message(embed=embed, view=PersonalizarPainelView(), ephemeral=True)


class _BtnPublicar(Button):
    def __init__(self, painel_msg):
        super().__init__(style=discord.ButtonStyle.success, row=1)
        aplicar_btn_admin(self, "publicar")
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


class EditarPainelEmbedModal(Modal):
    """Modal compartilhado para editar título/banner/thumbnail dos painéis (streamer e mediador)."""
    def __init__(self, key: str, default_titulo: str, alvo: str):
        super().__init__(title=f"Editar Embed — {alvo.title()}")
        self.key  = key   # "painel_streamer_embed" ou "painel_mediador_embed"
        self.alvo = alvo  # "streamer" ou "mediador"

        config = carregar_config()
        cur = config.get("global", {}).get(key, {})

        self.titulo = TextInput(
            label="Título",
            default=cur.get("titulo") or default_titulo,
            max_length=100,
            required=True,
        )
        self.banner = TextInput(
            label="Banner (URL — vazio = usar global)",
            default=cur.get("banner", ""),
            required=False,
            max_length=300,
        )
        self.thumbnail = TextInput(
            label="Thumbnail (URL — vazio = usar global)",
            default=cur.get("thumbnail", ""),
            required=False,
            max_length=300,
        )
        self.add_item(self.titulo)
        self.add_item(self.banner)
        self.add_item(self.thumbnail)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        cur = config["global"].setdefault(self.key, {})
        cur["titulo"]    = self.titulo.value.strip()
        cur["banner"]    = self.banner.value.strip()
        cur["thumbnail"] = self.thumbnail.value.strip()
        salvar_config(config)

        # Atualiza o painel correspondente
        if self.alvo == "streamer":
            await _atualizar_painel_streamer(config)
        else:
            await _atualizar_painel_mediador(None, config)

        await interaction.response.send_message(
            f"✅ Embed do painel **{self.alvo}** atualizado!",
            ephemeral=True,
        )


class PainelMediadorView(View):
    def __init__(self, painel_med_msg=None):
        super().__init__(timeout=None)
        self.add_item(_BtnCadastrarPix(painel_med_msg))
        self.add_item(_BtnEntrarFilaMediador(painel_med_msg))
        self.add_item(_BtnSairFilaMediador(painel_med_msg))
        self.add_item(_BtnLimparFilaMediador(painel_med_msg))
        self.add_item(_BtnEditarEmbedMediador(painel_med_msg))


class _BtnEditarEmbedMediador(Button):
    def __init__(self, painel_med_msg=None):
        super().__init__(label="Editar Embed", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="med_editar_embed")
        self.painel_med_msg = painel_med_msg

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Apenas administradores podem editar o embed.", ephemeral=True); return
        await interaction.response.send_modal(
            EditarPainelEmbedModal("painel_mediador_embed", "🤝  Painel de Mediadores", alvo="mediador")
        )


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
        # ── LOG: mediador entrou ──
        emb = _log_embed("mediador", "🤝  Mediador Entrou na Fila",
                         f"<@{uid}> entrou na fila de mediadores.\n**Posição:** #{len(fila)}",
                         autor=interaction.user)
        await _send_log(interaction.guild, "mediador", embed=emb, config=config)


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
        # ── LOG: mediador saiu ──
        emb = _log_embed("mediador", "🤝  Mediador Saiu da Fila",
                         f"<@{uid}> saiu da fila de mediadores.",
                         autor=interaction.user)
        await _send_log(interaction.guild, "mediador", embed=emb, config=config)


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
        self.cancelado              = False
        self.add_item(_BtnConfirmar(self))
        self.add_item(_BtnCancelarAposta(self))

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

        # ── LOG: confirmadas ───────────────────────────────────
        try:
            cat_l, modo_l = split_chave(self.ch)
            log_emb = _log_embed(
                "confirmadas",
                "✅  Partida Confirmada",
                f"**Categoria:** {EMOJI_CATEGORIA.get(cat_l,'')} {cat_l}\n"
                f"**Modo:** {EMOJI_MODO.get(modo_l,'')} {modo_l}\n"
                f"**Valor:** {self.preco['valor']}\n"
                f"**Canal:** {self.canal_partida.mention}\n"
                f"**Mediador:** " + (f"<@{self.mediador_uid}>" if self.mediador_uid else "`Sem mediador`") + "\n"
                f"**Jogadores:**\n" + "\n".join(f"• <@{u}>" for u in self.jogadores),
            )
            await _send_log(interaction.guild, "confirmadas", embed=log_emb)
        except Exception as e:
            print(f"⚠️ log confirmadas: {e}")

    async def on_timeout(self):
        if self.finalizado or self.cancelado:
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


class _BtnCancelarAposta(Button):
    def __init__(self, pv):
        super().__init__(label="❌  Cancelar Aposta", style=discord.ButtonStyle.danger)
        self.pv = pv

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        # Permissões: jogador da partida, ADM ou mediador podem cancelar
        eh_jogador  = uid in self.pv.jogadores
        eh_mediador = self.pv.mediador_uid and uid == str(self.pv.mediador_uid)
        eh_adm      = False
        if self.pv.cargo_adm_id and isinstance(interaction.user, discord.Member):
            eh_adm = any(r.id == self.pv.cargo_adm_id for r in interaction.user.roles)
        if self.pv.cargo_mediador_id and isinstance(interaction.user, discord.Member):
            if any(r.id == self.pv.cargo_mediador_id for r in interaction.user.roles):
                eh_mediador = True

        if not (eh_jogador or eh_mediador or eh_adm):
            await interaction.response.send_message("⚠️ Você não pode cancelar esta partida.", ephemeral=True); return

        if self.pv.cancelado or self.pv.finalizado:
            await interaction.response.send_message("⚠️ Esta partida já foi encerrada.", ephemeral=True); return

        self.pv.cancelado  = True
        self.pv.finalizado = True
        self.pv.stop()

        # Devolve o mediador à fila se ele tinha sido puxado
        if self.pv.mediador_uid:
            try:
                cfg = carregar_config()
                fila = cfg["global"].setdefault("fila_mediador", [])
                if self.pv.mediador_uid not in fila:
                    fila.insert(0, self.pv.mediador_uid)
                    salvar_config(cfg)
                await _atualizar_painel_mediador(None, cfg)
            except Exception:
                pass

        embed = discord.Embed(
            title="❌ Aposta Cancelada",
            description=f"Cancelada por <@{interaction.user.id}>.\n\nO canal será fechado em 15 segundos.",
            color=discord.Color.red(),
        )
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            try:
                await interaction.response.send_message(embed=embed)
            except Exception:
                pass

        # ── LOG: cancelada ─────────────────────────────────────
        try:
            cat_l, modo_l = split_chave(self.pv.ch)
            log_emb = _log_embed(
                "cancelada",
                "❌  Aposta Cancelada",
                f"**Cancelada por:** <@{interaction.user.id}>\n"
                f"**Categoria:** {EMOJI_CATEGORIA.get(cat_l,'')} {cat_l}\n"
                f"**Modo:** {EMOJI_MODO.get(modo_l,'')} {modo_l}\n"
                f"**Valor:** {self.pv.preco['valor']}\n"
                f"**Canal:** {self.pv.canal_partida.mention}\n"
                f"**Mediador:** " + (f"<@{self.pv.mediador_uid}>" if self.pv.mediador_uid else "`Sem mediador`") + "\n"
                f"**Jogadores:**\n" + "\n".join(f"• <@{u}>" for u in self.pv.jogadores),
                autor=interaction.user,
            )
            await _send_log(interaction.guild, "cancelada", embed=log_emb)
        except Exception as e:
            print(f"⚠️ log cancelada: {e}")

        try:
            await asyncio.sleep(15)
            await self.pv.canal_partida.delete(reason="Aposta cancelada por usuário")
        except Exception:
            pass


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

    # ── LOG: partida iniciada ───────────────────────────────
    log_emb = _log_embed(
        "iniciadas",
        "📥  Partida Iniciada",
        f"**Categoria:** {EMOJI_CATEGORIA.get(cat,'')} {cat}\n"
        f"**Modo:** {EMOJI_MODO.get(modo,'')} {modo}\n"
        f"**Valor:** {preco['valor']}\n"
        f"**Canal:** {canal.mention}\n"
        f"**Jogadores:**\n" + "\n".join(f"• <@{u}>" for u in jogadores),
    )
    await _send_log(guild, "iniciadas", embed=log_emb, config=config)

    # ── LOG: mediador puxado ────────────────────────────────
    if mediador_uid:
        med_emb = _log_embed(
            "mediador",
            "🤝  Mediador Puxado",
            f"**Mediador:** <@{mediador_uid}>\n"
            f"**Partida:** {canal.mention}\n"
            f"**Valor:** {preco['valor']} — {display(ch)}",
        )
        await _send_log(guild, "mediador", embed=med_emb, config=config)


# ──────────────────────────────────────────────
# FILAS ON / OFF — mensagem rotativa a cada 5 minutos
# ──────────────────────────────────────────────

_filas_on_msgs: dict[int, int] = {}


async def _atualizar_status_filas(guild: discord.Guild, config: dict):
    """Atualiza imediatamente as mensagens de status FILAS ON/OFF nos canais publicados."""
    ativas = config.get("global", {}).get("filas_ativas", True)
    texto = "@everyone\n# 🟢 FILAS ON" if ativas else "# 🛑 FILAS OFF\n-# entrada desabilitada"

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
        texto = "@everyone\n# 🟢 FILAS ON" if ativas else "# 🛑 FILAS OFF\n-# entrada desabilitada"
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
            msg = await canal.send(embed=embed, view=view)
            _filas_msg_ids[preco["id"]] = (canal.id, msg.id)
            publicados.append(f"{EMOJI_CATEGORIA[split_chave(ch)[0]]} **{display(ch)}** `{preco['valor']}` → {canal.mention}")
            await asyncio.sleep(0.3)

    # Status (FILAS ON / OFF) em cada canal único
    ativas = config.get("global", {}).get("filas_ativas", True)
    texto  = "@everyone\n# 🟢 FILAS ON" if ativas else "# 🛑 FILAS OFF\n-# entrada desabilitada"
    canais_notif: set = set()
    for ch in ALL_MODOS:
        cid = config[ch].get("canal_id")
        if cid and cid not in canais_notif:
            canal = interaction.guild.get_channel(cid)
            if canal:
                msg = await canal.send(texto)
                _filas_on_msgs[cid] = msg.id
                canais_notif.add(cid)

    await interaction.followup.send("# ✅ Filas publicadas!\n\n" + "\n".join(publicados), ephemeral=True)


# ──────────────────────────────────────────────
# Fila do Streamer
# ──────────────────────────────────────────────

_painel_streamer_msgs: dict[int, int] = {}   # {channel_id: message_id}

MODOS_STREAMER = ["1v1", "2v2", "3v3", "4v4"]


def _streamer_pode_controlar(member: discord.Member, config: dict) -> bool:
    """True se for admin/permissão máxima OU o próprio streamer."""
    if usuario_pode_admin(member, config):
        return True
    s_id = config.get("global", {}).get("streamer", {}).get("user_id")
    return bool(s_id) and str(member.id) == str(s_id)


def build_embed_painel_streamer(config: dict) -> discord.Embed:
    g = config.get("global", {})
    s = g.get("streamer", {})
    streamer_uid = s.get("user_id")
    aberta       = s.get("aberta", False)

    custom     = g.get("painel_streamer_embed", {})
    titulo     = custom.get("titulo")     or "🎮 Fila Contra 5 INVIT 3 NO PIX! | #1K"
    subtitulo  = custom.get("subtitulo")  or ""
    instrucoes = custom.get("instrucoes") or "• Clique em **Jogar Contra** para abrir um desafio.\n• O desafio expira automaticamente se não for aceito."
    info_jogo  = custom.get("info_jogo")  or ""

    # Texto resumido do título sem emoji para usar no corpo (igual à imagem)
    titulo_sem_emoji = re.sub(r'^\s*(<a?:\w+:\d+>|[^\w\s])\s*', '', titulo).strip() or titulo

    streamer_link = f"`{titulo_sem_emoji}`"

    descricao_lines = [
        f"• **Streamer:** {streamer_link}",
    ]
    if info_jogo:
        descricao_lines.append(f"• {info_jogo}")
    if subtitulo:
        descricao_lines.append("")
        descricao_lines.append(subtitulo)

    descricao = "\n".join(descricao_lines)

    embed = discord.Embed(
        title=titulo,
        description=descricao,
        color=cor_global(config),
    )

    # Status (com bolinha colorida igual à imagem)
    if aberta:
        status_txt = "🟢 Situação: AO VIVO"
        status_curto = "AO VIVO"
    else:
        status_txt = "🔴 Situação: OFFLINE"
        status_curto = "OFFLINE"
    embed.add_field(name="Status", value=status_txt, inline=False)

    # Como funciona
    embed.add_field(name="Como funciona", value=instrucoes, inline=False)

    # Footer estilo da imagem: título • status • data
    from datetime import datetime
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
    embed.set_footer(text=f"{titulo_sem_emoji} • {status_curto} • {data_atual}")

    thumb  = custom.get("thumbnail") or g.get("embed_global", {}).get("thumbnail", "")
    banner = custom.get("banner")    or g.get("embed_global", {}).get("banner", "")
    if thumb:
        embed.set_thumbnail(url=thumb)
    if banner:
        embed.set_image(url=banner)
    return embed


async def _atualizar_painel_streamer(config: dict):
    """Atualiza todas as mensagens de painel do streamer publicadas."""
    for canal_id, msg_id in list(_painel_streamer_msgs.items()):
        try:
            canal = bot.get_channel(canal_id)
            if not canal:
                continue
            msg = await canal.fetch_message(msg_id)
            await msg.edit(embed=build_embed_painel_streamer(config), view=PainelStreamerView())
        except Exception:
            pass


class PainelStreamerView(View):
    """Painel público — apenas 2 botões visíveis: Jogar Contra + Engrenagem (config)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(_BtnStreamerJogarContra())
        self.add_item(_BtnStreamerGear())


class _BtnStreamerJogarContra(Button):
    def __init__(self):
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {}).get("jogar_contra", {})
        super().__init__(
            label=b.get("label") or "Jogar Contra",
            emoji=to_discord_emoji(b.get("emoji") or "🚪"),
            style=discord.ButtonStyle.success,
            custom_id="streamer_jogar_contra",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        s = config["global"]["streamer"]
        if not s.get("aberta"):
            await interaction.response.send_message("🛑 A fila do streamer está **fechada** no momento.", ephemeral=True); return
        if not s.get("user_id"):
            await interaction.response.send_message("⚠️ Nenhum streamer foi definido ainda.", ephemeral=True); return
        if str(interaction.user.id) == str(s["user_id"]):
            await interaction.response.send_message("⚠️ Você é o **streamer**, não pode desafiar a si mesmo!", ephemeral=True); return

        uid = str(interaction.user.id)
        if uid in s["fila"]:
            await interaction.response.send_message(
                f"⚠️ Você já está na fila! Posição: **#{s['fila'].index(uid)+1}**",
                view=_AcoesJogadorView(),
                ephemeral=True,
            ); return

        s["fila"].append(uid)
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message(
            f"✅ Desafio aberto! Você está na posição **#{len(s['fila'])}**.",
            view=_AcoesJogadorView(),
            ephemeral=True,
        )


class _BtnStreamerGear(Button):
    def __init__(self):
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {}).get("gear", {})
        super().__init__(
            label=b.get("label") or "",
            emoji=to_discord_emoji(b.get("emoji") or "⚙️"),
            style=discord.ButtonStyle.secondary,
            custom_id="streamer_gear",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        # Streamer ou admin → painel completo. Usuário comum → ações de jogador.
        if _streamer_pode_controlar(interaction.user, config):
            await interaction.response.send_message(
                "⚙️ **Configurações do painel do streamer**\nUse os botões abaixo para gerenciar a fila e personalizar o painel.",
                view=PainelGearStreamerView(),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ℹ️ Use os botões abaixo:",
                view=_AcoesJogadorView(),
                ephemeral=True,
            )


class _AcoesJogadorView(View):
    """Ações ephemeral para jogador comum (sair da fila)."""
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(_BtnStreamerSair())


class PainelGearStreamerView(View):
    """Painel ephemeral aberto pela engrenagem — apenas streamer/admin."""
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(_BtnStreamerProximo())
        self.add_item(_BtnStreamerAbrirFechar())
        self.add_item(_BtnStreamerSair())
        self.add_item(_BtnStreamerConfigurar())
        self.add_item(_BtnEditarEmbedStreamer())
        self.add_item(_BtnEditarBotoesStreamer())


class _BtnEditarEmbedStreamer(Button):
    def __init__(self):
        super().__init__(label="Editar Embed", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="streamer_editar_embed", row=2)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Apenas administradores podem editar o embed.", ephemeral=True); return
        await interaction.response.send_modal(EditarEmbedStreamerModal())


class _BtnEditarBotoesStreamer(Button):
    def __init__(self):
        super().__init__(label="Editar Botões", emoji="🎨", style=discord.ButtonStyle.secondary, custom_id="streamer_editar_botoes", row=2)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Apenas administradores podem editar os botões.", ephemeral=True); return
        await interaction.response.send_message(
            "🎨 **Personalizar botões do painel do streamer**\nEscolha o que deseja editar:",
            view=EditarBotoesStreamerMenuView(),
            ephemeral=True,
        )


class EditarEmbedStreamerModal(Modal):
    """Modal para editar o embed do painel do streamer (estilo da imagem)."""
    def __init__(self):
        super().__init__(title="Editar Embed — Streamer")
        cur = carregar_config().get("global", {}).get("painel_streamer_embed", {})
        self.titulo = TextInput(
            label="Título (cabeçalho do painel)",
            default=cur.get("titulo") or "🎮 Fila Contra 5 INVIT 3 NO PIX! | #1K",
            max_length=200,
            required=True,
            placeholder="🎮 Fila Contra 5 INVIT 3 NO PIX! | #1K",
        )
        self.subtitulo = TextInput(
            label="Subtítulo (ex: SO FREE FIRE)",
            default=cur.get("subtitulo", ""),
            required=False,
            max_length=200,
            placeholder="SO FREE FIRE",
        )
        self.info_jogo = TextInput(
            label="Linha de info (ex: Jogando contra...)",
            default=cur.get("info_jogo", ""),
            required=False,
            max_length=300,
            placeholder="Jogando contra membros em live, tiktok @olipesick",
        )
        self.instrucoes = TextInput(
            label="Como funciona (use • para bullets)",
            default=cur.get("instrucoes") or "• Clique em **Jogar Contra** para abrir um desafio.\n• O desafio expira automaticamente se não for aceito.",
            required=False,
            max_length=1000,
            style=discord.TextStyle.paragraph,
        )
        self.thumbnail = TextInput(
            label="Thumbnail (URL — vazio = global)",
            default=cur.get("thumbnail", ""),
            required=False,
            max_length=500,
            placeholder="https://...png",
        )
        for it in (self.titulo, self.subtitulo, self.info_jogo, self.instrucoes, self.thumbnail):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        cur = config["global"].setdefault("painel_streamer_embed", {})
        cur["titulo"]     = self.titulo.value.strip()
        cur["subtitulo"]  = self.subtitulo.value.strip()
        cur["info_jogo"]  = self.info_jogo.value.strip()
        cur["instrucoes"] = self.instrucoes.value.strip()
        cur["thumbnail"]  = self.thumbnail.value.strip()
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message("✅ Embed do painel do streamer atualizado!", ephemeral=True)


class EditarBotoesStreamerMenuView(View):
    """Menu de seleção do que personalizar (botão principal ou administrativos)."""
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_BtnAbrirEditarPrincipal())
        self.add_item(_BtnAbrirEditarAdmin())


class _BtnAbrirEditarPrincipal(Button):
    def __init__(self):
        super().__init__(label="Botão Principal + Engrenagem", emoji="🎮", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditarBotoesStreamerPrincipalModal())


class _BtnAbrirEditarAdmin(Button):
    def __init__(self):
        super().__init__(label="Botões Administrativos", emoji="🛠️", style=discord.ButtonStyle.secondary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditarBotoesStreamerAdminModal())


class EditarBotoesStreamerPrincipalModal(Modal):
    """Personaliza o botão 'Jogar Contra' (visível no painel) e o ícone da engrenagem."""
    def __init__(self):
        super().__init__(title="Editar Botão Jogar Contra")
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {})
        def cur(k, de, dl):
            x = b.get(k, {})
            return f"{x.get('emoji') or de} {x.get('label') or dl}".strip()

        self.b_jogar = TextInput(
            label="Botão Jogar Contra (emoji + texto)",
            default=cur("jogar_contra", "🚪", "Jogar Contra"),
            max_length=100, required=True,
            placeholder="🚪 Jogar Contra  ou  <:emoji:id> Texto",
        )
        self.b_gear = TextInput(
            label="Engrenagem — só emoji (ex: ⚙️)",
            default=(b.get("gear", {}) or {}).get("emoji") or "⚙️",
            max_length=20, required=True,
            placeholder="⚙️  ou  <:emoji:id>",
        )
        self.add_item(self.b_jogar)
        self.add_item(self.b_gear)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        b = config["global"].setdefault("painel_streamer_botoes", {})
        e_j, l_j = parse_emoji_label(self.b_jogar.value)
        b["jogar_contra"] = {"emoji": e_j, "label": l_j}
        b["gear"] = {"emoji": self.b_gear.value.strip() or "⚙️", "label": ""}
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message("✅ Botão **Jogar Contra** e engrenagem atualizados!", ephemeral=True)


class EditarBotoesStreamerAdminModal(Modal):
    """Personaliza os botões internos (sair, próximo, abrir/fechar) do painel ephemeral."""
    def __init__(self):
        super().__init__(title="Editar Botões Administrativos")
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {})
        def cur(k, de, dl):
            x = b.get(k, {})
            return f"{x.get('emoji') or de} {x.get('label') or dl}"

        self.b_sair    = TextInput(label="Botão Sair da Fila",     default=cur("sair",    "❌", "Sair da Fila"),    max_length=100, required=True, placeholder="❌ Sair da Fila")
        self.b_proximo = TextInput(label="Botão Chamar Próximo",   default=cur("proximo", "🎮", "Chamar Próximo"),  max_length=100, required=True, placeholder="🎮 Chamar Próximo")
        self.b_toggle  = TextInput(label="Botão Abrir/Fechar Fila",default=cur("toggle",  "🔁", "Abrir/Fechar"),    max_length=100, required=True, placeholder="🔁 Abrir/Fechar")
        for it in (self.b_sair, self.b_proximo, self.b_toggle):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        b = config["global"].setdefault("painel_streamer_botoes", {})
        for k, txt in (("sair", self.b_sair.value),
                       ("proximo", self.b_proximo.value),
                       ("toggle", self.b_toggle.value)):
            e, lbl = parse_emoji_label(txt)
            b[k] = {"emoji": e, "label": lbl}
        salvar_config(config)
        await interaction.response.send_message("✅ Botões administrativos atualizados!", ephemeral=True)


class _BtnStreamerSair(Button):
    def __init__(self):
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {}).get("sair", {})
        super().__init__(
            label=b.get("label") or "Sair da Fila",
            emoji=to_discord_emoji(b.get("emoji") or "❌"),
            style=discord.ButtonStyle.danger,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        s = config["global"]["streamer"]
        uid = str(interaction.user.id)
        if uid not in s.get("fila", []):
            await interaction.response.send_message("⚠️ Você não está na fila!", ephemeral=True); return
        s["fila"].remove(uid)
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message("✅ Você saiu da fila.", ephemeral=True)


class _BtnStreamerProximo(Button):
    def __init__(self):
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {}).get("proximo", {})
        super().__init__(
            label=b.get("label") or "Chamar Próximo",
            emoji=to_discord_emoji(b.get("emoji") or "🎮"),
            style=discord.ButtonStyle.primary,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not _streamer_pode_controlar(interaction.user, config):
            await interaction.response.send_message("❌ Apenas o **streamer** ou **admin** podem chamar o próximo.", ephemeral=True); return

        s = config["global"]["streamer"]
        modo = s.get("modo", "1v1")
        n_pull = JOGADORES_MODO[modo] // 2

        if len(s.get("fila", [])) < 1:
            await interaction.response.send_message("⚠️ A fila está vazia!", ephemeral=True); return

        chamados = s["fila"][:n_pull]
        s["fila"] = s["fila"][n_pull:]
        salvar_config(config)
        await _atualizar_painel_streamer(config)

        await interaction.response.defer(ephemeral=True)
        await _criar_canal_partida_streamer(interaction.guild, config, s["user_id"], chamados, modo)
        await interaction.followup.send(
            f"✅ Chamado(s) **{len(chamados)}** jogador(es) — canal de partida criado!",
            ephemeral=True,
        )


class _BtnStreamerAbrirFechar(Button):
    def __init__(self):
        b = carregar_config().get("global", {}).get("painel_streamer_botoes", {}).get("toggle", {})
        super().__init__(
            label=b.get("label") or "Abrir/Fechar",
            emoji=to_discord_emoji(b.get("emoji") or "🔁"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not _streamer_pode_controlar(interaction.user, config):
            await interaction.response.send_message("❌ Apenas o **streamer** ou **admin** podem alterar o status.", ephemeral=True); return
        s = config["global"]["streamer"]
        s["aberta"] = not s.get("aberta", False)
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message(
            "🟢 Fila **ABERTA**!" if s["aberta"] else "🛑 Fila **FECHADA**.",
            ephemeral=True,
        )


class _BtnStreamerConfigurar(Button):
    def __init__(self):
        super().__init__(label="Configurar Streamer/Modo", emoji="🎥", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Apenas administradores podem configurar.", ephemeral=True); return
        await interaction.response.send_message(
            "⚙️ **Configurar fila do streamer**",
            view=ConfigStreamerView(),
            ephemeral=True,
        )


class ConfigStreamerView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_StreamerUserSelect())
        self.add_item(_StreamerModoSelect())
        self.add_item(_BtnLimparFilaStreamer())


class _StreamerUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="🎥 Selecione o streamer...", min_values=0, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["streamer"]["user_id"] = self.values[0].id if self.values else None
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        txt = f"✅ Streamer definido: {self.values[0].mention}" if self.values else "✅ Streamer removido."
        await interaction.response.send_message(txt, ephemeral=True)


class _StreamerModoSelect(Select):
    def __init__(self):
        opts = [discord.SelectOption(label=m, value=m, emoji=EMOJI_MODO[m]) for m in MODOS_STREAMER]
        super().__init__(placeholder="🎮 Selecione o modo...", options=opts, min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["streamer"]["modo"] = self.values[0]
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message(f"✅ Modo definido: **{self.values[0]}**", ephemeral=True)


class _BtnLimparFilaStreamer(Button):
    def __init__(self):
        super().__init__(label="Limpar Fila", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        config["global"]["streamer"]["fila"] = []
        salvar_config(config)
        await _atualizar_painel_streamer(config)
        await interaction.response.send_message("🗑️ Fila do streamer limpa.", ephemeral=True)


async def _criar_canal_partida_streamer(guild: discord.Guild, config: dict, streamer_uid, chamados: list, modo: str):
    """Cria canal de partida do streamer com permissões para o streamer + chamados."""
    cat_id = config.get("global", {}).get("categoria_id")
    categoria = guild.get_channel(cat_id) if cat_id else None

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}

    streamer_member = guild.get_member(int(streamer_uid)) if streamer_uid else None
    if streamer_member:
        overwrites[streamer_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    for uid in chamados:
        m = guild.get_member(int(uid))
        if m:
            overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    nome = f"streamer-{modo}-{gerar_id()[:6]}"
    try:
        canal = await guild.create_text_channel(name=nome, category=categoria, overwrites=overwrites, reason="Fila do streamer")
    except discord.Forbidden:
        return None

    embed = discord.Embed(
        title="🎬  Partida do Streamer!",
        description=(
            f"**🎥 Streamer:** <@{streamer_uid}>\n"
            f"**🎮 Modo:** {EMOJI_MODO.get(modo, '🎮')} **{modo}**\n\n"
            f"**👥 Desafiantes:**\n" + "\n".join(f"• <@{u}>" for u in chamados)
        ),
        color=0x9B59B6,
    )
    embed.set_footer(text="Boa partida! Quando terminar, use /vencedor para definir o vencedor e fechar o canal.")

    streamer_member_obj = guild.get_member(int(streamer_uid)) if streamer_uid else None
    if streamer_member_obj and streamer_member_obj.display_avatar:
        embed.set_thumbnail(url=streamer_member_obj.display_avatar.url)

    mentions = " ".join([f"<@{streamer_uid}>"] + [f"<@{u}>" for u in chamados])
    await canal.send(content=mentions, embed=embed)
    return canal


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
        # Painel streamer persistente
        self.add_view(PainelStreamerView())
        # Painel de tickets persistente (botões de abrir + botão de fechar)
        self.add_view(PainelTicketsPublicoView(config))
        self.add_view(_FecharTicketView())
        # IMPORTANTE: não sincronizar globalmente para evitar comandos duplicados
        # (a sincronização será feita por servidor em on_ready / on_guild_join)

    async def on_ready(self):
        print(f"🤖 Bot conectado como {self.user} (ID: {self.user.id})")
        # Apaga comandos globais registrados na Discord (sem mexer na árvore local)
        # — isto remove duplicatas que apareciam por terem sido registradas como
        # global E por servidor em versões anteriores do bot.
        try:
            await self.http.bulk_upsert_global_commands(self.application_id, [])
            print("🧹 Comandos globais antigos removidos (anti-duplicação).")
        except Exception as e:
            print(f"⚠️ Falha ao limpar comandos globais: {e}")

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

    async def on_member_join(self, member: discord.Member):
        # Autorole — dá um cargo automaticamente para novos membros
        if member.bot:
            return
        try:
            cfg = carregar_config()
            cargo_id = cfg.get("global", {}).get("cargo_autorole_id")
            if not cargo_id:
                return
            cargo = member.guild.get_role(cargo_id)
            if not cargo:
                print(f"⚠️ Autorole: cargo {cargo_id} não encontrado em '{member.guild.name}'.")
                return
            await member.add_roles(cargo, reason="Autorole — novo membro")
            print(f"🎟️ Autorole aplicado: {cargo.name} → {member} ({member.guild.name})")
        except discord.Forbidden:
            print(f"⚠️ Autorole: sem permissão para dar cargo em '{member.guild.name}'. Verifique a hierarquia e a permissão 'Gerenciar Cargos'.")
        except Exception as e:
            print(f"⚠️ Autorole: erro ao aplicar cargo: {e}")

    async def on_member_remove(self, member: discord.Member):
        # Log: alguém saiu (ou foi removido) do servidor
        try:
            criado_em = discord.utils.format_dt(member.created_at, style="R") if member.created_at else "—"
            entrou_em = discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "—"
            cargos = [r.mention for r in getattr(member, "roles", []) if r.name != "@everyone"]
            cargos_txt = ", ".join(cargos) if cargos else "`Nenhum`"
            emb = _log_embed(
                "saiu_servidor",
                "👋  Membro Saiu do Servidor",
                f"**Usuário:** {member.mention} (`{member}`)\n"
                f"**Entrou no servidor:** {entrou_em}\n"
                f"**Conta criada:** {criado_em}\n"
                f"**Cargos:** {cargos_txt}",
                autor=member,
            )
            if member.display_avatar:
                emb.set_thumbnail(url=member.display_avatar.url)
            await _send_log(member.guild, "saiu_servidor", embed=emb)
        except Exception as e:
            print(f"⚠️ log saiu_servidor: {e}")


bot = MyBot()


# ──────────────────────────────────────────────
# Permission check para slash commands
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# Personalizar Painel — view + modais
# ──────────────────────────────────────────────

class PersonalizarPainelView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(_BtnAbrirPainelPrincipalModal())
        self.add_item(_BtnAbrirPainelModoModal())
        self.add_item(_BtnAbrirPainelExtrasModal())


class _BtnAbrirPainelPrincipalModal(Button):
    def __init__(self):
        super().__init__(label="Botões: Painel Principal", emoji="🏠", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PersonalizarPainelPrincipalModal())


class _BtnAbrirPainelModoModal(Button):
    def __init__(self):
        super().__init__(label="Botões: Painel do Modo", emoji="🎮", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PersonalizarPainelModoModal())


class _BtnAbrirPainelExtrasModal(Button):
    def __init__(self):
        super().__init__(label="Botões: Visualizar / Preços / Voltar", emoji="🧰", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PersonalizarPainelExtrasModal())


def _btn_input(label: str, key: str) -> TextInput:
    info = get_admin_btn(key)
    default = f"{info['emoji']} {info['label']}".strip() if info['label'] else (info['emoji'] or "")
    return TextInput(
        label=label[:45],
        default=default,
        max_length=100, required=True,
        placeholder="emoji texto  ou  <:nome:id> Texto",
    )


def _salvar_btn(config: dict, key: str, valor: str, label_required: bool = True):
    pab = config["global"].setdefault("painel_admin_botoes", {})
    valor = valor.strip()
    if not valor:
        return
    # Se o usuário só colou um emoji (sem texto), mantém só o emoji.
    e, lbl = parse_emoji_label(valor)
    # Caso parse_emoji_label devolva texto inteiro como label sem emoji custom,
    # detecta também o caso "só emoji unicode" pra não duplicar.
    if not label_required and (e == "🎮" and lbl == valor):
        # O parse não achou emoji; assume que tudo é emoji unicode.
        pab[key] = {"emoji": valor, "label": ""}
        return
    pab[key] = {"emoji": e, "label": lbl}


class PersonalizarPainelPrincipalModal(Modal):
    def __init__(self):
        super().__init__(title="Painel Principal")
        self.b1 = _btn_input("Config Geral",         "config_geral")
        self.b2 = _btn_input("Embed Global",         "embed_global")
        self.b3 = _btn_input("Filas ON (quando OFF)", "filas_on")
        self.b4 = _btn_input("Filas OFF (quando ON)", "filas_off")
        self.b5 = _btn_input("Publicar Filas",       "publicar")
        for it in (self.b1, self.b2, self.b3, self.b4, self.b5):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        _salvar_btn(config, "config_geral", self.b1.value)
        _salvar_btn(config, "embed_global", self.b2.value)
        _salvar_btn(config, "filas_on",     self.b3.value)
        _salvar_btn(config, "filas_off",    self.b4.value)
        _salvar_btn(config, "publicar",     self.b5.value)
        salvar_config(config)
        await interaction.response.send_message("✅ Botões do painel principal atualizados! Reabra o painel pra ver.", ephemeral=True)


class PersonalizarPainelModoModal(Modal):
    def __init__(self):
        super().__init__(title="Painel do Modo")
        self.b1 = _btn_input("Título/Banner",  "editar_embed")
        self.b2 = _btn_input("Editar Botões",  "editar_botoes")
        self.b3 = _btn_input("Texto/Layout",   "texto_layout")
        self.b4 = _btn_input("Placeholders",   "placeholders")
        self.b5 = _btn_input("Personalizar Painel (botão)", "personalizar")
        for it in (self.b1, self.b2, self.b3, self.b4, self.b5):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        _salvar_btn(config, "editar_embed",  self.b1.value)
        _salvar_btn(config, "editar_botoes", self.b2.value)
        _salvar_btn(config, "texto_layout",  self.b3.value)
        _salvar_btn(config, "placeholders",  self.b4.value)
        _salvar_btn(config, "personalizar",  self.b5.value)
        salvar_config(config)
        await interaction.response.send_message("✅ Botões do painel do modo atualizados! Reabra o painel pra ver.", ephemeral=True)


class PersonalizarPainelExtrasModal(Modal):
    def __init__(self):
        super().__init__(title="Visualizar / Preços / Voltar")
        self.b1 = _btn_input("Visualizar", "visualizar")
        self.b2 = _btn_input("Preços",     "precos")
        self.b3 = _btn_input("Voltar",     "voltar")
        for it in (self.b1, self.b2, self.b3):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        if not usuario_pode_admin(interaction.user, config):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True); return
        _salvar_btn(config, "visualizar", self.b1.value)
        _salvar_btn(config, "precos",     self.b2.value)
        _salvar_btn(config, "voltar",     self.b3.value)
        salvar_config(config)
        await interaction.response.send_message("✅ Botões auxiliares atualizados! Reabra o painel pra ver.", ephemeral=True)


async def _check_pode_admin(interaction: discord.Interaction) -> bool:
    config = carregar_config()
    if usuario_pode_admin(interaction.user, config):
        return True
    await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
    return False


# ──────────────────────────────────────────────
# SISTEMA DE TICKETS
# ──────────────────────────────────────────────

ESTILOS_BTN = {
    "primary":   discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success":   discord.ButtonStyle.success,
    "danger":    discord.ButtonStyle.danger,
}
ESTILOS_PT = {
    "primary":   "azul",
    "secondary": "cinza",
    "success":   "verde",
    "danger":    "vermelho",
}
ESTILOS_PT_REV = {v: k for k, v in ESTILOS_PT.items()}


def _parse_estilo(txt: str) -> str:
    t = (txt or "").strip().lower()
    if t in ESTILOS_BTN:
        return t
    if t in ESTILOS_PT_REV:
        return ESTILOS_PT_REV[t]
    return "primary"


def cor_tickets(config: dict) -> int:
    cor = config["global"]["tickets"]["embed"].get("cor", "")
    if cor:
        return parse_cor(cor)
    return cor_global(config)


def build_embed_tickets_publico(config: dict) -> discord.Embed:
    e = config["global"]["tickets"]["embed"]
    embed = discord.Embed(
        title=e.get("titulo") or "🎫 Central de Tickets",
        description=e.get("descricao") or "Clique num botão abaixo pra abrir um ticket.",
        color=cor_tickets(config),
    )
    if e.get("thumbnail"):
        embed.set_thumbnail(url=e["thumbnail"])
    if e.get("banner"):
        embed.set_image(url=e["banner"])
    return embed


def build_embed_tickets_admin(config: dict) -> discord.Embed:
    tk = config["global"]["tickets"]
    embed = discord.Embed(
        title="🎫 Painel de Tickets — Configuração",
        description=(
            f"**Título do painel:** {tk['embed'].get('titulo') or '*(vazio)*'}\n"
            f"**Botões cadastrados:** `{len(tk['botoes'])}` / 25\n\n"
            "Use os botões abaixo pra editar o painel, adicionar/remover botões, "
            "e publicar a mensagem num canal."
        ),
        color=cor_tickets(config),
    )
    if tk["botoes"]:
        linhas = []
        for i, b in enumerate(tk["botoes"], 1):
            canal = f"<#{b['canal_id']}>" if b.get("canal_id") else "*(sem canal)*"
            linhas.append(f"`{i}.` {b.get('emoji','')} **{b.get('label') or '—'}** → {canal}")
        embed.add_field(name="Botões", value="\n".join(linhas), inline=False)
    return embed


# ─── Modais de edição ────────────────────────────

class EditarEmbedTicketsModal(Modal, title="Editar Embed do Painel"):
    def __init__(self, painel_msg):
        super().__init__()
        config = carregar_config()
        e = config["global"]["tickets"]["embed"]
        self.painel_msg = painel_msg
        self.titulo    = TextInput(label="Título",    default=e.get("titulo", ""),    max_length=200, required=False)
        self.descricao = TextInput(label="Descrição", default=e.get("descricao", ""), style=discord.TextStyle.paragraph, max_length=2000, required=False)
        self.thumbnail = TextInput(label="Thumbnail (URL)", default=e.get("thumbnail", ""), max_length=400, required=False)
        self.banner    = TextInput(label="Banner (URL)",    default=e.get("banner", ""),    max_length=400, required=False)
        self.cor       = TextInput(label="Cor (hex, ex: #00BFFF) — vazio usa global",
                                   default=e.get("cor", ""), max_length=10, required=False)
        for it in (self.titulo, self.descricao, self.thumbnail, self.banner, self.cor):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        e = config["global"]["tickets"]["embed"]
        e["titulo"]    = self.titulo.value.strip()
        e["descricao"] = self.descricao.value
        e["thumbnail"] = self.thumbnail.value.strip()
        e["banner"]    = self.banner.value.strip()
        e["cor"]       = self.cor.value.strip()
        salvar_config(config)
        _registrar_view_tickets()
        await interaction.response.edit_message(embed=build_embed_tickets_admin(config), view=PainelTicketsAdminView(self.painel_msg))


class AdicionarBotaoTicketModal(Modal, title="Adicionar Botão de Ticket"):
    def __init__(self, painel_msg):
        super().__init__()
        self.painel_msg = painel_msg
        self.emoji_label = TextInput(
            label="Emoji + Texto do botão",
            placeholder="ex: 🎫 Suporte  ou  <:nome:id> Compras",
            max_length=80, required=True,
        )
        self.estilo = TextInput(
            label="Cor do botão",
            placeholder="azul / cinza / verde / vermelho",
            default="azul", max_length=20, required=False,
        )
        self.mensagem = TextInput(
            label="Mensagem inicial (use {user} pra mencionar)",
            style=discord.TextStyle.paragraph,
            default="Olá {user}! Descreva sua questão e aguarde um atendente.",
            max_length=1500, required=True,
        )
        for it in (self.emoji_label, self.estilo, self.mensagem):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        emoji, label = parse_emoji_label(self.emoji_label.value)
        novo = {
            "id": gerar_id(),
            "emoji": emoji,
            "label": label,
            "estilo": _parse_estilo(self.estilo.value),
            "canal_id": None,
            "mensagem_inicial": self.mensagem.value,
            "cargo_atendimento_id": None,
        }
        await interaction.response.send_message(
            f"✅ Botão **{emoji} {label}** criado! Agora escolha em **qual canal** ele abrirá os tickets:",
            view=_EscolherCanalTicketView(novo, self.painel_msg, modo="adicionar"),
            ephemeral=True,
        )


class EditarBotaoTicketModal(Modal, title="Editar Botão de Ticket"):
    def __init__(self, btn: dict, painel_msg):
        super().__init__()
        self.btn_id = btn["id"]
        self.painel_msg = painel_msg
        emj_lbl = f"{btn.get('emoji','')} {btn.get('label','')}".strip()
        self.emoji_label = TextInput(
            label="Emoji + Texto do botão",
            default=emj_lbl, max_length=80, required=True,
        )
        self.estilo = TextInput(
            label="Cor do botão",
            placeholder="azul / cinza / verde / vermelho",
            default=ESTILOS_PT.get(btn.get("estilo", "primary"), "azul"),
            max_length=20, required=False,
        )
        self.mensagem = TextInput(
            label="Mensagem inicial (use {user} pra mencionar)",
            style=discord.TextStyle.paragraph,
            default=btn.get("mensagem_inicial", ""),
            max_length=1500, required=True,
        )
        for it in (self.emoji_label, self.estilo, self.mensagem):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        config = carregar_config()
        for b in config["global"]["tickets"]["botoes"]:
            if b["id"] == self.btn_id:
                e, l = parse_emoji_label(self.emoji_label.value)
                b["emoji"] = e
                b["label"] = l
                b["estilo"] = _parse_estilo(self.estilo.value)
                b["mensagem_inicial"] = self.mensagem.value
                break
        salvar_config(config)
        _registrar_view_tickets()
        await interaction.response.edit_message(embed=build_embed_tickets_admin(config), view=PainelTicketsAdminView(self.painel_msg))


# ─── Selects auxiliares ──────────────────────────

class _EscolherCanalTicketView(View):
    """Após criar/editar botão de ticket, pergunta o canal de destino."""
    def __init__(self, btn: dict, painel_msg, modo: str = "adicionar"):
        super().__init__(timeout=300)
        self.btn = btn
        self.painel_msg = painel_msg
        self.modo = modo  # "adicionar" ou "editar_canal"
        self.add_item(self._CanalSelect(self))

    class _CanalSelect(ChannelSelect):
        def __init__(self, parent):
            super().__init__(channel_types=[discord.ChannelType.text], placeholder="Escolha o canal onde os tickets serão abertos…", min_values=1, max_values=1)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            canal = self.values[0]
            config = carregar_config()
            if self.parent.modo == "adicionar":
                self.parent.btn["canal_id"] = canal.id
                config["global"]["tickets"]["botoes"].append(self.parent.btn)
                salvar_config(config)
                _registrar_view_tickets()
                await interaction.response.edit_message(
                    content=f"✅ Botão adicionado e vinculado a {canal.mention}!",
                    view=None,
                )
            else:  # editar_canal
                for b in config["global"]["tickets"]["botoes"]:
                    if b["id"] == self.parent.btn["id"]:
                        b["canal_id"] = canal.id
                        break
                salvar_config(config)
                _registrar_view_tickets()
                await interaction.response.edit_message(
                    content=f"✅ Canal alterado para {canal.mention}!",
                    view=None,
                )


class _SelectBotaoTicket(Select):
    def __init__(self, painel_msg, acao: str):
        config = carregar_config()
        botoes = config["global"]["tickets"]["botoes"]
        opts = []
        for b in botoes[:25]:
            label = (b.get("label") or "—")[:80]
            desc = f"{ESTILOS_PT.get(b.get('estilo','primary'),'azul')} • " + (f"<#{b['canal_id']}>" if b.get("canal_id") else "sem canal")
            try:
                opts.append(discord.SelectOption(label=label, description=desc[:90], value=b["id"], emoji=to_discord_emoji(b.get("emoji","")) if b.get("emoji") else None))
            except Exception:
                opts.append(discord.SelectOption(label=label, description=desc[:90], value=b["id"]))
        if not opts:
            opts = [discord.SelectOption(label="(nenhum botão)", value="__none__")]
        placeholder = {
            "editar":      "Selecione um botão pra editar (texto/cor/mensagem)…",
            "canal":       "Selecione um botão pra trocar o canal de destino…",
            "remover":     "Selecione um botão pra remover…",
        }[acao]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=opts)
        self.painel_msg = painel_msg
        self.acao = acao

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__none__":
            await interaction.response.send_message("❌ Nenhum botão cadastrado ainda.", ephemeral=True); return
        config = carregar_config()
        btn = next((b for b in config["global"]["tickets"]["botoes"] if b["id"] == self.values[0]), None)
        if not btn:
            await interaction.response.send_message("❌ Botão não encontrado.", ephemeral=True); return

        if self.acao == "editar":
            await interaction.response.send_modal(EditarBotaoTicketModal(btn, self.painel_msg))
        elif self.acao == "canal":
            await interaction.response.send_message(
                f"Escolha o novo canal para **{btn.get('emoji','')} {btn.get('label','')}**:",
                view=_EscolherCanalTicketView(btn, self.painel_msg, modo="editar_canal"),
                ephemeral=True,
            )
        elif self.acao == "remover":
            config["global"]["tickets"]["botoes"] = [b for b in config["global"]["tickets"]["botoes"] if b["id"] != self.values[0]]
            salvar_config(config)
            _registrar_view_tickets()
            await interaction.response.edit_message(
                embed=build_embed_tickets_admin(config),
                view=PainelTicketsAdminView(self.painel_msg),
            )


# ─── View principal de admin ─────────────────────

class PainelTicketsAdminView(View):
    def __init__(self, painel_msg=None):
        super().__init__(timeout=600)
        self.painel_msg = painel_msg
        self.add_item(_BtnTkEditarEmbed(painel_msg))
        self.add_item(_BtnTkAdicionarBotao(painel_msg))
        self.add_item(_BtnTkEditarBotao(painel_msg))
        self.add_item(_BtnTkTrocarCanal(painel_msg))
        self.add_item(_BtnTkRemoverBotao(painel_msg))
        self.add_item(_BtnTkVisualizar())
        self.add_item(_BtnTkPublicar(painel_msg))


class _BtnTkEditarEmbed(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Editar Embed", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditarEmbedTicketsModal(self.painel_msg))


class _BtnTkAdicionarBotao(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Adicionar Botão", emoji="➕", style=discord.ButtonStyle.success, row=0)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if len(config["global"]["tickets"]["botoes"]) >= 25:
            await interaction.response.send_message("❌ Limite de 25 botões atingido.", ephemeral=True); return
        await interaction.response.send_modal(AdicionarBotaoTicketModal(self.painel_msg))


class _BtnTkEditarBotao(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Editar Botão", emoji="🔧", style=discord.ButtonStyle.secondary, row=0)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        view = View(timeout=120)
        view.add_item(_SelectBotaoTicket(self.painel_msg, "editar"))
        await interaction.response.send_message("Escolha qual botão editar:", view=view, ephemeral=True)


class _BtnTkTrocarCanal(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Trocar Canal", emoji="📍", style=discord.ButtonStyle.secondary, row=1)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        view = View(timeout=120)
        view.add_item(_SelectBotaoTicket(self.painel_msg, "canal"))
        await interaction.response.send_message("Escolha qual botão terá o canal trocado:", view=view, ephemeral=True)


class _BtnTkRemoverBotao(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Remover Botão", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        view = View(timeout=120)
        view.add_item(_SelectBotaoTicket(self.painel_msg, "remover"))
        await interaction.response.send_message("Escolha qual botão remover:", view=view, ephemeral=True)


class _BtnTkVisualizar(Button):
    def __init__(self):
        super().__init__(label="Visualizar", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        await interaction.response.send_message(
            content="**Pré-visualização do painel:**",
            embed=build_embed_tickets_publico(config),
            view=PainelTicketsPublicoView(config),
            ephemeral=True,
        )


class _BtnTkPublicar(Button):
    def __init__(self, painel_msg):
        super().__init__(label="Publicar Painel", emoji="🚀", style=discord.ButtonStyle.success, row=2)
        self.painel_msg = painel_msg
    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        if not config["global"]["tickets"]["botoes"]:
            await interaction.response.send_message("❌ Adicione pelo menos um botão antes de publicar.", ephemeral=True); return
        view = View(timeout=120)
        view.add_item(_PublicarTicketsCanalSelect())
        await interaction.response.send_message("Escolha o canal onde o painel de tickets será publicado:", view=view, ephemeral=True)


class _PublicarTicketsCanalSelect(ChannelSelect):
    def __init__(self):
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Canal onde publicar o painel…", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        canal = self.values[0]
        canal_real = interaction.guild.get_channel(canal.id)
        if not isinstance(canal_real, discord.TextChannel):
            await interaction.response.send_message("❌ Canal inválido.", ephemeral=True); return
        try:
            await canal_real.send(embed=build_embed_tickets_publico(config), view=PainelTicketsPublicoView(config))
            await interaction.response.edit_message(content=f"✅ Painel publicado em {canal_real.mention}!", view=None)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Sem permissão pra enviar mensagem nesse canal.", ephemeral=True)


# ─── View pública (que aparece pros usuários) ────

class PainelTicketsPublicoView(View):
    def __init__(self, config: dict | None = None):
        super().__init__(timeout=None)
        if config is None:
            config = carregar_config()
        for i, b in enumerate(config["global"]["tickets"]["botoes"][:25]):
            self.add_item(_BtnAbrirTicket(b, row=i // 5))


class _BtnAbrirTicket(Button):
    def __init__(self, btn_data: dict, row: int = 0):
        emj = btn_data.get("emoji") or None
        super().__init__(
            label=(btn_data.get("label") or None),
            emoji=to_discord_emoji(emj) if emj else None,
            style=ESTILOS_BTN.get(btn_data.get("estilo", "primary"), discord.ButtonStyle.primary),
            custom_id=f"ticket_btn_{btn_data['id']}",
            row=row,
        )
        self.btn_id = btn_data["id"]

    async def callback(self, interaction: discord.Interaction):
        config = carregar_config()
        btn = next((b for b in config["global"]["tickets"]["botoes"] if b["id"] == self.btn_id), None)
        if not btn:
            await interaction.response.send_message("❌ Esse botão não está mais disponível.", ephemeral=True); return
        canal_id = btn.get("canal_id")
        canal = interaction.guild.get_channel(canal_id) if canal_id else None
        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message("❌ Canal de destino não configurado.", ephemeral=True); return

        await interaction.response.defer(ephemeral=True, thinking=True)

        nome_user = interaction.user.name.lower().replace(" ", "-")[:40]
        nome_topico = f"ticket-{nome_user}"

        try:
            topico = await canal.create_thread(
                name=nome_topico,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440,
                reason=f"Ticket aberto por {interaction.user} via botão {btn.get('label','')}",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Não tenho permissão pra criar tópicos privados nesse canal.", ephemeral=True); return
        except discord.HTTPException:
            # Fallback: tópico público
            try:
                topico = await canal.create_thread(
                    name=nome_topico,
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=1440,
                )
            except Exception as e:
                await interaction.followup.send(f"❌ Erro ao abrir o ticket: `{e}`", ephemeral=True); return

        try:
            await topico.add_user(interaction.user)
        except Exception:
            pass

        msg_inicial = (btn.get("mensagem_inicial") or "Olá {user}!").format(user=interaction.user.mention)
        try:
            await topico.send(content=msg_inicial, view=_FecharTicketView())
        except Exception:
            pass

        await interaction.followup.send(f"✅ Seu ticket foi aberto: {topico.mention}", ephemeral=True)

        # ── LOG: ticket aberto ──
        log_emb = _log_embed(
            "ticket",
            "🎫  Ticket Aberto",
            f"**Usuário:** {interaction.user.mention}\n"
            f"**Tipo:** {btn.get('label','—')}\n"
            f"**Tópico:** {topico.mention}",
            autor=interaction.user,
        )
        await _send_log(interaction.guild, "ticket", embed=log_emb)


def _registrar_view_tickets():
    """Re-registra a view pública de tickets pra que novos botões funcionem em mensagens já publicadas."""
    try:
        bot.add_view(PainelTicketsPublicoView(carregar_config()))
    except Exception:
        pass


class _FecharTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_fechar")
    async def fechar(self, interaction: discord.Interaction, button: Button):
        canal = interaction.channel
        if not isinstance(canal, discord.Thread):
            await interaction.response.send_message("❌ Esse botão só funciona dentro de um ticket.", ephemeral=True); return
        await interaction.response.send_message(f"🔒 Ticket fechado por {interaction.user.mention}. Arquivando em 5s…")
        # ── LOG: ticket fechado ──
        try:
            log_emb = _log_embed(
                "ticket",
                "🎫  Ticket Fechado",
                f"**Fechado por:** {interaction.user.mention}\n"
                f"**Tópico:** {canal.mention}\n"
                f"**Nome:** `{canal.name}`",
                autor=interaction.user,
            )
            await _send_log(interaction.guild, "ticket", embed=log_emb)
        except Exception as e:
            print(f"⚠️ log ticket: {e}")
        await asyncio.sleep(5)
        try:
            await canal.edit(archived=True, locked=True)
        except Exception:
            pass


class _LimparConfirmView(View):
    def __init__(self, autor_id: int, canal: discord.TextChannel):
        super().__init__(timeout=60)
        self.autor_id = autor_id
        self.canal = canal

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Só quem usou o comando pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Apagar tudo", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🧹 Apagando mensagens...", view=self)

        total = 0
        try:
            # purge() apaga até 14 dias em massa; mensagens mais antigas precisam delete() individual.
            while True:
                deletadas = await self.canal.purge(limit=100, bulk=True)
                total += len(deletadas)
                if len(deletadas) < 100:
                    break
            # Tenta apagar mensagens antigas restantes (>14 dias) uma a uma
            async for msg in self.canal.history(limit=None):
                try:
                    await msg.delete()
                    total += 1
                except Exception:
                    pass
        except discord.Forbidden:
            try:
                await interaction.followup.send("❌ Não tenho permissão de **Gerenciar Mensagens** neste canal.", ephemeral=True)
            except Exception:
                pass
            return
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Erro ao apagar: `{e}`", ephemeral=True)
            except Exception:
                pass
            return

        try:
            aviso = await self.canal.send(f"# 🧹 Canal limpo!\n-# {total} mensagem(ns) apagada(s) por {interaction.user.mention}.")
            await asyncio.sleep(5)
            await aviso.delete()
        except Exception:
            pass

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❎ Limpeza cancelada.", view=self)


@bot.tree.command(name="limpar", description="Apaga TODAS as mensagens deste canal (com confirmação)")
async def limpar(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    canal = interaction.channel
    if not isinstance(canal, discord.TextChannel):
        await interaction.response.send_message("❌ Esse comando só funciona em canais de texto.", ephemeral=True)
        return

    perms = canal.permissions_for(interaction.guild.me) if interaction.guild else None
    if perms and not perms.manage_messages:
        await interaction.response.send_message(
            "❌ Eu preciso da permissão **Gerenciar Mensagens** neste canal pra apagar.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="⚠️ Confirmar limpeza",
        description=(
            f"Você está prestes a apagar **TODAS as mensagens** de {canal.mention}.\n\n"
            "Essa ação é **irreversível**. Tem certeza?"
        ),
        color=discord.Color.red(),
    )
    await interaction.response.send_message(
        embed=embed,
        view=_LimparConfirmView(interaction.user.id, canal),
        ephemeral=True,
    )


@bot.tree.command(name="painel_tickets", description="Abre o painel de configuração do sistema de tickets")
async def painel_tickets(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    view = PainelTicketsAdminView()
    await interaction.response.send_message(embed=build_embed_tickets_admin(config), view=view, ephemeral=True)
    msg = await interaction.original_response()
    view.painel_msg = msg
    for child in view.children:
        if hasattr(child, "painel_msg"):
            child.painel_msg = msg


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


@bot.tree.command(name="painel_streamer", description="Publica o painel da fila do streamer no canal atual")
async def painel_streamer(interaction: discord.Interaction):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    embed  = build_embed_painel_streamer(config)
    view   = PainelStreamerView()
    msg    = await interaction.channel.send(embed=embed, view=view)
    _painel_streamer_msgs[interaction.channel.id] = msg.id
    await interaction.response.send_message("✅ Painel da fila do streamer publicado!", ephemeral=True)


@bot.tree.command(name="streamer", description="Define quem é o streamer da fila")
@app_commands.describe(streamer="Usuário que será o streamer (deixe vazio para limpar)")
async def streamer_cmd(interaction: discord.Interaction, streamer: discord.Member = None):
    if not await _check_pode_admin(interaction):
        return
    config = carregar_config()
    config["global"]["streamer"]["user_id"] = streamer.id if streamer else None
    salvar_config(config)
    await _atualizar_painel_streamer(config)
    if streamer:
        await interaction.response.send_message(f"✅ Streamer definido: {streamer.mention}", ephemeral=True)
    else:
        await interaction.response.send_message("✅ Streamer removido.", ephemeral=True)


@bot.tree.command(name="vencedor", description="Define o vencedor da partida e fecha o canal em 10 segundos")
@app_commands.describe(vencedor="Jogador que venceu a partida (digite o nick para buscar)")
async def vencedor_cmd(interaction: discord.Interaction, vencedor: discord.Member):
    config = carregar_config()
    if not (usuario_pode_admin(interaction.user, config) or usuario_e_mediador(interaction.user, config)):
        await interaction.response.send_message(
            "❌ Apenas **administradores**, **permissão máxima** ou **mediadores** podem definir o vencedor.",
            ephemeral=True,
        ); return

    canal = interaction.channel
    if not isinstance(canal, discord.TextChannel) or not (canal.name.startswith("partida-") or canal.name.startswith("streamer-")):
        await interaction.response.send_message(
            "❌ Use este comando **dentro de um canal de partida** (`partida-…` ou `streamer-…`).",
            ephemeral=True,
        ); return

    eh_streamer = canal.name.startswith("streamer-")

    embed = discord.Embed(
        title="🏆  Vencedor da Partida!",
        description=f"# 🥇 {vencedor.mention}\n\n**Parabéns pela vitória!** 🎉",
        color=0xF1C40F,
    )
    embed.set_thumbnail(url=vencedor.display_avatar.url)
    embed.add_field(name="📛 Vencedor",      value=f"`{vencedor.display_name}`",  inline=True)
    embed.add_field(name="👤 Definido por",  value=interaction.user.mention,       inline=True)
    embed.add_field(name="⏳ Canal fecha em", value="**10 segundos**",             inline=True)
    embed.set_footer(text="GG! Até a próxima partida 🎮")

    banner = config.get("global", {}).get("embed_global", {}).get("banner", "")
    if banner:
        embed.set_image(url=banner)

    await interaction.response.send_message(embed=embed)

    # ── LOG: finalizada (sempre) e vitorias_ws (se foi partida do streamer) ──
    try:
        log_emb = _log_embed(
            "finalizadas",
            "🏆  Partida Finalizada",
            f"**Vencedor:** {vencedor.mention} (`{vencedor.display_name}`)\n"
            f"**Canal:** `{canal.name}`\n"
            f"**Definido por:** {interaction.user.mention}",
            autor=interaction.user,
        )
        log_emb.set_thumbnail(url=vencedor.display_avatar.url)
        await _send_log(interaction.guild, "finalizadas", embed=log_emb)

        if eh_streamer:
            ws_emb = _log_embed(
                "vitorias_ws",
                "🎬  Vitória contra o Streamer!",
                f"**Vencedor:** {vencedor.mention} (`{vencedor.display_name}`)\n"
                f"**Canal:** `{canal.name}`\n"
                f"**Definido por:** {interaction.user.mention}",
                autor=interaction.user,
            )
            ws_emb.set_thumbnail(url=vencedor.display_avatar.url)
            await _send_log(interaction.guild, "vitorias_ws", embed=ws_emb)
    except Exception as e:
        print(f"⚠️ log finalizadas/ws: {e}")

    await asyncio.sleep(10)
    try:
        await canal.delete(reason=f"Partida finalizada — vencedor: {vencedor}")
    except Exception:
        pass


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
