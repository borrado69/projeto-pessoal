#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OBSCURITY
Roguelike voxel 3D isométrico: o herói enfrenta inimigos pelas salas da masmorra.
O herói pode andar sozinho (automático) ou ser controlado por você (manual).
Combate em tempo real ESTILO DARK SOULS (sem turnos): ande livre (WASD/setas), ATAQUE LEVE = J | ATAQUE FORTE = L |
ROLAR = K / ESPAÇO (imortal no começo da rolagem) | TAB troca o alvo. HABILIDADE = Q (R = 2ª magia da maga). Arqueira e maga atacam de longe. Cada ação gasta FÔLEGO; os monstros te
perseguem e avisam o golpe antes de bater. Clique esquerdo = atacar, direito = rolar.
Precisa de Python 3 + pygame (pip install pygame). Tecla C abre as configurações.
CENÁRIO INICIAL: toda partida começa no VILAREJO PENUMBRA (sem inimigos); o poço no fim da trilha leva ao andar 1.
FERREIRO: na vila há uma forja. Chegue perto do ferreiro e aperte E (ou clique no aviso) para gastar ouro melhorando
ARMA (mais dano e crítico) e ARMADURA (bloqueio e corações). O ouro e os níveis ficam gravados no seu save.
MERCADO: a barraca da vila tem um mercador. Chegue perto e aperte E (ou clique no aviso): na aba COMPRAR você gasta ouro em equipamento
(vai para a mochila) e na aba VENDER troca os itens da mochila por ouro. A mochila agora fica gravada no save entre as partidas.
ALDEÕES: os moradores andam pela vila, param para conversar e viram o corpo para o herói quando ele chega perto.
LOOT E INVENTÁRIO: salas do tesouro e chefes dropam itens (comum a lendário) que vão para a MOCHILA. Tecla I (ou clique nos
slots do HUD) abre o inventário: selecione, EQUIPE, DESEQUIPE ou VENDA (V). O equipamento vale só na descida atual; a mochila fica no save.
MENU: START (jogar um save) e CRIAR SAVE. São 5 slots (obscurity_saves.json): cada um guarda nome, classe e recorde.
"""
import heapq
import json
import math
import os
import queue
import socket
import time
import random
import struct
import sys
import threading
import traceback

import pygame

W, H = 960, 640
TW, TH, ZH = 60, 30, 30       # largura/altura do tile e altura de 1 voxel
N = 9                         # sala N x N
WALL_H = 3
OX, OY = W // 2, 178
FPS = 60
PLAT_X, PLAT_H = 4.0, 1.5     # plataforma (2º andar) das salas duplas
HEAL_EVERY = 3                # a vida só é restaurada a cada 3 andares
MAX_HEARTS = 6                # limite de vidas
HERO_SCALE = 1.35             # escala com que o herói é desenhado (zumbi e esqueleto usam a mesma)

# ------------------------------------------------------------- configurações
try:
    CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obscurity_config.json")
except NameError:
    CONFIG_PATH = "obscurity_config.json"
DEFAULT_CFG = {
    "mode": "auto",        # "auto" = o herói anda sozinho | "manual" = você controla (WASD / setas)
    "speed": 1.0,          # velocidade do herói (0.6 .. 1.6)
    "music": True,
    "music_vol": 1.0,      # 0.0 .. 1.0
    "sfx": True,           # efeitos sonoros
    "shake": True,         # tremor de tela nos golpes
    "mp_addr": "",         # último endereço usado no MULTIPLAYER
    "public_host": "",     # IP/domínio da máquina que roda os 3 servidores públicos (vazio = automático)
    "public_host_last": "",  # último host público que respondeu (guardado automaticamente)
    "username": "",        # nome de usuário único (conta online)
    "token": "",           # chave secreta da conta (gerada sozinha; não compartilhe)
    "auto_host": False,    # True = ao abrir o jogo, já sobe os 3 servidores públicos e abre as portas no roteador (UPnP)
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        _p = CONFIG_PATH if os.path.exists(CONFIG_PATH) else CONFIG_PATH.replace("obscurity_", "masmorra_")   # arquivo antigo
        with open(_p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, dv in DEFAULT_CFG.items():
                v = data.get(k)
                if isinstance(dv, bool):
                    if isinstance(v, bool):
                        cfg[k] = v
                elif isinstance(dv, float):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        cfg[k] = float(v)
                elif isinstance(v, str):
                    cfg[k] = v
    except Exception:
        pass
    if cfg["mode"] not in ("auto", "manual"):
        cfg["mode"] = "auto"
    cfg["speed"] = min(1.6, max(0.6, cfg["speed"]))
    cfg["music_vol"] = min(1.0, max(0.0, cfg["music_vol"]))
    return cfg


def save_cfg(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ------------------------------------------------------------------ saves (5 slots)
NSLOTS = 5
NAME_MAX = 12
MENU_PHASES = ("title", "slots", "create", "mp_menu", "username")     # telas de menu (a partida não roda nelas)
try:
    SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obscurity_saves.json")
except NameError:
    SAVE_PATH = "obscurity_saves.json"


def load_saves():
    """Lê os 5 slots. Cada slot é None (vazio) ou {"name", "hero", "best", "runs"}."""
    saves = [None] * NSLOTS
    try:
        _p = SAVE_PATH if os.path.exists(SAVE_PATH) else SAVE_PATH.replace("obscurity_", "masmorra_")   # arquivo antigo
        with open(_p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for i, sv in enumerate(data[:NSLOTS]):
                if isinstance(sv, dict) and isinstance(sv.get("name"), str) and isinstance(sv.get("hero"), str):
                    best, runs = sv.get("best", 1), sv.get("runs", 0)
                    def _n(k, hi=10 ** 9):
                        v = sv.get(k, 0)
                        return min(hi, v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
                    saves[i] = {"name": sv["name"][:NAME_MAX],
                                "hero": sv["hero"],
                                "best": best if isinstance(best, int) and best >= 1 else 1,
                                "runs": runs if isinstance(runs, int) and runs >= 0 else 0,
                                "gold": _n("gold"), "weapon": _n("weapon", 5), "armor": _n("armor", 5)}
                    if sv.get("race") in RACE_IDS:
                        saves[i]["race"] = sv["race"]
                    saves[i]["bag"] = clean_bag(sv.get("bag"))
                    _a = sv.get("attrs")
                    if isinstance(_a, dict):                      # atributos do personagem (opcional: saves antigos não têm)
                        saves[i]["attrs"] = {k: min(ATTR_MAX, max(1, _a[k])) for k in ATTR_KEYS
                                             if isinstance(_a.get(k), int) and not isinstance(_a.get(k), bool)}
    except Exception:
        pass
    return saves


def write_saves(saves):
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(saves, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ----------------------------------------------------------------- utilidades
def shade(c, f):
    return (max(0, min(255, int(c[0] * f))),
            max(0, min(255, int(c[1] * f))),
            max(0, min(255, int(c[2] * f))))


def mix(c, t, other=(255, 255, 255)):
    t = max(0.0, min(1.0, t))
    return (int(c[0] + (other[0] - c[0]) * t),
            int(c[1] + (other[1] - c[1]) * t),
            int(c[2] + (other[2] - c[2]) * t))


def proj(x, y, z, cam=(0, 0)):
    return (OX + cam[0] + (x - y) * TW / 2,
            OY + cam[1] + (x + y) * TH / 2 - z * ZH)


def stair_h(x):
    """Altura do degrau k (0..4) da escada das salas duplas: 1.25, 1.0, 0.75, 0.5, 0.25."""
    return 1.25 - 0.25 * max(0, min(4, int((x - PLAT_X) / 0.2)))


def ground(x, y, duplo):
    """Altura do chão em (x, y). Salas duplas têm plataforma + escada de 5 degraus."""
    if not duplo:
        return 0.0
    if x < PLAT_X:
        return PLAT_H
    if 3.0 <= y <= 5.0 and x < PLAT_X + 1.0:
        return stair_h(x)
    return 0.0


_TEX = random.Random(1234)


def draw_box(surf, x, y, z, w, d, h, color, cam=(0, 0), outline=True, g=0.0, tex=0.0, bevel=False, ao=False):
    """Voxel/caixa com 3 faces visíveis (topo, esquerda, direita).
    g > 0 desenha a grade de mini-voxels sobre as faces.
    tex > 0 dá a cada mini-voxel um tom levemente diferente (pedra); bevel realça as quinas;
    ao escurece a base das faces laterais (oclusão ambiente)."""
    p = lambda a, b, c: proj(a, b, c, cam)
    ct, cl, cr = shade(color, 1.15), shade(color, 0.82), shade(color, 0.60)
    top = [p(x, y, z + h), p(x + w, y, z + h), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    left = [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    right = [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x + w, y, z + h)]
    nx = ny = nz = 1
    if g > 0:
        nx, ny, nz = max(1, int(round(w / g))), max(1, int(round(d / g))), max(1, int(round(h / g)))
    sx_, sy_, sz_ = w / nx, d / ny, h / nz
    if tex > 0 and g > 0:
        rnd = _TEX.random
        zt = z + h
        for i in range(nx):
            for j in range(ny):
                q = [p(x + i * sx_, y + j * sy_, zt), p(x + (i + 1) * sx_, y + j * sy_, zt),
                     p(x + (i + 1) * sx_, y + (j + 1) * sy_, zt), p(x + i * sx_, y + (j + 1) * sy_, zt)]
                pygame.draw.polygon(surf, shade(ct, 1 + (rnd() * 2 - 1) * tex), q)
        for i in range(nx):
            for k in range(nz):
                q = [p(x + i * sx_, y + d, z + k * sz_), p(x + (i + 1) * sx_, y + d, z + k * sz_),
                     p(x + (i + 1) * sx_, y + d, z + (k + 1) * sz_), p(x + i * sx_, y + d, z + (k + 1) * sz_)]
                pygame.draw.polygon(surf, shade(cl, 1 + (rnd() * 2 - 1) * tex), q)
        for j in range(ny):
            for k in range(nz):
                q = [p(x + w, y + j * sy_, z + k * sz_), p(x + w, y + (j + 1) * sy_, z + k * sz_),
                     p(x + w, y + (j + 1) * sy_, z + (k + 1) * sz_), p(x + w, y + j * sy_, z + (k + 1) * sz_)]
                pygame.draw.polygon(surf, shade(cr, 1 + (rnd() * 2 - 1) * tex), q)
    else:
        pygame.draw.polygon(surf, ct, top)
        pygame.draw.polygon(surf, cl, left)
        pygame.draw.polygon(surf, cr, right)
    if g > 0:
        k_ = 0.93 if tex > 0 else 0.90
        lt, ll, lr = shade(ct, k_), shade(cl, k_), shade(cr, k_)
        for i in range(1, nx):
            xx = x + i * sx_
            pygame.draw.line(surf, lt, p(xx, y, z + h), p(xx, y + d, z + h))
            pygame.draw.line(surf, ll, p(xx, y + d, z), p(xx, y + d, z + h))
        for j in range(1, ny):
            yy = y + j * sy_
            pygame.draw.line(surf, lt, p(x, yy, z + h), p(x + w, yy, z + h))
            pygame.draw.line(surf, lr, p(x + w, yy, z), p(x + w, yy, z + h))
        for k in range(1, nz):
            zz = z + k * sz_
            pygame.draw.line(surf, ll, p(x, y + d, zz), p(x + w, y + d, zz))
            pygame.draw.line(surf, lr, p(x + w, y, zz), p(x + w, y + d, zz))
    if ao and h > 0.3:
        band = min(0.2, h * 0.3)
        pygame.draw.polygon(surf, shade(cl, 0.80), [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + band), p(x, y + d, z + band)])
        pygame.draw.polygon(surf, shade(cr, 0.80), [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + band), p(x + w, y, z + band)])
    if bevel:
        pygame.draw.line(surf, mix(ct, 0.30), p(x, y + d, z + h), p(x + w, y + d, z + h), 2)
        pygame.draw.line(surf, mix(ct, 0.16), p(x + w, y, z + h), p(x + w, y + d, z + h), 2)
        pygame.draw.line(surf, mix(cl, 0.14), p(x + w, y + d, z), p(x + w, y + d, z + h))
    if outline:
        e = shade(color, 0.36)
        for poly in (top, left, right):
            pygame.draw.polygon(surf, e, poly, 1)


def wbox(surf, ax, v, a, la, z, h, t, color, off=0.0, g=0.0, cam=(0, 0), **kw):
    """Caixa colada na parede. ax='x': parede em x=0 (corre ao longo de y); ax='y': parede em y=0.
    v+a = início ao longo da parede, la = comprimento, t = espessura, off = distância da parede."""
    if ax == "x":
        draw_box(surf, off, v + a, z, t, la, h, color, cam, g=g, **kw)
    else:
        draw_box(surf, v + a, off, z, la, t, h, color, cam, g=g, **kw)


# ------------------------------------------------------------------ paletas
PALS = [  # DARK FANTASY: chão A, chão B, parede A, parede B, fundo, bandeira
    ((92, 88, 90), (76, 72, 76), (68, 66, 78), (54, 52, 64), (5, 5, 9), (132, 20, 34)),        # cripta de pedra
    ((64, 86, 66), (52, 70, 56), (62, 74, 68), (48, 60, 54), (3, 8, 6), (168, 126, 36)),       # pântano maldito
    ((100, 62, 54), (80, 48, 44), (88, 46, 44), (70, 36, 38), (14, 4, 4), (186, 96, 20)),      # fornalha infernal
    ((96, 116, 140), (80, 98, 122), (84, 102, 126), (66, 82, 106), (5, 9, 18), (56, 86, 160)), # catacumba gelada
    ((86, 64, 104), (70, 52, 88), (68, 52, 88), (54, 40, 72), (9, 4, 15), (150, 40, 126)),     # santuário profano
]


def _liquid_cell(s, rng, x, y, liq, kind, axis, stone):
    """Uma célula de rio no cenário em cache: água (um degrau abaixo do piso), vau raso com pedras ou ponte."""
    deep, light = liq["deep"], liq["light"]
    if kind == "water":
        draw_box(s, x, y, -0.6, 1, 1, 0.30, mix(deep, 0.10 + 0.16 * rng.random(), light), outline=False)
    elif kind == "ford":
        draw_box(s, x, y, -0.6, 1, 1, 0.48, mix(deep, 0.45 + 0.10 * rng.random(), light), outline=False)
        for _ in range(3):
            draw_box(s, x + rng.uniform(0.08, 0.62), y + rng.uniform(0.08, 0.62), -0.14,
                     rng.uniform(0.2, 0.3), rng.uniform(0.18, 0.28), 0.16, shade(stone, rng.uniform(0.6, 0.9)),
                     g=0.1, tex=0.05)
    else:   # ponte (só vigas baixas: o herói nunca fica "atrás" de uma peça desenhada no cenário)
        draw_box(s, x, y, -0.6, 1, 1, 0.30, mix(deep, 0.10, light), outline=False)
        plank, beam = liq["ponte"]
        if axis == "y":      # rio corre ao longo de y: atravessa-se ao longo de x
            draw_box(s, x, y, -0.12, 1.0, 0.07, 0.2, beam)
            for k in range(5):
                draw_box(s, x + 0.02 + 0.2 * k, y + 0.04, -0.12, 0.17, 0.92, 0.12, shade(plank, 0.9 + 0.1 * (k % 2)))
            draw_box(s, x, y + 0.93, -0.12, 1.0, 0.07, 0.2, beam)
        else:
            draw_box(s, x, y, -0.12, 0.07, 1.0, 0.2, beam)
            for k in range(5):
                draw_box(s, x + 0.04, y + 0.02 + 0.2 * k, -0.12, 0.92, 0.17, 0.12, shade(plank, 0.9 + 0.1 * (k % 2)))
            draw_box(s, x + 0.93, y, -0.12, 0.07, 1.0, 0.2, beam)


def _cave_extras(s, rng, lay, pal, wet):
    """Detalhes de caverna nas paredes (tudo com no máx. 0.24 de profundidade, o herói nunca encosta)."""
    fa, fb, wa, wb, _, acc = pal

    def touch(ax, v, la):
        for j in range(max(0, int(v)), min(N - 1, int(v + la)) + 1):
            if ((0, j) if ax == "x" else (j, 0)) in wet:
                return True
        return False

    for ax in ("x", "y"):
        for _ in range(rng.randint(3, 5)):           # pedras salientes na base
            v, la = rng.uniform(0.2, N - 1.4), rng.uniform(0.5, 1.1)
            if touch(ax, v, la):
                continue
            hh = rng.uniform(0.3, 0.75)
            wbox(s, ax, v, 0, la, 0.0, hh, 0.22, shade(wa, rng.uniform(0.95, 1.3)), g=0.2, tex=0.08)
            wbox(s, ax, v, 0.1 * la, la * 0.6, hh, hh * 0.4, 0.14, shade(wa, rng.uniform(1.15, 1.4)), g=0.15, tex=0.06)
        for _ in range(rng.randint(5, 8)):           # estalactites penduradas no topo
            v = rng.uniform(0.2, N - 0.6)
            top = WALL_H - 0.02
            c = shade(wb, rng.uniform(1.0, 1.35))
            wbox(s, ax, v, 0, 0.30, top - 0.32, 0.32, 0.22, c, g=0.12, tex=0.06)
            wbox(s, ax, v, 0.06, 0.18, top - 0.62, 0.30, 0.14, shade(c, 1.08), g=0.1)
            wbox(s, ax, v, 0.11, 0.08, top - 0.90, 0.28, 0.08, shade(c, 1.16))
    if lay.get("tunnel"):                              # boca de túnel escura com moldura de rocha
        ax, v = lay["tunnel"]
        stone = shade(wa, 1.1)
        wbox(s, ax, v, 0.0, 2.0, 0.0, 2.0, 0.06, (6, 6, 12), outline=False)
        wbox(s, ax, v, -0.3, 0.3, 0.0, 2.35, 0.22, stone, g=0.2, tex=0.08)
        wbox(s, ax, v, 2.0, 0.3, 0.0, 2.35, 0.22, stone, g=0.2, tex=0.08)
        wbox(s, ax, v, -0.3, 2.6, 2.0, 0.35, 0.22, shade(stone, 1.1), g=0.2, tex=0.08)
    for (ax, v, zc, col) in lay.get("wall_crystals", ()):   # cristais brilhantes na parede
        wbox(s, ax, v, 0.0, 0.5, zc - 0.12, 0.22, 0.2, shade(wa, 1.25), g=0.12, tex=0.06)
        wbox(s, ax, v, 0.04, 0.12, zc + 0.10, 0.5, 0.16, col)
        wbox(s, ax, v, 0.06, 0.10, zc + 0.60, 0.14, 0.12, mix(col, 0.4))
        wbox(s, ax, v, 0.26, 0.12, zc + 0.10, 0.34, 0.16, shade(col, 0.8))
        wbox(s, ax, v, 0.28, 0.10, zc + 0.44, 0.12, 0.12, mix(col, 0.4))


def build_room(pal, duplo, seed, lay=None):
    fa, fb, wa, wb, _, ban = pal
    rng = random.Random(seed)
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    rock = shade(fb, 0.46)
    cave = bool(lay and lay.get("cave"))
    water = set(lay.get("water", ())) if lay else set()
    bridges = set(lay.get("bridges", ())) if lay else set()
    fords = set(lay.get("fords", ())) if lay else set()
    wet = water | bridges | fords
    liq = LIQUIDS[lay["liquid"]] if (lay and wet) else None
    r_axis = lay.get("river_axis", "y") if lay else "y"

    # ilha flutuante: camadas de rocha irregular sob o piso
    for layer, (z0, lo, hi, keep) in enumerate(((-1.25, -1, N, 0.80), (-1.9, 1, N - 1, 0.72), (-2.5, 2, N - 2, 0.65))):
        for x in range(lo, hi):
            for y in range(lo, hi):
                if rng.random() > keep and layer > 0:
                    continue
                if layer == 0 and (x == N - 1 or y == N - 1) and rng.random() < 0.3:
                    continue
                draw_box(s, x, y, z0, 1, 1, 0.65, shade(rock, 0.92 - 0.1 * layer + rng.uniform(-0.04, 0.04)),
                         g=0.34, tex=0.07)

    # piso: ladrilhos com variação, sombra junto às paredes, rachaduras e musgo
    for x in range(-1, N):
        for y in range(-1, N):
            if x < 0 or y < 0:
                c = shade(wa, 0.55)
            else:
                c = shade(fa if (x + y) % 2 == 0 else fb, rng.uniform(0.95, 1.05))
                if x == 0 or y == 0:
                    c = shade(c, 0.84)
                elif x == 1 or y == 1:
                    c = shade(c, 0.93)
            if cave and x >= 0 and y >= 0:       # caverna: chão de terra/rocha irregular
                c = shade(fa if rng.random() < 0.55 else fb, rng.uniform(0.80, 1.10))
                if x == 0 or y == 0:
                    c = shade(c, 0.80)
                elif x == 1 or y == 1:
                    c = shade(c, 0.90)
            if (x, y) in wet:
                kd_ = "water" if (x, y) in water else ("ford" if (x, y) in fords else "bridge")
                _liquid_cell(s, rng, x, y, liq, kd_, r_axis, fa)
                continue
            draw_box(s, x, y, -0.6, 1, 1, 0.55, c, g=0.2, tex=0.09 if cave else 0.05, bevel=not cave)
            if x >= 0 and y >= 0 and rng.random() < 0.13:
                px_, py_ = rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8)
                for _ in range(3):
                    qx = max(0.05, min(0.95, px_ + rng.uniform(-0.28, 0.28)))
                    qy = max(0.05, min(0.95, py_ + rng.uniform(-0.28, 0.28)))
                    pygame.draw.line(s, shade(c, 0.62), proj(x + px_, y + py_, -0.05), proj(x + qx, y + qy, -0.05))
                    px_, py_ = qx, qy

    # paredes: pedra com variação, base musgosa, cornija no topo e rodapé
    for x in range(-1, N):
        for y in range(-1, N):
            if (x < 0 or y < 0) and cave:        # paredes de rocha bruta, com topo irregular
                for z in range(WALL_H):
                    c = shade(wa if rng.random() < 0.5 else wb, rng.uniform(0.80, 1.15))
                    if z == 0:
                        c = shade(c, 0.85)
                        if rng.random() < 0.3:
                            c = mix(c, 0.3, (58, 112, 74))
                    draw_box(s, x, y, z, 1, 1, 1, c, g=0.25, tex=0.09, ao=(z == 0))
                if rng.random() < 0.55:
                    draw_box(s, x, y, WALL_H, 1, 1, rng.choice((0.35, 0.5, 0.75)), shade(wa, rng.uniform(0.95, 1.2)),
                             g=0.25, tex=0.09)
            elif x < 0 or y < 0:
                for z in range(WALL_H):
                    c = shade(wa if (x + y + z) % 2 == 0 else wb, rng.uniform(0.94, 1.06))
                    if z == 0:
                        c = shade(c, 0.88)
                        if rng.random() < 0.2:
                            c = mix(c, 0.3, (58, 112, 58))
                    draw_box(s, x, y, z, 1, 1, 1, c, g=0.2, tex=0.05, ao=(z == 0))
                draw_box(s, x, y, WALL_H, 1, 1, 0.14, mix(wa, 0.14), g=0.25, tex=0.04, bevel=True)
    for i in range(0 if cave else N):
        zx = ground(0.1, i + 0.5, duplo)
        zy = ground(i + 0.5, 0.1, duplo)
        if (0, i) not in wet:
            draw_box(s, 0, i, zx, 0.16, 1, 0.2, shade(wa, 0.72), g=0.1, tex=0.04, bevel=True)
        if (i, 0) not in wet:
            draw_box(s, i, 0, zy, 1, 0.16, 0.2, shade(wa, 0.72), g=0.1, tex=0.04, bevel=True)

    if duplo:
        # plataforma (2º andar) + escada de 5 degraus + guarda-corpo, ordenados de trás pra frente
        dl = []

        def add(x, y, z, w, d, h, c, **kw):
            dl.append((x + w / 2 + y + d / 2, z, (x, y, z, w, d, h, c), kw))

        for x in range(int(PLAT_X)):
            for y in range(N):
                c = shade(fa if (x + y) % 2 == 0 else fb, 0.92)
                add(x, y, 0, 1, 1, PLAT_H, c, g=0.2, tex=0.05, bevel=True, ao=True)
        stone = shade(wb, 0.9)
        for k in range(5):
            x0, hk = PLAT_X + 0.2 * k, 1.25 - 0.25 * k
            add(x0, 2.86, 0, 0.2, 0.14, hk + 0.22, stone, g=0.1, tex=0.04, bevel=True)
            add(x0, 3.0, 0, 0.2, 2.0, hk, mix(fa, 0.08 if k % 2 else 0.0), g=0.2, tex=0.05, bevel=True)
            add(x0, 5.0, 0, 0.2, 0.14, hk + 0.22, stone, g=0.1, tex=0.04, bevel=True)
        for yy in (2.80, 5.06):
            add(PLAT_X - 0.1, yy, PLAT_H, 0.16, 0.16, 0.62, (150, 108, 60), g=0.08, bevel=True)
            add(PLAT_X + 0.9, yy + 0.0, 0.0, 0.16, 0.16, 0.62, (150, 108, 60), g=0.08, bevel=True)
        for y in range(N):
            if 3 <= y <= 4:
                continue
            add(PLAT_X - 0.16, y + 0.42, PLAT_H, 0.12, 0.14, 0.52, (120, 84, 50), g=0.08, bevel=True)
            add(PLAT_X - 0.14, y, PLAT_H + 0.40, 0.08, 1.0, 0.07, (160, 118, 66), bevel=True)
        dl.sort(key=lambda it: (round(it[0], 3), it[1]))
        for _, _, args, kw in dl:
            draw_box(s, *args, **kw)
    elif not cave and not wet and rng.random() < 0.6:
        # tapete retangular (só em salas planas, sem rio)
        horiz = rng.random() < 0.5
        rw, rd = (3, 2) if horiz else (2, 3)
        rx, ry = rng.randint(2, N - rw - 1), rng.randint(2, N - rd - 1)
        base = shade(ban, 0.62)
        draw_box(s, rx, ry, -0.05, rw, rd, 0.04, base, outline=False, g=0.25, tex=0.04)
        draw_box(s, rx + 0.18, ry + 0.18, -0.01, rw - 0.36, rd - 0.36, 0.03, shade(ban, 0.85), outline=False, g=0.25, tex=0.04)
        draw_box(s, rx + 0.34, ry + 0.34, 0.02, rw - 0.68, rd - 0.68, 0.02, (222, 188, 90), outline=False, g=0.25, tex=0.03)
        draw_box(s, rx + 0.46, ry + 0.46, 0.04, rw - 0.92, rd - 0.92, 0.02, shade(ban, 0.7), outline=False, g=0.25, tex=0.04)

    # bandeiras nas paredes (posições sorteadas por andar)
    gold = (240, 205, 80)
    for ax, v in (lay["banners"] if lay else [("x", 4.0), ("y", 4.0)]):
        z0 = ground(0.1, v + 0.5, duplo) if ax == "x" else ground(v + 0.5, 0.1, duplo)
        bz = z0 + 0.55
        wbox(s, ax, v, 0.0, 1.0, bz, 0.95, 0.07, ban, g=0.2, tex=0.04)
        wbox(s, ax, v, -0.05, 1.10, bz + 0.95, 0.07, 0.11, (150, 110, 52), g=0.1)
        wbox(s, ax, v, -0.08, 0.10, bz + 0.92, 0.13, 0.13, gold, g=0.05)
        wbox(s, ax, v, 0.98, 0.10, bz + 0.92, 0.13, 0.13, gold, g=0.05)
        wbox(s, ax, v, 0.34, 0.32, bz + 0.5, 0.10, 0.10, gold, off=0.0, outline=False)
        wbox(s, ax, v, 0.45, 0.10, bz + 0.34, 0.42, 0.10, gold, off=0.0, outline=False)
        for fa_ in (0.08, 0.45, 0.82):
            wbox(s, ax, v, fa_, 0.10, bz - 0.10, 0.10, 0.06, gold, g=0.05, outline=False)

    # deco solta: pedrinhas com sombra e tufos de musgo em voxels
    rub = []
    for _ in range(26):
        x, y = rng.uniform(0.25, N - 0.7), rng.uniform(0.25, N - 0.7)
        if duplo and 2.9 < x < 5.4 and 2.5 < y < 5.5:
            continue
        if (int(x), int(y)) in wet:
            continue
        kind = rng.choice(["stone", "stone", "moss"])
        rub.append((x + y, x, y, rng.uniform(0.08, 0.22), kind))
    rub.sort()
    for _, x, y, sz, kind in rub:
        gz = ground(x, y, duplo)
        if kind == "moss":
            for _ in range(rng.randint(3, 6)):
                mx, my = x + rng.uniform(-0.18, 0.18), y + rng.uniform(-0.18, 0.18)
                mh = rng.uniform(0.03, 0.08)
                draw_box(s, mx, my, gz, 0.1, 0.1, mh, shade((70, 130, 70), rng.uniform(0.8, 1.2)), outline=False)
        else:
            draw_box(s, x, y, gz, sz, sz, sz * 0.8, shade(fa, 0.6 + rng.random() * 0.3), g=0)
            draw_box(s, x + sz * 0.15, y + sz * 0.15, gz + sz * 0.8, sz * 0.55, sz * 0.55, sz * 0.3,
                     shade(fa, 0.8 + rng.random() * 0.2), outline=False)
    if lay:
        for (dx_, dy_, kd) in lay["decor"]:      # decoração rasteira (poças, musgo, pedrinhas) vai no cenário em cache
            if kd in FLAT_KINDS:
                gz_ = ground(dx_, dy_, duplo)
                for (px_, py_, pz_, pw, pd, ph, pc) in decor_parts2(kd, 0.0):
                    draw_box(s, dx_ + px_, dy_ + py_, gz_ + pz_, pw, pd, ph, pc, outline=False)
        if cave:
            _cave_extras(s, rng, lay, pal, wet)
    return s


# ------------------------------------------------------------- poço de escada
def draw_stairwell(scr, sx, sy, gz, cam, t, pal, glows=None):
    """Poço com degraus de voxel descendo, borda de pedra, gemas pulsantes e seta flutuante."""
    wa = pal[2]
    a, rim = 0.62, 0.16
    pulse = 0.5 + 0.5 * math.sin(t * 4)
    P = lambda x, y, z: proj(x, y, z, cam)
    pygame.draw.polygon(scr, (6, 8, 18), [P(sx - a, sy - a, gz), P(sx + a, sy - a, gz), P(sx + a, sy + a, gz), P(sx - a, sy + a, gz)])
    bw = 0.14
    stone = shade(wa, 1.0)
    # paredes de trás (a face interna fica visível)
    draw_box(scr, sx - a, sy - a, gz - 0.6, bw, 2 * a, 0.6 + rim, stone, cam, g=0.2, bevel=True)
    draw_box(scr, sx - a + bw, sy - a, gz - 0.6, 2 * a - bw, bw, 0.6 + rim, shade(stone, 0.95), cam, g=0.2, bevel=True)
    # fundo brilhante + degraus descendo em direção à frente
    glow_c = mix((24, 60, 140), 0.25 + 0.35 * pulse, (90, 190, 255))
    pygame.draw.polygon(scr, glow_c, [P(sx - a + bw, sy - a + bw, gz - 0.55), P(sx + a - bw, sy - a + bw, gz - 0.55),
                                      P(sx + a - bw, sy + a - bw, gz - 0.55), P(sx - a + bw, sy + a - bw, gz - 0.55)])
    inner = 2 * a - 2 * bw
    for k in range(5):
        top = gz - 0.07 - 0.12 * k
        col = shade(wa, 0.95 - 0.09 * k)
        draw_box(scr, sx - a + bw, sy - a + bw + k * 0.19, gz - 0.58, inner, 0.19, top - (gz - 0.58), col, cam, g=0.19)
    if glows:
        gi = glows[min(len(glows) - 1, int(pulse * len(glows)))]
        gp = P(sx, sy, gz - 0.3)
        scr.blit(gi, (gp[0] - gi.get_width() // 2, gp[1] - gi.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
    # bordas da frente
    draw_box(scr, sx + a - bw, sy - a, gz, bw, 2 * a, rim, stone, cam, g=0.2, bevel=True)
    draw_box(scr, sx - a, sy + a - bw, gz, 2 * a - bw, bw, rim, shade(stone, 0.95), cam, g=0.2, bevel=True)
    gem = mix((50, 130, 255), 0.55 * pulse)
    for cx_, cy_ in ((sx - a, sy - a), (sx + a - 0.12, sy - a), (sx - a, sy + a - 0.12), (sx + a - 0.12, sy + a - 0.12)):
        draw_box(scr, cx_, cy_, gz + rim, 0.12, 0.12, 0.1, gem, cam, outline=False)
    # seta ▼ flutuante
    bob = 0.08 * math.sin(t * 4)
    ac = mix((70, 150, 255), 0.3 + 0.3 * pulse)
    for i, (wd, zz) in enumerate(((0.34, 0.0), (0.24, 0.1), (0.14, 0.2))):
        draw_box(scr, sx - wd / 2, sy - wd / 2, gz + 1.0 + zz + bob, wd, wd, 0.09, ac, cam, outline=False)
    draw_box(scr, sx - 0.06, sy - 0.06, gz + 1.32 + bob, 0.12, 0.12, 0.2, ac, cam, outline=False)


def make_glow(r, col):
    s = pygame.Surface((2 * r, 2 * r))
    s.fill((0, 0, 0))
    for i in range(r, 0, -2):
        k = (1 - i / r) ** 2
        pygame.draw.circle(s, (int(col[0] * k), int(col[1] * k), int(col[2] * k)), (r, r), i)
    return s


def make_vignette():
    v = pygame.Surface((W, H), pygame.SRCALPHA)
    for i in range(80):
        a = int(210 * (1 - i / 80) ** 1.7)
        pygame.draw.rect(v, (2, 0, 6, a), (i * 3, i * 2, W - i * 6, H - i * 4), 3)
    return v


# -------------------------------------------------------------- personagens
WHITE, DARK = (250, 250, 255), (26, 24, 36)


def parts_player(t, moving, hero=None):
    hero = hero or "knight"
    sw = math.sin(t * 10) if moving else 0.0
    l1, l2 = max(0, sw) * 0.08, max(0, -sw) * 0.08
    b = abs(sw) * 0.03 if moving else math.sin(t * 3) * 0.01
    arm = sw * 0.07
    steel, steelD = (196, 202, 216), (140, 148, 168)
    blue, blueD = (64, 104, 206), (44, 72, 150)
    gold, skin, brown, red = (240, 200, 70), (244, 206, 164), (110, 72, 44), (214, 52, 60)
    if hero == "ranger":
        blue, blueD, steel, steelD = (120, 180, 110), (82, 134, 78), (170, 200, 180), (110, 150, 128)
        red = (130, 210, 140)
    elif hero == "mage":
        blue, blueD, steel, steelD = (170, 130, 255), (120, 90, 196), (220, 206, 244), (158, 126, 204)
        red = (175, 120, 255)
    elif hero == "guardian":
        blue, blueD, steel, steelD = (240, 170, 110), (164, 118, 70), (210, 188, 150), (152, 116, 80)
        red = (248, 142, 92)
    return [
        (-0.16, -0.09, l1, 0.14, 0.19, 0.10, brown), (0.02, -0.09, l2, 0.14, 0.19, 0.10, brown),
        (-0.14, -0.07, 0.10 + l1, 0.10, 0.14, 0.18, steelD), (0.04, -0.07, 0.10 + l2, 0.10, 0.14, 0.18, steelD),
        (-0.16, -0.15, 0.22 + b, 0.32, 0.04, 0.36, red),
        (-0.18, -0.12, 0.28, 0.36, 0.24, 0.06, brown),
        (-0.035, 0.12, 0.285, 0.07, 0.02, 0.05, gold), (0.18, -0.035, 0.285, 0.02, 0.07, 0.05, gold),
        (-0.17, -0.11, 0.34 + b, 0.34, 0.22, 0.24, blue),
        (-0.17, -0.11, 0.34 + b, 0.34, 0.22, 0.04, blueD),
        (-0.04, 0.11, 0.42 + b, 0.08, 0.02, 0.11, gold), (0.17, -0.04, 0.42 + b, 0.02, 0.08, 0.11, gold),
        (-0.27, -0.10, 0.50 + b, 0.12, 0.20, 0.08, steel), (0.15, -0.10, 0.50 + b, 0.12, 0.20, 0.08, steel),
        (-0.25, -0.06, 0.30 + b - arm, 0.08, 0.12, 0.20, blueD), (0.17, -0.06, 0.30 + b + arm, 0.08, 0.12, 0.20, blueD),
        (-0.25, -0.05, 0.23 + b - arm, 0.08, 0.10, 0.07, skin), (0.17, -0.05, 0.23 + b + arm, 0.08, 0.10, 0.07, skin),
        (-0.32, -0.11, 0.20 + b - arm, 0.05, 0.22, 0.28, steel),
        (-0.275, -0.05, 0.28 + b - arm, 0.02, 0.10, 0.12, red),
        (0.20, -0.02, 0.31 + b + arm, 0.04, 0.04, 0.46, (236, 240, 250)),
        (0.16, -0.05, 0.28 + b + arm, 0.12, 0.10, 0.03, gold),
        (-0.14, -0.11, 0.60 + b, 0.28, 0.22, 0.22, skin),
        (-0.15, -0.12, 0.62 + b, 0.30, 0.05, 0.14, (120, 72, 40)),
        (-0.07, 0.11, 0.69 + b, 0.06, 0.02, 0.06, WHITE), (0.02, 0.11, 0.69 + b, 0.06, 0.02, 0.06, WHITE),
        (-0.05, 0.12, 0.70 + b, 0.03, 0.01, 0.04, DARK), (0.04, 0.12, 0.70 + b, 0.03, 0.01, 0.04, DARK),
        (0.14, -0.08, 0.69 + b, 0.02, 0.06, 0.06, WHITE), (0.14, 0.02, 0.69 + b, 0.02, 0.06, 0.06, WHITE),
        (0.15, -0.06, 0.70 + b, 0.01, 0.03, 0.04, DARK), (0.15, 0.04, 0.70 + b, 0.01, 0.03, 0.04, DARK),
        (-0.03, 0.11, 0.63 + b, 0.06, 0.02, 0.02, (190, 90, 80)),
        (-0.16, -0.13, 0.76 + b, 0.32, 0.26, 0.08, steel),
        (-0.16, -0.13, 0.66 + b, 0.03, 0.26, 0.10, steelD),
        (-0.03, -0.14, 0.84 + b, 0.06, 0.28, 0.08, red), (-0.03, -0.14, 0.80 + b, 0.06, 0.06, 0.06, red),
    ]


def parts_enemy(kind, t):
    if kind == "slime":
        sq = 1 + 0.10 * math.sin(t * 4)
        h1 = 0.30 / sq
        col, colL = (70, 200, 100), (130, 235, 150)
        return [
            (-0.36, -0.36, 0, 0.72, 0.72, h1, col), (-0.31, -0.31, h1, 0.62, 0.62, 0.12 / sq, col),
            (-0.22, -0.22, h1 + 0.12 / sq, 0.44, 0.44, 0.10 / sq, colL), (-0.14, -0.14, h1 + 0.22 / sq, 0.10, 0.10, 0.04, WHITE),
            (-0.02, -0.26, 0.10, 0.10, 0.10, 0.10, (40, 150, 80)), (-0.20, 0.36, 0.12, 0.14, 0.02, 0.16, WHITE), (0.06, 0.36, 0.12, 0.14, 0.02, 0.16, WHITE),
            (-0.15, 0.37, 0.14, 0.07, 0.01, 0.10, DARK), (0.11, 0.37, 0.14, 0.07, 0.01, 0.10, DARK), (-0.06, 0.36, 0.04, 0.12, 0.02, 0.04, DARK),
            (0.36, -0.20, 0.12, 0.02, 0.14, 0.16, WHITE), (0.36, 0.06, 0.12, 0.02, 0.14, 0.16, WHITE), (0.37, -0.15, 0.14, 0.01, 0.07, 0.10, DARK), (0.37, 0.11, 0.14, 0.01, 0.07, 0.10, DARK), (0.36, -0.06, 0.04, 0.02, 0.12, 0.04, DARK),
        ]
    if kind == "goblin":
        skin = (118, 198, 104)
        cloth = (56, 96, 64)
        metal = (170, 140, 76)
        arm = math.sin(t * 6) * 0.05
        return [
            (-0.18, -0.08, 0.00, 0.12, 0.12, 0.08, cloth), (0.06, -0.08, 0.00, 0.12, 0.12, 0.08, cloth),
            (-0.14, -0.10, 0.08, 0.28, 0.20, 0.22, skin), (-0.18, -0.12, 0.30, 0.40, 0.22, 0.07, cloth),
            (-0.21, -0.14, 0.36 - arm, 0.05, 0.08, 0.22, skin), (0.17, -0.14, 0.36 + arm, 0.05, 0.08, 0.22, skin),
            (-0.20, 0.05, 0.36, 0.08, 0.02, 0.18, metal), (0.12, 0.05, 0.36, 0.08, 0.02, 0.18, metal),
            (-0.10, -0.12, 0.54, 0.20, 0.18, 0.16, skin), (-0.15, -0.10, 0.66, 0.30, 0.20, 0.06, (90, 130, 58)),
            (-0.08, 0.11, 0.72, 0.06, 0.02, 0.08, DARK), (0.02, 0.11, 0.72, 0.06, 0.02, 0.08, DARK),
            (-0.05, 0.13, 0.74, 0.03, 0.01, 0.04, (255, 85, 72)), (0.04, 0.13, 0.74, 0.03, 0.01, 0.04, (255, 85, 72)),
            (0.18, -0.10, 0.66, 0.05, 0.06, 0.06, metal), (0.18, 0.03, 0.66, 0.05, 0.06, 0.06, metal),
            (0.18, 0.00, 0.28, 0.04, 0.04, 0.34, metal),
        ]
    if kind == "bat":
        wing = (102, 118, 150)
        body = (92, 90, 122)
        eye = (255, 240, 160)
        return [
            (-0.38, -0.08, 0.14, 0.14, 0.22, 0.06, wing), (-0.18, -0.32, 0.20, 0.18, 0.12, 0.06, wing),
            (0.24, -0.08, 0.14, 0.14, 0.22, 0.06, wing), (0.04, -0.32, 0.20, 0.18, 0.12, 0.06, wing),
            (-0.12, -0.03, 0.12, 0.24, 0.18, 0.16, body), (-0.06, 0.12, 0.20, 0.05, 0.02, 0.08, eye), (0.02, 0.12, 0.20, 0.05, 0.02, 0.08, eye),
            (-0.02, -0.04, 0.30, 0.04, 0.08, 0.06, (230, 210, 255)),
            (-0.06, -0.20, 0.12, 0.12, 0.02, 0.16, wing), (-0.02, -0.20, 0.12, 0.12, 0.02, 0.16, wing), (0.06, -0.20, 0.12, 0.12, 0.02, 0.16, wing),
        ]
    if kind == "skeleton":
        bone, boneD, brown = (236, 234, 218), (192, 190, 176), (130, 90, 54)
        arm = math.sin(t * 3) * 0.02
        parts = [(-0.14, -0.07, 0, 0.12, 0.16, 0.05, boneD), (0.02, -0.07, 0, 0.12, 0.16, 0.05, boneD), (-0.10, -0.03, 0.05, 0.04, 0.06, 0.25, bone), (0.06, -0.03, 0.05, 0.04, 0.06, 0.25, bone), (-0.11, -0.04, 0.17, 0.06, 0.08, 0.05, boneD), (0.05, -0.04, 0.17, 0.06, 0.08, 0.05, boneD), (-0.15, -0.08, 0.30, 0.30, 0.16, 0.07, boneD), (-0.025, -0.03, 0.37, 0.05, 0.06, 0.25, bone)]
        for i in range(3):
            parts.append((-0.16 + 0.01 * i, -0.08, 0.38 + i * 0.075, 0.32 - 0.02 * i, 0.16, 0.045, bone))
        parts += [(-0.18, -0.07, 0.60, 0.36, 0.10, 0.04, boneD), (-0.22, -0.04, 0.34 + arm, 0.04, 0.06, 0.28, bone), (0.18, -0.04, 0.34 - arm, 0.04, 0.06, 0.28, bone), (-0.14, -0.11, 0.66, 0.28, 0.22, 0.20, bone), (-0.11, -0.09, 0.62, 0.22, 0.18, 0.05, boneD), (-0.09, 0.11, 0.75, 0.07, 0.02, 0.07, DARK), (0.02, 0.11, 0.75, 0.07, 0.02, 0.07, DARK), (-0.07, 0.115, 0.77, 0.03, 0.01, 0.03, (255, 70, 70)), (0.04, 0.115, 0.77, 0.03, 0.01, 0.03, (255, 70, 70)), (0.14, -0.09, 0.75, 0.02, 0.07, 0.07, DARK), (0.14, 0.02, 0.75, 0.02, 0.07, 0.07, DARK), (-0.02, 0.11, 0.71, 0.04, 0.02, 0.04, DARK), (-0.08, 0.11, 0.65, 0.04, 0.02, 0.03, DARK), (-0.04, 0.11, 0.65, 0.04, 0.02, 0.03, WHITE), (0.00, 0.11, 0.65, 0.04, 0.02, 0.03, DARK), (0.04, 0.11, 0.65, 0.04, 0.02, 0.03, WHITE), (0.20, 0.0, 0.34 - arm, 0.035, 0.035, 0.42, (150, 150, 165)), (0.17, -0.03, 0.31 - arm, 0.10, 0.09, 0.03, brown), (-0.28, -0.10, 0.28 + arm, 0.05, 0.20, 0.22, brown), (-0.235, -0.02, 0.32 + arm, 0.02, 0.04, 0.14, (120, 120, 130)), (-0.235, -0.06, 0.37 + arm, 0.02, 0.12, 0.04, (120, 120, 130))]
        return parts
    if kind == "orc":
        skin, skinD = (104, 164, 76), (76, 126, 56)
        leather, metal, bone = (110, 74, 44), (130, 136, 150), (240, 238, 224)
        arm = math.sin(t * 3) * 0.03
        return [(-0.20, -0.10, 0, 0.16, 0.22, 0.10, leather), (0.04, -0.10, 0, 0.16, 0.22, 0.10, leather), (-0.18, -0.08, 0.10, 0.13, 0.17, 0.18, (82, 58, 40)), (0.05, -0.08, 0.10, 0.13, 0.17, 0.18, (82, 58, 40)), (-0.24, -0.15, 0.28, 0.48, 0.30, 0.07, leather), (-0.05, 0.15, 0.285, 0.10, 0.02, 0.07, bone), (0.24, -0.05, 0.285, 0.02, 0.10, 0.07, bone), (-0.27, -0.15, 0.35, 0.54, 0.30, 0.32, skin), (-0.18, 0.15, 0.36, 0.08, 0.02, 0.28, leather), (0.27, -0.12, 0.36, 0.02, 0.10, 0.28, leather), (-0.20, 0.15, 0.55, 0.16, 0.02, 0.07, skinD), (0.04, 0.15, 0.55, 0.16, 0.02, 0.07, skinD), (-0.39, -0.12, 0.60, 0.15, 0.24, 0.10, metal), (0.24, -0.12, 0.60, 0.15, 0.24, 0.10, metal), (-0.35, -0.03, 0.70, 0.05, 0.05, 0.08, bone), (0.30, -0.03, 0.70, 0.05, 0.05, 0.08, bone), (-0.37, -0.08, 0.36 - arm, 0.11, 0.16, 0.26, skin), (0.26, -0.08, 0.36 + arm, 0.11, 0.16, 0.26, skin), (-0.37, -0.07, 0.29 - arm, 0.11, 0.14, 0.08, skinD), (0.26, -0.07, 0.29 + arm, 0.11, 0.14, 0.08, skinD), (-0.17, -0.13, 0.70, 0.34, 0.26, 0.22, skin), (-0.16, -0.12, 0.66, 0.32, 0.24, 0.06, skinD), (-0.17, 0.13, 0.83, 0.34, 0.02, 0.04, skinD), (-0.11, 0.13, 0.78, 0.07, 0.02, 0.05, (255, 230, 60)), (0.04, 0.13, 0.78, 0.07, 0.02, 0.05, (255, 230, 60)), (-0.09, 0.135, 0.79, 0.03, 0.01, 0.03, (200, 30, 30)), (0.06, 0.135, 0.79, 0.03, 0.01, 0.03, (200, 30, 30)), (0.17, -0.11, 0.78, 0.02, 0.07, 0.05, (255, 230, 60)), (0.17, 0.04, 0.78, 0.02, 0.07, 0.05, (255, 230, 60)), (-0.11, 0.13, 0.67, 0.04, 0.02, 0.07, bone), (0.07, 0.13, 0.67, 0.04, 0.02, 0.07, bone), (0.17, -0.10, 0.67, 0.02, 0.04, 0.07, bone), (0.17, 0.06, 0.67, 0.02, 0.04, 0.07, bone), (-0.03, -0.13, 0.92, 0.06, 0.26, 0.08, DARK), (-0.03, -0.10, 0.98, 0.06, 0.18, 0.06, DARK), (0.35, 0.08, 0.20 + arm, 0.05, 0.05, 0.64, leather), (0.30, 0.04, 0.66 + arm, 0.14, 0.13, 0.14, metal), (0.44, 0.05, 0.67 + arm, 0.03, 0.11, 0.12, (210, 215, 225))]
    if kind == "wolfman":
        fur, furD, furL = (162, 148, 146), (124, 108, 102), (198, 178, 164)
        claw = (224, 214, 190)
        return [(-0.25, -0.12, 0.0, 0.20, 0.18, 0.12, furD), (0.05, -0.12, 0.0, 0.20, 0.18, 0.12, furD), (-0.20, -0.15, 0.12, 0.42, 0.28, 0.26, fur), (-0.18, -0.18, 0.38, 0.38, 0.24, 0.14, furL), (-0.28, -0.04, 0.42, 0.12, 0.12, 0.28, fur), (0.16, -0.04, 0.42, 0.12, 0.12, 0.28, fur), (-0.32, -0.12, 0.22, 0.10, 0.14, 0.30, fur), (0.22, -0.12, 0.22, 0.10, 0.14, 0.30, fur), (-0.18, 0.16, 0.54, 0.08, 0.02, 0.12, claw), (0.10, 0.16, 0.54, 0.08, 0.02, 0.12, claw), (-0.12, 0.16, 0.66, 0.21, 0.18, 0.18, furL), (-0.10, 0.15, 0.82, 0.16, 0.14, 0.06, (90, 30, 30)), (0.06, 0.15, 0.80, 0.04, 0.02, 0.12, (255, 210, 100)), (0.18, -0.04, 0.74, 0.06, 0.06, 0.08, claw), (0.18, 0.08, 0.74, 0.06, 0.06, 0.08, claw), (-0.26, 0.06, 0.74, 0.06, 0.06, 0.08, claw), (-0.26, -0.08, 0.74, 0.06, 0.06, 0.08, claw)]
    if kind == "ghost":
        z0 = 0.30 + 0.06 * math.sin(t * 3)
        c, cD, glow = (208, 228, 255), (150, 180, 235), (120, 235, 255)
        parts = []
        for i in range(4):
            h = 0.10 + 0.05 * math.sin(t * 5 + i * 1.6)
            parts.append((-0.24 + i * 0.12, -0.20, z0 - h, 0.12, 0.40, h, cD if i % 2 else c))
        parts += [(-0.24, -0.20, z0, 0.48, 0.40, 0.40, c), (-0.20, -0.17, z0 + 0.40, 0.40, 0.34, 0.14, c), (-0.14, -0.12, z0 + 0.54, 0.28, 0.24, 0.08, (230, 244, 255)), (-0.32, -0.08, z0 + 0.16 + 0.04 * math.sin(t * 4), 0.08, 0.16, 0.10, cD), (0.24, -0.08, z0 + 0.16 - 0.04 * math.sin(t * 4), 0.08, 0.16, 0.10, cD), (-0.14, 0.20, z0 + 0.30, 0.10, 0.02, 0.14, DARK), (0.04, 0.20, z0 + 0.30, 0.10, 0.02, 0.14, DARK), (-0.12, 0.21, z0 + 0.34, 0.05, 0.01, 0.07, glow), (0.06, 0.21, z0 + 0.34, 0.05, 0.01, 0.07, glow), (0.24, -0.14, z0 + 0.30, 0.02, 0.10, 0.14, DARK), (0.24, 0.04, z0 + 0.30, 0.02, 0.10, 0.14, DARK), (0.25, -0.12, z0 + 0.34, 0.01, 0.05, 0.07, glow), (0.25, 0.06, z0 + 0.34, 0.01, 0.05, 0.07, glow), (-0.05, 0.20, z0 + 0.16, 0.10, 0.02, 0.08, DARK), (0.24, -0.05, z0 + 0.16, 0.02, 0.10, 0.08, DARK)]
        for i in range(3):
            a = t * 2 + i * 2.1
            parts.append((math.cos(a) * 0.40 - 0.03, math.sin(a) * 0.40 - 0.03, z0 + 0.3 + 0.2 * math.sin(t * 3 + i), 0.06, 0.06, 0.06, glow))
        return parts
    if kind == "golem":
        rock, rockD, moss, rune = (142, 142, 154), (106, 106, 122), (80, 142, 76), (90, 230, 255)
        arm = math.sin(t * 2.5) * 0.04
        return [(-0.32, -0.18, 0, 0.26, 0.34, 0.14, rockD), (0.06, -0.18, 0, 0.26, 0.34, 0.14, rockD), (-0.28, -0.14, 0.14, 0.20, 0.26, 0.24, rock), (0.08, -0.14, 0.14, 0.20, 0.26, 0.24, rock), (-0.30, -0.18, 0.38, 0.60, 0.36, 0.10, rockD), (-0.42, -0.26, 0.48, 0.84, 0.52, 0.50, rock), (-0.10, 0.26, 0.62, 0.20, 0.02, 0.04, rune), (-0.02, 0.26, 0.54, 0.04, 0.02, 0.20, rune), (0.42, -0.10, 0.62, 0.02, 0.20, 0.04, rune), (0.42, -0.02, 0.54, 0.02, 0.04, 0.20, rune), (-0.36, -0.20, 0.98, 0.30, 0.22, 0.04, moss), (0.10, 0.0, 0.98, 0.26, 0.20, 0.04, moss), (-0.58, -0.20, 0.82, 0.22, 0.40, 0.18, rockD), (0.36, -0.20, 0.82, 0.22, 0.40, 0.18, rockD), (-0.58, -0.14, 0.34 - arm, 0.20, 0.28, 0.48, rock), (0.38, -0.14, 0.34 + arm, 0.20, 0.28, 0.48, rock), (-0.62, -0.18, 0.18 - arm, 0.28, 0.36, 0.18, rockD), (0.34, -0.18, 0.18 + arm, 0.28, 0.36, 0.18, rockD), (-0.18, -0.16, 0.98, 0.36, 0.32, 0.26, rock), (-0.12, 0.16, 1.08, 0.08, 0.02, 0.06, (255, 220, 60)), (0.04, 0.16, 1.08, 0.08, 0.02, 0.06, (255, 220, 60)), (0.18, -0.12, 1.08, 0.02, 0.08, 0.06, (255, 220, 60)), (0.18, 0.04, 1.08, 0.02, 0.08, 0.06, (255, 220, 60)), (-0.06, 0.16, 1.00, 0.12, 0.02, 0.03, DARK), (-0.30, -0.26, 1.0, 0.10, 0.10, 0.32, rune), (-0.18, -0.22, 1.0, 0.08, 0.08, 0.22, rune)]
    if kind == "goblin_chief":
        body = (72, 140, 88)
        acc = (222, 180, 90)
        return [(-0.40, -0.10, 0.0, 0.16, 0.18, 0.12, (48, 74, 52)), (0.20, -0.10, 0.0, 0.16, 0.18, 0.12, (48, 74, 52)), (-0.32, -0.18, 0.12, 0.64, 0.38, 0.28, body), (-0.14, -0.18, 0.40, 0.24, 0.18, 0.12, acc), (-0.28, 0.12, 0.42, 0.08, 0.03, 0.24, (230, 170, 75)), (0.18, 0.12, 0.42, 0.08, 0.03, 0.24, (230, 170, 75)), (-0.18, 0.10, 0.55, 0.36, 0.26, 0.20, (90, 190, 110)), (-0.16, 0.09, 0.74, 0.30, 0.20, 0.12, (60, 116, 84)), (-0.12, 0.18, 0.80, 0.12, 0.02, 0.08, (255, 215, 90)), (0.04, 0.18, 0.80, 0.12, 0.02, 0.08, (255, 215, 90)), (0.18, -0.10, 0.64, 0.08, 0.08, 0.08, (255, 215, 90))]
    if kind == "werewolf":
        fur = (120, 110, 106)
        claw = (224, 214, 190)
        return [(-0.34, -0.18, 0.0, 0.28, 0.24, 0.18, fur), (0.06, -0.18, 0.0, 0.28, 0.24, 0.18, fur), (-0.28, -0.20, 0.18, 0.56, 0.34, 0.32, (170, 150, 140)), (-0.28, -0.06, 0.50, 0.12, 0.10, 0.28, fur), (0.20, -0.06, 0.50, 0.12, 0.10, 0.28, fur), (-0.18, 0.08, 0.64, 0.34, 0.22, 0.18, fur), (-0.12, 0.16, 0.80, 0.07, 0.02, 0.10, (255, 170, 110)), (0.04, 0.16, 0.80, 0.07, 0.02, 0.10, (255, 170, 110)), (0.24, -0.06, 0.62, 0.05, 0.06, 0.08, claw), (-0.32, -0.06, 0.62, 0.05, 0.06, 0.08, claw)]
    if kind == "bat_queen":
        wing = (162, 132, 255)
        body = (108, 96, 164)
        return [(-0.48, -0.12, 0.24, 0.18, 0.28, 0.08, wing), (0.30, -0.12, 0.24, 0.18, 0.28, 0.08, wing), (-0.40, -0.28, 0.18, 0.12, 0.14, 0.12, wing), (0.28, -0.28, 0.18, 0.12, 0.14, 0.12, wing), (-0.14, -0.08, 0.14, 0.28, 0.26, 0.18, body), (-0.12, 0.15, 0.28, 0.04, 0.02, 0.12, (255, 235, 140)), (0.06, 0.15, 0.28, 0.04, 0.02, 0.12, (255, 235, 140)), (-0.02, -0.06, 0.32, 0.04, 0.08, 0.08, (220, 210, 255))]
    if kind == "orc_chief":
        skin = (122, 176, 102)
        cloth = (95, 80, 60)
        metal = (188, 194, 210)
        return [(-0.35, -0.18, 0.0, 0.22, 0.20, 0.12, cloth), (0.12, -0.18, 0.0, 0.22, 0.20, 0.12, cloth), (-0.28, -0.16, 0.12, 0.58, 0.34, 0.30, skin), (-0.22, -0.22, 0.42, 0.42, 0.18, 0.20, cloth), (-0.26, 0.16, 0.50, 0.08, 0.02, 0.24, metal), (0.18, 0.16, 0.50, 0.08, 0.02, 0.24, metal), (-0.18, 0.10, 0.62, 0.36, 0.22, 0.22, skin), (-0.15, 0.12, 0.82, 0.28, 0.18, 0.08, (100, 80, 60)), (-0.05, 0.18, 0.90, 0.11, 0.02, 0.10, (255, 230, 90)), (0.05, 0.18, 0.90, 0.11, 0.02, 0.10, (255, 230, 90)), (0.30, 0.02, 0.28, 0.04, 0.08, 0.40, metal)]
    # dragão
    r, rD, rL = (196, 52, 56), (140, 36, 44), (228, 96, 86)
    belly, horn, yel = (240, 200, 110), (240, 226, 170), (255, 232, 70)
    fl = math.sin(t * 4) * 0.10
    fire = 0.5 + 0.5 * math.sin(t * 9)
    parts = []
    for (lx, ly) in [(-0.38, -0.30), (0.18, -0.30), (-0.38, 0.10), (0.18, 0.10)]:
        parts += [(lx, ly, 0.0, 0.20, 0.20, 0.10, rD), (lx + 0.02, ly + 0.02, 0.10, 0.16, 0.16, 0.22, r), (lx + 0.02, ly + 0.20, 0.0, 0.04, 0.03, 0.05, horn), (lx + 0.08, ly + 0.20, 0.0, 0.04, 0.03, 0.05, horn), (lx + 0.14, ly + 0.20, 0.0, 0.04, 0.03, 0.05, horn)]
    parts += [(-1.30, -0.05, 0.52, 0.24, 0.10, 0.09, rD), (-1.08, -0.07, 0.46, 0.28, 0.14, 0.12, rD), (-0.82, -0.09, 0.40, 0.32, 0.18, 0.16, r), (-0.52, -0.12, 0.36, 0.36, 0.24, 0.20, r), (-1.40, -0.03, 0.54, 0.12, 0.06, 0.07, horn), (-0.52, -0.34, 0.32, 1.02, 0.68, 0.46, r), (-0.46, 0.34, 0.34, 0.90, 0.02, 0.30, belly), (0.50, -0.28, 0.34, 0.02, 0.56, 0.30, belly), (-0.30, -0.50, 0.80 + fl, 0.55, 0.03, 0.42, (150, 40, 62)), (-0.30, 0.37, 0.80 + fl, 0.55, 0.03, 0.42, (160, 44, 66)), (-0.30, -0.52, 0.80 + fl, 0.06, 0.06, 0.58, rD), (-0.30, 0.34, 0.80 + fl, 0.06, 0.06, 0.58, rD), (0.22, -0.17, 0.60, 0.26, 0.34, 0.22, r), (0.30, -0.16, 0.78, 0.24, 0.32, 0.22, r), (0.34, -0.15, 0.96, 0.22, 0.30, 0.20, r), (0.30, -0.20, 1.12, 0.40, 0.40, 0.28, rL), (0.70, -0.14, 1.12, 0.22, 0.28, 0.18, rL), (0.66, -0.12, 1.06, 0.22, 0.24, 0.06, rD), (0.92, -0.10, 1.12, 0.02, 0.04, 0.05, horn), (0.92, 0.00, 1.12, 0.02, 0.04, 0.05, horn), (0.92, 0.07, 1.12, 0.02, 0.04, 0.05, horn), (0.92, -0.08, 1.25, 0.02, 0.04, 0.03, DARK), (0.92, 0.04, 1.25, 0.02, 0.04, 0.03, DARK), (0.92, -0.04, 1.14, 0.02, 0.10, 0.04, (255, int(130 + 90 * fire), 30)), (0.36, 0.20, 1.26, 0.08, 0.02, 0.07, yel), (0.52, 0.20, 1.26, 0.08, 0.02, 0.07, yel), (0.39, 0.205, 1.27, 0.03, 0.01, 0.05, DARK), (0.55, 0.205, 1.27, 0.03, 0.01, 0.05, DARK), (0.32, -0.20, 1.40, 0.06, 0.06, 0.18, horn), (0.32, 0.14, 1.40, 0.06, 0.06, 0.18, horn), (0.28, -0.20, 1.54, 0.04, 0.05, 0.10, horn), (0.28, 0.15, 1.54, 0.04, 0.05, 0.10, horn)]
    for i in range(5):
        parts.append((-0.44 + i * 0.2, -0.06, 0.78, 0.08, 0.12, 0.10 + 0.02 * (i % 2), horn))
    return parts


def _face(hw, hd, z, ec=WHITE, pc=DARK, sz=0.06):
    out = []
    for sx in (-1, 1):
        x = sx * hw * 0.5 - sz / 2
        out += [(x, hd, z, sz, 0.02, sz, ec), (x + 0.015, hd + 0.01, z + 0.01, sz * 0.5, 0.01, sz * 0.7, pc)]
    for sy in (-1, 1):
        y = sy * hd * 0.5 - sz / 2
        out += [(hw, y, z, 0.02, sz, sz, ec), (hw + 0.01, y + 0.015, z + 0.01, 0.01, sz * 0.5, sz * 0.7, pc)]
    return out


parts_player_old = parts_player


def parts_hero(hero, t, moving):
    hero = hero or "knight"
    if hero == "ranger":
        g, gD, lea = (74, 140, 84), (46, 96, 56), (128, 92, 58)
        sw = math.sin(t * 10) if moving else 0.0
        l1, l2 = max(0, sw) * 0.08, max(0, -sw) * 0.08
        b = abs(sw) * 0.03 if moving else math.sin(t * 3) * 0.01
        arm = sw * 0.07
        skin, brown = (244, 206, 164), (110, 72, 44)
        P = [(-0.16, -0.09, l1, 0.14, 0.19, 0.10, (92, 64, 40)), (0.02, -0.09, l2, 0.14, 0.19, 0.10, (92, 64, 40)),
             (-0.14, -0.07, 0.10 + l1, 0.10, 0.14, 0.18, (96, 124, 84)), (0.04, -0.07, 0.10 + l2, 0.10, 0.14, 0.18, (96, 124, 84)),
             (-0.19, -0.17, 0.26 + b, 0.38, 0.05, 0.40, g), (-0.17, -0.11, 0.34 + b, 0.34, 0.22, 0.24, (150, 170, 96)),
             (-0.17, 0.11, 0.42 + b, 0.34, 0.02, 0.04, lea), (-0.18, -0.12, 0.28, 0.36, 0.24, 0.06, lea),
             (0.02, -0.21, 0.40 + b, 0.11, 0.08, 0.32, lea), (0.04, -0.20, 0.72 + b, 0.02, 0.02, 0.09, (235, 235, 205)),
             (0.07, -0.20, 0.72 + b, 0.02, 0.02, 0.07, (235, 80, 70)),
             (-0.25, -0.06, 0.30 + b - arm, 0.08, 0.12, 0.20, g), (0.17, -0.06, 0.30 + b + arm, 0.08, 0.12, 0.20, g),
             (-0.25, -0.05, 0.23 + b - arm, 0.08, 0.10, 0.07, skin), (0.17, -0.05, 0.23 + b + arm, 0.08, 0.10, 0.07, skin),
             (-0.36, -0.03, 0.26 + b - arm, 0.04, 0.05, 0.12, lea), (-0.36, 0.01, 0.38 + b - arm, 0.04, 0.05, 0.10, brown),
             (-0.36, 0.05, 0.48 + b - arm, 0.04, 0.05, 0.10, brown), (-0.36, 0.09, 0.58 + b - arm, 0.04, 0.05, 0.08, brown),
             (-0.36, 0.01, 0.16 + b - arm, 0.04, 0.05, 0.10, brown), (-0.36, 0.05, 0.06 + b - arm, 0.04, 0.05, 0.10, brown),
             (-0.36, 0.09, 0.0 + b - arm, 0.04, 0.05, 0.07, brown), (-0.345, 0.12, 0.05, 0.01, 0.01, 0.57, (240, 240, 230)),
             (0.20, 0.0, 0.33 + b + arm, 0.03, 0.20, 0.03, (232, 222, 180)), (0.20, 0.20, 0.325 + b + arm, 0.03, 0.04, 0.04, (180, 190, 200)),
             (-0.14, -0.11, 0.60 + b, 0.28, 0.22, 0.20, skin), (-0.17, -0.14, 0.76 + b, 0.34, 0.30, 0.08, g), (-0.17, -0.15, 0.60 + b, 0.34, 0.05, 0.24, g),
             (-0.17, -0.11, 0.62 + b, 0.03, 0.22, 0.16, gD), (0.14, -0.11, 0.74 + b, 0.03, 0.22, 0.04, gD),
             (-0.05, -0.18, 0.84 + b, 0.10, 0.14, 0.07, gD), (-0.20, -0.02, 0.70 + b, 0.06, 0.04, 0.05, skin), (0.14, -0.02, 0.70 + b, 0.06, 0.04, 0.05, skin),
             (-0.03, 0.11, 0.63 + b, 0.06, 0.02, 0.02, (190, 90, 80))]
        return P + _face(0.14, 0.11, 0.68 + b, WHITE, (40, 120, 70))
    if hero == "mage":
        rb, rbD, hat = (140, 96, 220), (92, 60, 160), (70, 48, 130)
        hair = (214, 96, 80)
        sw = math.sin(t * 10) if moving else 0.0
        l1, l2 = max(0, sw) * 0.08, max(0, -sw) * 0.08
        b = abs(sw) * 0.03 if moving else math.sin(t * 3) * 0.01
        arm = sw * 0.07
        skin = (244, 206, 164)
        glow = (110, 220, 255)
        P = [(-0.12, 0.12, 0.0 + l1, 0.10, 0.10, 0.05, (110, 72, 44)), (0.02, 0.12, 0.0 + l2, 0.10, 0.10, 0.05, (110, 72, 44)),
             (-0.23, -0.16, 0.04, 0.46, 0.32, 0.24, rbD), (-0.20, -0.14, 0.26 + b, 0.40, 0.28, 0.10, rb),
             (-0.23, -0.16, 0.04, 0.46, 0.32, 0.03, (240, 200, 70)),
             (-0.17, -0.11, 0.34 + b, 0.34, 0.22, 0.24, rb), (-0.19, -0.13, 0.30 + b, 0.38, 0.26, 0.05, (240, 200, 70)),
             (-0.02, 0.12, 0.40 + b, 0.04, 0.02, 0.16, (240, 200, 70)),
             (-0.27, -0.07, 0.28 + b - arm, 0.11, 0.15, 0.22, rbD), (0.16, -0.07, 0.28 + b + arm, 0.11, 0.15, 0.22, rbD),
             (-0.25, -0.05, 0.22 + b - arm, 0.08, 0.10, 0.07, skin), (0.17, -0.05, 0.22 + b + arm, 0.08, 0.10, 0.07, skin),
             (-0.36, -0.06, 0.26 + b - arm, 0.07, 0.16, 0.20, (160, 50, 90)), (-0.355, -0.05, 0.30 + b - arm, 0.02, 0.14, 0.04, (240, 200, 70)),
             (0.23, -0.02, 0.05 + b + arm, 0.04, 0.04, 0.85, (110, 72, 44)), (0.20, -0.05, 0.88 + b + arm, 0.10, 0.10, 0.04, (240, 200, 70)),
             (0.19, -0.06, 0.92 + b + arm, 0.12, 0.12, 0.12, glow),
             (-0.15, -0.15, 0.36 + b, 0.30, 0.06, 0.42, hair), (-0.15, -0.09, 0.50 + b, 0.03, 0.18, 0.26, hair), (0.12, -0.09, 0.50 + b, 0.03, 0.18, 0.26, hair),
             (-0.13, -0.10, 0.60 + b, 0.26, 0.20, 0.18, skin),
             (-0.24, -0.20, 0.78 + b, 0.48, 0.40, 0.04, hat), (-0.15, -0.12, 0.82 + b, 0.30, 0.24, 0.10, rb),
             (-0.11, -0.08, 0.92 + b, 0.22, 0.16, 0.10, rb), (-0.07, -0.04, 1.02 + b, 0.14, 0.08, 0.10, rb),
             (-0.03, -0.03, 1.12 + b, 0.06, 0.05, 0.07, rbD), (-0.03, 0.125, 0.84 + b, 0.06, 0.01, 0.06, (240, 200, 70)),
             (-0.03, 0.10, 0.62 + b, 0.06, 0.02, 0.02, (210, 110, 120))]
        return P + _face(0.13, 0.10, 0.69 + b, WHITE, (90, 40, 150))
    if hero == "guardian":
        br, brD, st = (206, 134, 72), (150, 92, 50), (190, 192, 204)
        dk = (62, 50, 50)
        sw = math.sin(t * 10) if moving else 0.0
        l1, l2 = max(0, sw) * 0.08, max(0, -sw) * 0.08
        b = abs(sw) * 0.03 if moving else math.sin(t * 3) * 0.01
        arm = sw * 0.07
        P = [(-0.20, -0.10, l1, 0.18, 0.22, 0.12, dk), (0.02, -0.10, l2, 0.18, 0.22, 0.12, dk),
             (-0.18, -0.08, 0.12 + l1, 0.14, 0.16, 0.18, brD), (0.04, -0.08, 0.12 + l2, 0.14, 0.16, 0.18, brD),
             (-0.25, -0.15, 0.26, 0.50, 0.30, 0.06, dk), (-0.24, -0.14, 0.30 + b, 0.48, 0.28, 0.30, br),
             (-0.24, -0.14, 0.30 + b, 0.48, 0.28, 0.04, brD), (-0.06, 0.14, 0.42 + b, 0.12, 0.02, 0.12, (240, 200, 70)),
             (-0.24, 0.14, 0.52 + b, 0.48, 0.02, 0.04, (240, 200, 70)),
             (-0.42, -0.15, 0.54 + b, 0.19, 0.30, 0.12, st), (0.23, -0.15, 0.54 + b, 0.19, 0.30, 0.12, st),
             (-0.38, -0.05, 0.66 + b, 0.07, 0.07, 0.09, st), (0.27, -0.05, 0.66 + b, 0.07, 0.07, 0.09, st),
             (-0.36, -0.08, 0.28 + b - arm, 0.12, 0.16, 0.26, brD), (0.24, -0.08, 0.28 + b + arm, 0.12, 0.16, 0.26, brD),
             (-0.36, -0.08, 0.20 + b - arm, 0.12, 0.16, 0.08, st), (0.24, -0.08, 0.20 + b + arm, 0.12, 0.16, 0.08, st),
             (-0.52, -0.22, 0.06 + b - arm, 0.08, 0.44, 0.66, st), (-0.44, -0.18, 0.10 + b - arm, 0.02, 0.36, 0.58, brD),
             (-0.435, -0.08, 0.28 + b - arm, 0.02, 0.16, 0.22, (240, 200, 70)),
             (0.29, -0.02, 0.10 + b + arm, 0.05, 0.05, 0.64, (110, 72, 44)), (0.21, -0.09, 0.72 + b + arm, 0.20, 0.18, 0.16, st),
             (0.21, -0.09, 0.72 + b + arm, 0.20, 0.18, 0.03, brD),
             (-0.15, -0.12, 0.62 + b, 0.30, 0.24, 0.22, st), (-0.11, 0.12, 0.72 + b, 0.22, 0.02, 0.04, (255, 200, 60)),
             (0.15, -0.08, 0.72 + b, 0.02, 0.16, 0.04, (255, 200, 60)),
             (-0.24, -0.04, 0.80 + b, 0.09, 0.08, 0.06, (244, 206, 164)), (-0.30, -0.04, 0.86 + b, 0.07, 0.08, 0.09, (244, 206, 164)),
             (0.15, -0.04, 0.80 + b, 0.09, 0.08, 0.06, (244, 206, 164)), (0.23, -0.04, 0.86 + b, 0.07, 0.08, 0.09, (244, 206, 164)),
             (-0.03, -0.14, 0.84 + b, 0.06, 0.28, 0.07, (214, 52, 60))]
        return P
    return parts_player_old(t, moving, hero)


def parts_player_base(t, moving, hero=None):
    hero = hero or "knight"
    if hero in {"ranger", "mage", "guardian"}:
        return parts_hero(hero, t, moving)
    return parts_player_old(t, moving, hero)


def hero_extras(hero, t, moving):
    """Detalhes animados extras (capa, cachecol, runas, orbes...)."""
    sw = math.sin(t * 10) if moving else 0.0
    b = abs(sw) * 0.03 if moving else math.sin(t * 3) * 0.01
    fl = 0.03 + (0.05 if moving else 0.0)
    gold = (240, 200, 70)
    P = []
    if hero == "knight":
        red = (214, 52, 60)
        for i in range(4):  # penacho do elmo
            sway = math.sin(t * 4 - i * 0.9) * 0.025 * (i + 1)
            P.append((-0.03 + sway, -0.17 - i * 0.07 - fl * i * 0.5, 0.84 + b - i * 0.035, 0.06, 0.08, 0.06, shade(red, 1.0 - i * 0.08)))
        P.append((-0.17, -0.14, 0.76 + b, 0.34, 0.28, 0.025, gold))
        for i in range(3):  # barra da capa balançando
            fo = math.sin(t * 5 - i * 0.7) * 0.03 + fl
            P.append((-0.16, -0.17 - fo * (i + 1), 0.20 - i * 0.07, 0.32, 0.04, 0.07, shade(red, 0.9 - i * 0.07)))
        if math.sin(t * 3.1) > 0.65:  # brilho na espada
            sz = 0.05 + 0.04 * math.sin(t * 20) ** 2
            P.append((0.19, -0.03, 0.80 + b, sz, sz, sz, (255, 255, 255)))
    elif hero == "ranger":
        for i in range(4):  # cachecol ao vento
            sway = math.sin(t * 5 - i) * 0.03 * (i + 1)
            P.append((0.0 + sway, -0.16 - i * 0.07 - fl * i * 0.4, 0.66 + b - i * 0.03, 0.07, 0.07, 0.05, (210, 84, 84)))
        for i in range(3):  # vaga-lumes
            a = t * 1.8 + i * 2.1
            P.append((math.cos(a) * 0.46 - 0.025, math.sin(a) * 0.46 - 0.025, 0.55 + 0.12 * math.sin(t * 3 + i * 2), 0.05, 0.05, 0.05, (190, 255, 170)))
    elif hero == "mage":
        glow = (110, 220, 255)
        for i in range(3):  # faíscas ao redor do orbe do cajado
            a = t * 3 + i * 2.09
            P.append((0.25 + math.cos(a) * 0.11 - 0.02, math.sin(a) * 0.11 - 0.02, 1.02 + 0.04 * math.sin(t * 4 + i), 0.04, 0.04, 0.04, glow))
        zb = 0.05 * math.sin(t * 2)  # grimório flutuante
        P.append((-0.56, -0.08, 0.55 + zb, 0.18, 0.16, 0.05, (150, 60, 70)))
        P.append((-0.55, -0.07, 0.60 + zb, 0.16, 0.14, 0.02, WHITE))
        pul = 0.5 + 0.5 * math.sin(t * 5)
        P.append((-0.49, -0.02, 0.68 + zb + 0.03 * pul, 0.04, 0.04, 0.04, mix(glow, 0.4 * pul)))
        sway = math.sin(t * 3) * 0.03  # ponta do chapéu
        P.append((0.0 + sway, -0.03, 1.19, 0.05, 0.05, 0.05, (92, 60, 160)))
        P.append((0.03 + sway * 2, -0.03, 1.23, 0.05, 0.05, 0.04, (92, 60, 160)))
    elif hero == "guardian":
        for i in range(6):  # anel de orbes dourados
            a = t * 2.2 + i * math.tau / 6
            P.append((math.cos(a) * 0.52 - 0.03, math.sin(a) * 0.52 - 0.03, 0.04 + 0.03 * math.sin(t * 4 + i), 0.06, 0.06, 0.06, gold))
        pul = 0.5 + 0.5 * math.sin(t * 4)
        P.append((-0.445, -0.04, 0.40, 0.02, 0.08, 0.10, mix(gold, 0.5 * pul)))
    return P


def parts_player(t, moving, hero=None):
    hero = hero or "knight"
    return parts_player_base(t, moving, hero) + hero_extras(hero, t, moving)


# ============================================================ HERÓIS V3 (voxel macio)
# Estilo: voxels gordinhos e pastel, sombras frias, luz quente no topo, quinas com brilho,
# sem contorno preto. Cabeçona + corpinho (chibi), olhos com brilho e bochechas.
SOFT_SHADOW = (26, 44, 78)
WARM_LIGHT = (255, 248, 232)


def tshade(c, f):
    """Sombreamento 'macio': luz quente nas faces claras, sombra azulada nas escuras."""
    if f >= 1.0:
        return mix(c, min(0.5, (f - 1.0) * 1.5), WARM_LIGHT)
    return mix(shade(c, f), (1.0 - f) * 0.30, SOFT_SHADOW)


def draw_box_soft(surf, x, y, z, w, d, h, color, cam=(0, 0)):
    """Voxel no estilo macio: sem contorno escuro, com oclusão na base e brilho nas quinas."""
    p = lambda a, b, c: proj(a, b, c, cam)
    ct, cl, cr = tshade(color, 1.16), tshade(color, 0.84), tshade(color, 0.64)
    top = [p(x, y, z + h), p(x + w, y, z + h), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    left = [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    right = [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x + w, y, z + h)]
    pygame.draw.polygon(surf, ct, top)
    pygame.draw.polygon(surf, cl, left)
    pygame.draw.polygon(surf, cr, right)
    if h > 0.11:  # oclusão ambiente na base das faces laterais
        band = min(0.10, h * 0.30)
        pygame.draw.polygon(surf, tshade(cl, 0.88), [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + band), p(x, y + d, z + band)])
        pygame.draw.polygon(surf, tshade(cr, 0.88), [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + band), p(x + w, y, z + band)])
    if max(w, d, h) > 0.075:  # brilho nas quinas (como nos blocos da referência)
        pygame.draw.line(surf, mix(ct, 0.50, WARM_LIGHT), p(x, y + d, z + h), p(x + w, y + d, z + h))
        pygame.draw.line(surf, mix(ct, 0.30, WARM_LIGHT), p(x + w, y, z + h), p(x + w, y + d, z + h))
        pygame.draw.line(surf, mix(cl, 0.22, WARM_LIGHT), p(x + w, y + d, z), p(x + w, y + d, z + h))


class _P(list):
    """Lista de voxels com construtor por centro: b(cx, cy, z, w, d, h, cor)."""

    def b(self, cx, cy, z, w, d, h, c):
        self.append((cx - w / 2, cy - d / 2, z, w, d, h, c))

    def wrap(self, cx, cy, w, d, z, h, c, t=0.016):
        """Faixa que contorna as duas faces visíveis (+x e +y) de uma caixa w x d, sem cruzar o volume."""
        self.append((cx + w / 2 - 0.004, cy - d / 2, z, t + 0.004, d + t, h, c))
        self.append((cx - w / 2, cy + d / 2 - 0.004, z, w, t + 0.004, h, c))


_BLEND = {}


def _gait(t, moving, face, key):
    """Ciclo de caminhada: pernas e braços balançam NA DIREÇÃO do movimento, corpo sobe e
    desce, leve balanço lateral; transição suave entre parado e andando; pisca de olhos."""
    fx, fy = face if face else (0.7071, 0.7071)
    n = math.hypot(fx, fy) or 1.0
    fx, fy = fx / n, fy / n
    m = _BLEND.get(key, 0.0)
    m += ((1.0 if moving else 0.0) - m) * 0.22
    if abs(m - (1.0 if moving else 0.0)) < 0.01:
        m = 1.0 if moving else 0.0
    _BLEND[key] = m
    ph = t * 10.0
    s, c = math.sin(ph), math.cos(ph)
    k = math.sin(t * 3.0)
    L, A = 0.12 * m, 0.10 * m
    g = {"f": (fx, fy), "m": m}
    g["bob"] = 0.045 * abs(c) * m + 0.010 * k * (1 - m)
    g["head"] = 0.014 * math.sin(ph * 2 + 0.8) * m + 0.008 * math.sin(t * 3.0 - 0.7) * (1 - m)
    g["sway"] = (-fy * 0.018 * s * m, fx * 0.018 * s * m)
    g["lA"] = (fx * s * L, fy * s * L, max(0.0, c) * 0.09 * m)
    g["lB"] = (-fx * s * L, -fy * s * L, max(0.0, -c) * 0.09 * m)
    g["aA"] = (-fx * s * A, -fy * s * A, 0.012 * math.sin(t * 3.0 + 1.0) * (1 - m))
    g["aB"] = (fx * s * A, fy * s * A, -0.012 * math.sin(t * 3.0 + 1.0) * (1 - m))
    tx, ty = -fx, -fy
    dot = (tx + ty) * 0.7071
    if dot > 0:   # andando "de costas": o vento vai para o lado, não para cima do corpo
        tx -= dot * 0.7071 * 1.15
        ty -= dot * 0.7071 * 1.15
    tl = math.hypot(tx, ty)
    if tl < 0.3:
        tx, ty = -0.45, -0.45
    else:
        tx, ty = tx / tl, ty / tl
    g["tx"], g["ty"] = tx, ty
    g["blink"] = 1.0 if (t % 3.7) < 0.12 else 0.0
    g["trail"] = 0.35 + 0.65 * m          # intensidade de capas/plumas ao vento
    return g


def _legs(P, g, boot, pant, sep=0.085, w=0.13):
    fx, fy = g["f"]
    for side, o in ((1, g["lA"]), (-1, g["lB"])):
        cx, cy = sep * side + o[0], -sep * side + o[1]
        P.b(cx, cy, o[2] + 0.06, w * 0.92, w * 0.92, 0.075, pant)
        P.b(cx + fx * 0.035, cy + fy * 0.035, o[2], w + 0.012, w + 0.012, 0.065, boot)


def _arm(P, g, side, cx0, sleeve, hand, extra=(0.0, 0.0, 0.0), w=0.095, z0=0.20, sh=0.13):
    """Braço: manga + mão. side=+1 -> lado A (direita da tela), -1 -> lado B."""
    o = g["aA"] if side > 0 else g["aB"]
    ox, oy, oz = o[0] + extra[0], o[1] + extra[1], o[2] + extra[2]
    b = g["bob"]
    P.b(side * cx0 + ox * 0.5, -side * cx0 + oy * 0.5, z0 + 0.075 + oz * 0.5 + b, w, w, sh, sleeve)
    P.b(side * cx0 + ox, -side * cx0 + oy, z0 + oz + b, w + 0.012, w + 0.012, 0.085, hand)
    return (side * cx0 + ox, -side * cx0 + oy, z0 + oz + b)


def _face3(P, cx, cy, hw, z, g, eye=(44, 46, 78), cheek=(255, 170, 164), mouth=(178, 86, 98),
           with_cheeks=False, with_mouth=False, eh0=0.05, ew=0.095):
    """Rosto virado para a câmera: um olho em cada face visível perto da quina."""
    eh = eh0 * (1.0 - 0.85 * g["blink"])
    ez = z + 0.17 + (0.105 - eh) / 2
    for face in (0, 1):
        def at(u, d_off, w, h, zz, col, dep=0.012):
            if face == 0:   # face +y (esquerda da tela): afastar da quina = -x
                P.b(cx + hw - u - w / 2, cy + hw + d_off, zz, w, dep, h, col)
            else:           # face +x (direita da tela): afastar da quina = -y
                P.b(cx + hw + d_off, cy + hw - u - w / 2, zz, dep, w, h, col)
        at(0.0925, 0.002, ew, eh, ez, eye)
        if g["blink"] < 0.5 and eh0 > 0.08:
            at(0.070, 0.006, 0.030, 0.034, ez + eh - 0.045, WHITE, 0.014)
        if with_cheeks:
            at(0.155, 0.001, 0.07, 0.04, z + 0.095, cheek, 0.010)
        if with_mouth:
            at(0.03, 0.002, 0.05, 0.026, z + 0.045, mouth)


def _orbit(P, g, t, n, r, z, size, col, speed=2.0, wob=0.04):
    for i in range(n):
        a = t * speed + i * math.tau / n
        P.b(math.cos(a) * r, math.sin(a) * r, z + wob * math.sin(t * 3 + i * 2), size, size, size, col)


def _knight(t, moving, face, atk):
    """Cavaleiro de Cinzas (design original): armadura carbonizada e rachada com brasas vivas nas frestas,
    coroa quebrada sobre o elmo fechado, manto de cinza se desfazendo e uma espada que solta brasas."""
    g = _gait(t, moving, face, "knight")
    fx, fy = g["f"]
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    ash, ashD, ashL = (68, 63, 66), (36, 34, 38), (108, 102, 102)
    cloak = (94, 88, 86)
    bronze, bone = (124, 94, 56), (196, 186, 164)
    pul = 0.5 + 0.5 * math.sin(t * 3.0)
    emb = mix((200, 64, 22), 0.55 * pul, (255, 178, 74))
    embD = (150, 40, 16)
    P = _P()
    _legs(P, g, ashD, ash)
    # peitoral rachado: brasa pulsando pelas frestas (nas duas faces visíveis)
    P.b(sx, sy, 0.12 + b, 0.34, 0.32, 0.30, ash)
    P.b(sx + 0.168, sy - 0.04, 0.17 + b, 0.012, 0.035, 0.20, emb)
    P.b(sx + 0.168, sy + 0.05, 0.26 + b, 0.012, 0.03, 0.10, embD)
    P.b(sx + 0.03, sy + 0.158, 0.17 + b, 0.035, 0.012, 0.20, emb)
    P.b(sx - 0.07, sy + 0.158, 0.27 + b, 0.03, 0.012, 0.08, embD)
    P.wrap(sx, sy, 0.34, 0.32, 0.17 + b, 0.04, bronze)
    P.b(sx + 0.178, sy + 0.17, 0.165 + b, 0.016, 0.05, 0.055, bone)
    for side in (1, -1):    # ombreiras lascadas
        o = g["aA"] if side > 0 else g["aB"]
        P.b(side * 0.215 + o[0] * 0.2, -side * 0.215 + o[1] * 0.2, 0.37 + b, 0.15, 0.15, 0.07, ashL)
    hB = _arm(P, g, -1, 0.215, ashD, ash)
    hA = _arm(P, g, 1, 0.215, ashD, ash, extra=(fx * 0.16 * atk, fy * 0.16 * atk, 0.10 * atk))
    # escudo quebrado (lado B): topo lascado e rachadura de brasa
    P.b(hB[0] - 0.01, hB[1] + 0.085, hB[2] - 0.05, 0.22, 0.05, 0.28, ash)
    P.b(hB[0] - 0.04, hB[1] + 0.085, hB[2] + 0.23, 0.12, 0.05, 0.07, ash)
    P.b(hB[0] - 0.01, hB[1] + 0.112, hB[2] + 0.00, 0.025, 0.012, 0.20, emb)
    P.b(hB[0] - 0.01, hB[1] + 0.112, hB[2] - 0.04, 0.16, 0.012, 0.03, bronze)
    # espada longa de aço escurecido; segmentos em brasa; faíscas subindo
    P.b(hA[0], hA[1], hA[2] + 0.07, 0.05, 0.05, 0.07, (84, 60, 44))
    P.b(hA[0], hA[1], hA[2] + 0.14, 0.17, 0.05, 0.035, bronze)
    lean = 0.04 + 0.30 * atk
    for i in range(7):
        k = i / 6.0
        col = emb if i in (2, 4) else ((132, 128, 134) if i < 6 else (204, 200, 204))
        P.b(hA[0] + fx * lean * k * k, hA[1] + fy * lean * k * k, hA[2] + 0.175 + i * 0.10, 0.055, 0.04, 0.11, col)
    for j in range(4):
        ph = (t * 0.9 + j / 4.0) % 1.0
        P.b(hA[0] + fx * lean * 0.5 + 0.04 * math.sin(t * 5 + j * 2), hA[1] + fy * lean * 0.5 + 0.04 * math.cos(t * 4 + j),
            hA[2] + 0.30 + ph * 0.55, 0.035 * (1 - ph) + 0.012, 0.035 * (1 - ph) + 0.012, 0.035 * (1 - ph) + 0.012,
            mix(emb, ph, (70, 34, 24)))
    # elmo fechado com fenda de brasa e coroa quebrada
    hz = 0.42 + hb
    hx, hy = sx * 1.4, sy * 1.4
    P.b(hx, hy, hz, 0.46, 0.46, 0.33, ash)
    P.wrap(hx, hy, 0.46, 0.46, hz + 0.28, 0.045, bronze)
    P.b(hx, hy, hz + 0.33, 0.50, 0.50, 0.10, ashL)
    P.b(hx + 0.232, hy - 0.10, hz + 0.06, 0.012, 0.03, 0.16, embD)
    P.b(hx - 0.10, hy + 0.232, hz + 0.20, 0.03, 0.012, 0.12, emb)
    for i, (dx, dy, hh) in enumerate(((0.17, 0.0, 0.16), (0.0, 0.17, 0.10), (-0.17, 0.0, 0.20),
                                      (0.0, -0.17, 0.07), (0.12, 0.12, 0.05), (-0.12, -0.12, 0.14))):
        P.b(hx + dx, hy + dy, hz + 0.43, 0.07, 0.07, hh, bronze if i % 2 == 0 else ashL)
    _face3(P, hx, hy, 0.23, hz, g, eye=(255, 140, 50))
    for j in range(3):      # brasas escapando do elmo
        ph = (t * 0.6 + j / 3.0) % 1.0
        P.b(hx + 0.05 * math.sin(t * 4 + j * 2), hy + 0.05 * math.cos(t * 3 + j), hz + 0.56 + ph * 0.42,
            0.045 * (1 - ph) + 0.012, 0.045 * (1 - ph) + 0.012, 0.045 * (1 - ph) + 0.012, mix(emb, ph, (80, 36, 24)))
    # manto de cinza se desfazendo
    for i in range(5):
        wv = math.sin(t * 5 - i * 0.8) * 0.035 * g["trail"]
        P.b(sx - 0.13 + g["tx"] * 0.07 * i * g["trail"] + wv * fy, sy - 0.13 + g["ty"] * 0.07 * i * g["trail"] - wv * fx,
            0.30 + b - i * 0.075, 0.26 - 0.02 * (i % 2), 0.26 - 0.02 * (i % 2), 0.08, shade(cloak, 0.95 - i * 0.07))
    for j in range(4):
        ph = (t * 0.5 + j / 4.0) % 1.0
        P.b(sx - 0.2 + g["tx"] * (0.1 + 0.3 * ph), sy - 0.2 + g["ty"] * (0.1 + 0.3 * ph), 0.15 + b + ph * 0.5,
            0.04, 0.04, 0.04, mix(cloak, ph, (30, 28, 30)))
    return P


def _ranger(t, moving, face, atk):
    g = _gait(t, moving, face, "ranger")
    fx, fy = g["f"]
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    gr, grD = (44, 58, 48), (28, 38, 34)
    brown, leather = (66, 50, 40), (88, 64, 48)
    skin, red = (168, 140, 124), (104, 20, 28)
    P = _P()
    _legs(P, g, brown, (46, 56, 46))
    P.b(sx, sy, 0.12 + b, 0.33, 0.31, 0.27, gr)
    P.wrap(sx, sy, 0.33, 0.31, 0.17 + b, 0.045, leather)
    P.b(sx + 0.178, sy + 0.16, 0.165 + b, 0.016, 0.05, 0.055, (150, 118, 60))
    P.b(sx + 0.166, sy + 0.0, 0.25 + b, 0.014, 0.30, 0.05, grD)
    P.b(sx + 0.0, sy + 0.156, 0.25 + b, 0.30, 0.014, 0.05, grD)
    # aljava nas costas com flechas
    qx, qy = sx - fx * 0.17 - 0.03, sy - fy * 0.17 + 0.03
    P.b(qx, qy, 0.20 + b, 0.10, 0.09, 0.30, leather)
    for i, cc in enumerate(((150, 150, 140), red, (150, 150, 140))):
        P.b(qx + (i - 1) * 0.035, qy - 0.01, 0.50 + b + (i % 2) * 0.03, 0.03, 0.03, 0.07, cc)
    hB = _arm(P, g, -1, 0.215, gr, skin)
    hA = _arm(P, g, 1, 0.215, gr, skin, extra=(fx * 0.14 * atk, fy * 0.14 * atk, 0.08 * atk))
    # arco na mão B
    for i in range(9):
        zi = hB[2] - 0.12 + 0.07 * i
        bulge = 0.055 * (1 - ((i - 4) / 4.0) ** 2)
        P.b(hB[0], hB[1] + 0.06 + bulge, zi, 0.045, 0.045, 0.075, brown if i not in (0, 8) else (110, 80, 60))
    P.b(hB[0], hB[1] + 0.06, hB[2] - 0.10, 0.012, 0.012, 0.56, (170, 168, 156))
    # flecha na mão A durante o ataque
    if atk > 0.05:
        P.b(hA[0] + fx * 0.10 * atk, hA[1] + fy * 0.10 * atk, hA[2] + 0.07, 0.03, 0.03, 0.03, (150, 150, 140))
    # cabeça com capuz
    hz = 0.45 + hb
    P.b(sx * 1.4, sy * 1.4, hz, 0.46, 0.46, 0.31, skin)
    P.b(sx * 1.4, sy * 1.4, hz + 0.31, 0.51, 0.51, 0.13, gr)
    P.b(sx * 1.4 + 0.235, sy * 1.4 - 0.16, hz + 0.02, 0.028, 0.07, 0.30, grD)
    P.b(sx * 1.4 - 0.16, sy * 1.4 + 0.235, hz + 0.02, 0.07, 0.028, 0.30, grD)
    P.b(sx * 1.4 - fx * 0.13, sy * 1.4 - fy * 0.13, hz + 0.36, 0.30, 0.30, 0.07, grD)
    tw = math.sin(t * 5) * 0.03 * g["trail"]
    for i in range(3):   # ponta do capuz balançando
        P.b(sx * 1.4 - 0.17 + g["tx"] * 0.06 * i + tw * fy * i, sy * 1.4 - 0.17 + g["ty"] * 0.06 * i - tw * fx * i,
            hz + 0.40 - i * 0.04, 0.12 - i * 0.025, 0.12 - i * 0.025, 0.09, gr)
    P.b(sx * 1.4 + 0.10, sy * 1.4 + 0.10, hz + 0.43, 0.04, 0.04, 0.14, (150, 150, 140))   # pena
    P.b(sx * 1.4 + 0.10 - fx * 0.03, sy * 1.4 + 0.10 - fy * 0.03, hz + 0.50, 0.04, 0.04, 0.08, red)
    _face3(P, sx * 1.4, sy * 1.4, 0.23, hz, g, eye=(214, 226, 206))
    # cachecol vermelho ao vento
    P.b(sx, sy, 0.39 + b, 0.37, 0.35, 0.06, red)
    for i in range(4):
        wv = math.sin(t * 6 - i) * 0.035 * g["trail"]
        P.b(sx - 0.17 + g["tx"] * (0.03 + 0.07 * i * (0.5 + 0.7 * g["trail"])) + wv * fy,
            sy - 0.17 + g["ty"] * (0.03 + 0.07 * i * (0.5 + 0.7 * g["trail"])) - wv * fx, 0.37 + b - i * 0.03, 0.08, 0.08, 0.07, shade(red, 1 - i * 0.07))
    _orbit(P, g, t, 3, 0.52, 0.55, 0.05, (120, 150, 90), 1.8, 0.05)
    return P


def _mage(t, moving, face, atk):
    g = _gait(t, moving, face, "mage")
    fx, fy = g["f"]
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    rb, rbD = (58, 40, 76), (36, 24, 52)
    hat, hatD = (42, 28, 60), (28, 18, 42)
    gold, skin, hair = (160, 124, 58), (172, 146, 134), (112, 34, 36)
    glow = (255, 118, 40)
    P = _P()
    for side, o in ((1, g["lA"]), (-1, g["lB"])):   # pés aparecendo sob a barra da túnica
        P.b(0.10 * side + o[0] + fx * 0.04, -0.10 * side + o[1] + fy * 0.04, o[2] * 0.8, 0.13, 0.13, 0.075, (130, 96, 84))
    tr = g["trail"]
    hemx, hemy = -fx * 0.025 * g["m"], -fy * 0.025 * g["m"]
    P.b(hemx, hemy, 0.075, 0.42, 0.40, 0.165, rbD)
    P.wrap(hemx, hemy, 0.42, 0.40, 0.075, 0.035, gold)
    P.b(sx * 0.6, sy * 0.6, 0.24 + b, 0.34, 0.32, 0.20, rb)
    P.wrap(sx * 0.6, sy * 0.6, 0.34, 0.32, 0.30 + b, 0.04, gold)
    P.b(sx * 0.6 + 0.172, sy * 0.6 + 0.06, 0.25 + b, 0.014, 0.12, 0.17, rbD)
    P.b(sx * 0.6 + 0.06, sy * 0.6 + 0.172, 0.25 + b, 0.12, 0.014, 0.17, rbD)
    hB = _arm(P, g, -1, 0.215, rbD, skin, w=0.115, sh=0.14)
    hA = _arm(P, g, 1, 0.215, rbD, skin, extra=(fx * 0.12 * atk, fy * 0.12 * atk, 0.10 * atk), w=0.115, sh=0.14)
    # cajado
    lean = 0.04 + 0.22 * atk
    for i in range(7):
        k = i / 6.0
        P.b(hA[0] + fx * lean * k * k, hA[1] + fy * lean * k * k, hA[2] - 0.12 + i * 0.13, 0.045, 0.045, 0.14, (150, 108, 78))
    ox, oy = hA[0] + fx * lean, hA[1] + fy * lean
    pul = 0.5 + 0.5 * math.sin(t * 5)
    P.b(ox, oy, hA[2] + 0.70, 0.17, 0.17, 0.035, gold)
    P.b(ox, oy, hA[2] + 0.735, 0.15, 0.15, 0.15, mix(glow, 0.25 * pul))
    P.b(ox, oy, hA[2] + 0.785, 0.06, 0.06, 0.06, (255, 255, 255))
    for i in range(3):
        a = t * 3 + i * 2.09
        P.b(ox + math.cos(a) * 0.14, oy + math.sin(a) * 0.14, hA[2] + 0.78 + 0.05 * math.sin(t * 4 + i), 0.04, 0.04, 0.04, glow)
    # grimório flutuante
    zb = 0.05 * math.sin(t * 2)
    bx, by = hB[0] - 0.07, hB[1] + 0.20
    P.b(bx, by, 0.50 + zb, 0.17, 0.05, 0.20, (104, 28, 40))
    P.b(bx, by + 0.03, 0.52 + zb, 0.13, 0.014, 0.16, (176, 164, 140))
    P.b(bx, by + 0.04, 0.58 + zb + 0.02 * pul, 0.035, 0.012, 0.035, mix(glow, 0.3 * pul))
    # cabeça
    hz = 0.42 + hb
    P.b(sx * 1.4, sy * 1.4, hz, 0.46, 0.46, 0.37, skin)
    P.b(sx * 1.4 + 0.235, sy * 1.4 - 0.15, hz + 0.02, 0.026, 0.09, 0.30, hair)
    P.b(sx * 1.4 - 0.15, sy * 1.4 + 0.235, hz + 0.02, 0.09, 0.026, 0.30, hair)
    P.b(sx * 1.4 + 0.235, sy * 1.4 + 0.14, hz + 0.31, 0.026, 0.10, 0.09, hair)             # franja
    P.b(sx * 1.4 + 0.14, sy * 1.4 + 0.235, hz + 0.31, 0.10, 0.026, 0.09, hair)
    _face3(P, sx * 1.4, sy * 1.4, 0.23, hz, g, eye=(255, 110, 40))
    # chapéu pontudo com ponta curvada
    P.b(sx * 1.4, sy * 1.4, hz + 0.37, 0.66, 0.66, 0.05, hatD)
    P.b(sx * 1.4, sy * 1.4, hz + 0.42, 0.46, 0.46, 0.05, gold)
    sw_ = math.sin(t * 3.0) * 0.02 + math.sin(t * 6) * 0.015 * g["m"]
    for i, (wd, hh) in enumerate(((0.40, 0.11), (0.32, 0.11), (0.24, 0.11), (0.16, 0.10), (0.10, 0.09))):
        k = i / 4.0
        P.b(sx * 1.4 - fx * 0.05 * k * 1.4 + sw_ * k * fy, sy * 1.4 - fy * 0.05 * k * 1.4 - sw_ * k * fx,
            hz + 0.47 + i * 0.105, wd, wd, hh, hat if i % 2 == 0 else mix(hat, 0.06))
    P.b(sx * 1.4 + 0.0, sy * 1.4 + 0.205, hz + 0.50, 0.10, 0.02, 0.10, gold)   # estrela
    P.b(sx * 1.4 + 0.205, sy * 1.4 + 0.0, hz + 0.50, 0.02, 0.10, 0.10, gold)
    return P


GUARDIAN_VIS = 0.72     # tamanho visual do Guardião (só o desenho): ~10% mais alto que os outros heróis


def _spk_up(P, cx, cy, z, w, h, c, n=3):
    """Espinho apontando para cima: caixas empilhadas que afinam até a ponta."""
    for i in range(n):
        k = 1.0 - i / float(n)
        s = max(0.02, w * k)
        P.b(cx, cy, z + i * h / n, s, s, h / n + 0.004, c)


def _spk_dir(P, cx, cy, zc, dx, dy, w, ln, c, n=3):
    """Espinho apontando para o lado (dx, dy); zc = altura do centro."""
    for i in range(n):
        k = 1.0 - i / float(n)
        s = max(0.02, w * k)
        d = i * ln / n
        P.b(cx + dx * d, cy + dy * d, zc - s / 2, s, s, s, c)


def _scale_parts_raw(P, k):
    return [(a * k, b * k, c * k, d * k, e * k, f * k, col) for (a, b, c, d, e, f, col) in P]


def _guardian(t, moving, face, atk):
    """Colosso de armadura completa: placas grossas de aço dos pés à cabeça, sem nenhuma pele à mostra."""
    g = _gait(t, moving, face, "guardian")
    fx, fy = g["f"]
    b, hb = g["bob"] * 0.6, g["bob"] * 0.6 + g["head"]
    sx, sy = g["sway"]
    m, mD, mL = (118, 122, 134), (72, 76, 90), (164, 168, 180)
    iron, rivet, visor = (46, 44, 52), (196, 182, 140), (8, 6, 10)
    P = _P()
    for side, o in ((1, g["lA"]), (-1, g["lB"])):     # pernas blindadas (sabatão, greva, joelheira, coxote)
        cx, cy = 0.14 * side + o[0], -0.14 * side + o[1]
        P.b(cx + fx * 0.05, cy + fy * 0.05, o[2], 0.27, 0.29, 0.10, mD)
        P.b(cx, cy, o[2] + 0.10, 0.22, 0.22, 0.16, m)
        P.b(cx, cy, o[2] + 0.26, 0.25, 0.25, 0.07, mL)
        P.b(cx, cy, o[2] + 0.33, 0.23, 0.23, 0.12, mD)
        _spk_dir(P, cx + fx * 0.12, cy + fy * 0.12, o[2] + 0.31, fx, fy, 0.08, 0.14, mL)   # espinho da joelheira
    # cintura, escarcela e peitoral enorme com placas rebitadas
    P.b(sx, sy, 0.43 + b, 0.56, 0.48, 0.10, iron)
    P.b(sx, sy, 0.46 + b, 0.60, 0.52, 0.12, mD)
    P.wrap(sx, sy, 0.60, 0.52, 0.52 + b, 0.05, mL)
    P.b(sx, sy, 0.58 + b, 0.62, 0.54, 0.40, m)
    P.b(sx + 0.318, sy, 0.64 + b, 0.016, 0.20, 0.30, mL)
    P.b(sx, sy + 0.278, 0.64 + b, 0.22, 0.016, 0.30, mL)
    P.wrap(sx, sy, 0.62, 0.54, 0.68 + b, 0.035, mD)
    P.wrap(sx, sy, 0.62, 0.54, 0.84 + b, 0.035, mD)
    for k in (-1, 1):
        P.b(sx + 0.322, sy + 0.10 * k, 0.70 + b, 0.012, 0.03, 0.03, rivet)
        P.b(sx + 0.10 * k, sy + 0.282, 0.70 + b, 0.03, 0.012, 0.03, rivet)
    P.b(sx * 1.2, sy * 1.2, 0.98 + b, 0.40, 0.38, 0.12, mD)    # gorjal
    for j in range(2):          # espinhos do peitoral (nas duas faces visíveis)
        for k in (-1, 1):
            _spk_dir(P, sx + 0.31, sy + 0.12 * k, 0.76 + 0.13 * j + b, 1, 0, 0.075, 0.15, mL)
            _spk_dir(P, sx + 0.12 * k, sy + 0.27, 0.76 + 0.13 * j + b, 0, 1, 0.075, 0.15, mL)
    _spk_dir(P, sx * 1.2 + 0.19, sy * 1.2, 1.04 + b, 1, 0, 0.07, 0.12, mL)      # espinhos do gorjal
    _spk_dir(P, sx * 1.2, sy * 1.2 + 0.18, 1.04 + b, 0, 1, 0.07, 0.12, mL)
    for side in (1, -1):        # ombreiras em camadas, com espigão
        o = g["aA"] if side > 0 else g["aB"]
        ox, oy = side * 0.42 + o[0] * 0.2, -side * 0.42 + o[1] * 0.2
        P.b(ox, oy, 0.86 + b, 0.30, 0.30, 0.16, m)
        P.b(ox, oy, 1.00 + b, 0.34, 0.34, 0.08, mL)
        P.b(ox, oy, 1.08 + b, 0.22, 0.22, 0.07, m)
        _spk_up(P, ox, oy, 1.15 + b, 0.13, 0.30, mL, 4)
        _spk_dir(P, ox + side * 0.15, oy - side * 0.15, 1.02 + b, side * 0.7071, -side * 0.7071, 0.09, 0.20, mL)
    hB = _arm(P, g, -1, 0.40, mD, m, w=0.20, z0=0.42, sh=0.30)
    hA = _arm(P, g, 1, 0.40, mD, m, extra=(fx * 0.14 * atk, fy * 0.14 * atk, 0.09 * atk), w=0.20, z0=0.42, sh=0.30)
    # escudo-torre de aço
    P.b(hB[0] - 0.04, hB[1] + 0.14, hB[2] - 0.36, 0.52, 0.09, 1.00, mD)
    P.b(hB[0] - 0.04, hB[1] + 0.19, hB[2] - 0.30, 0.44, 0.02, 0.88, m)
    P.b(hB[0] - 0.04, hB[1] + 0.212, hB[2] + 0.13, 0.44, 0.012, 0.04, iron)
    P.b(hB[0] - 0.04, hB[1] + 0.212, hB[2] - 0.12, 0.44, 0.012, 0.04, iron)
    P.b(hB[0] - 0.04, hB[1] + 0.215, hB[2] + 0.02, 0.18, 0.03, 0.18, mL)
    _spk_dir(P, hB[0] - 0.04, hB[1] + 0.23, hB[2] + 0.11, 0, 1, 0.14, 0.26, mL, 4)      # espinho central do escudo
    for kx in (-0.20, 0.20):                                                             # espinhos nas quinas de cima
        _spk_up(P, hB[0] - 0.04 + kx, hB[1] + 0.14, hB[2] + 0.64, 0.09, 0.18, mL)
    # martelo de guerra gigante
    lean = 0.04 + 0.28 * atk
    for i in range(6):
        k = i / 5.0
        P.b(hA[0] + fx * lean * k * k, hA[1] + fy * lean * k * k, hA[2] - 0.10 + i * 0.15, 0.07, 0.07, 0.16,
            iron if i % 2 else (78, 60, 46))
    hx_, hy_ = hA[0] + fx * lean, hA[1] + fy * lean
    P.b(hx_, hy_, hA[2] + 0.78, 0.44, 0.34, 0.05, mL)
    P.b(hx_, hy_, hA[2] + 0.83, 0.40, 0.30, 0.30, m)
    P.b(hx_, hy_, hA[2] + 1.13, 0.44, 0.34, 0.05, mL)
    _spk_up(P, hx_, hy_, hA[2] + 1.18, 0.12, 0.30, mL, 4)
    _spk_dir(P, hx_ + 0.22, hy_, hA[2] + 0.98, 1, 0, 0.10, 0.22, mL)
    _spk_dir(P, hx_, hy_ + 0.17, hA[2] + 0.98, 0, 1, 0.10, 0.22, mL)
    # grande elmo fechado: só fenda de olhos acesa
    hz = 1.08 + hb
    hx, hy = sx * 1.4, sy * 1.4
    P.b(hx, hy, hz, 0.58, 0.58, 0.40, m)
    P.b(hx, hy, hz + 0.40, 0.62, 0.62, 0.10, mL)
    P.b(hx, hy, hz + 0.50, 0.10, 0.56, 0.14, mD)
    P.wrap(hx, hy, 0.58, 0.58, hz + 0.30, 0.04, mD)
    P.b(hx + 0.285, hy, hz + 0.17, 0.012, 0.50, 0.05, visor)
    P.b(hx, hy + 0.285, hz + 0.17, 0.50, 0.012, 0.05, visor)
    for k in range(3):
        P.b(hx + 0.292, hy - 0.05 + 0.09 * k, hz + 0.07, 0.012, 0.03, 0.03, iron)
        P.b(hx - 0.05 + 0.09 * k, hy + 0.292, hz + 0.07, 0.03, 0.012, 0.03, iron)
    _face3(P, hx, hy, 0.29, hz, g, eye=(255, 96, 40))
    for k in (-0.18, 0.0, 0.18):                       # espinhos na crista do elmo
        _spk_up(P, hx, hy + k, hz + 0.64, 0.09, 0.18, mL)
    bone, boneD = (232, 222, 190), (150, 138, 112)
    sdx, sdy = -fy, fx                                  # lado do elmo (perpendicular ao rosto)
    outs = (0.31, 0.40, 0.47, 0.51, 0.51, 0.47)         # chifres curvos: saem para o lado e sobem
    for sg in (1, -1):
        for i, out in enumerate(outs):
            w_ = 0.18 - 0.024 * i
            P.b(hx + sdx * sg * out, hy + sdy * sg * out, hz + 0.24 + i * 0.115, w_, w_, 0.13,
                boneD if i == 0 else (bone if i < 5 else mix(bone, 0.5)))
    return _scale_parts_raw(P, GUARDIAN_VIS)


def _rogue(t, moving, face, atk):
    """Ladino: capuz azul-noite, máscara vermelha com rabo ao vento, cinto com facas e duas adagas."""
    g = _gait(t, moving, face, "rogue")
    fx, fy = g["f"]
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    cloth, clothD = (30, 32, 44), (20, 22, 32)
    hood, hoodD = (22, 24, 34), (14, 16, 24)
    red, redD = (128, 18, 32), (90, 12, 26)
    steel, steelL = (140, 148, 164), (206, 210, 222)
    gold, skin = (150, 116, 58), (166, 142, 128)
    boot, leather, glove = (34, 28, 34), (78, 58, 44), (38, 34, 42)
    P = _P()
    _legs(P, g, boot, clothD, sep=0.08, w=0.12)
    # corpo magrinho: túnica, cinto vermelho com fivela, facas e bolsinha
    P.b(sx, sy, 0.12 + b, 0.31, 0.29, 0.30, cloth)
    P.wrap(sx, sy, 0.31, 0.29, 0.17 + b, 0.045, red)
    P.b(sx + 0.163, sy + 0.12, 0.165 + b, 0.016, 0.05, 0.055, gold)
    P.b(sx + 0.162, sy - 0.06, 0.24 + b, 0.014, 0.16, 0.05, clothD)            # gola/faixa lateral
    P.b(sx + 0.05, sy + 0.153, 0.24 + b, 0.16, 0.014, 0.05, clothD)
    for i in range(3):                                                           # cabos de facas de arremesso
        P.b(sx - 0.08 + 0.065 * i, sy + 0.153, 0.215 + b, 0.03, 0.014, 0.07, steel if i != 1 else leather)
    P.b(sx + 0.162, sy - 0.07, 0.15 + b, 0.014, 0.09, 0.08, leather)             # bolsinha no quadril
    # capa curta escura (forro vermelho na ponta), balançando atrás
    for i in range(4):
        wv = math.sin(t * 5 - i * 0.8) * 0.035 * g["trail"]
        col = shade(clothD, 0.95 - i * 0.06) if i < 3 else redD
        P.b(sx - 0.13 + g["tx"] * 0.07 * i * g["trail"] + wv * fy, sy - 0.13 + g["ty"] * 0.07 * i * g["trail"] - wv * fx,
            0.31 + b - i * 0.07, 0.25, 0.25, 0.075, col)
    # braços: B (esquerda da tela) estoca para a frente, A (direita) segura a adaga em pé
    hB = _arm(P, g, -1, 0.205, clothD, glove, extra=(fx * 0.12 * atk, fy * 0.12 * atk, 0.05 * atk))
    hA = _arm(P, g, 1, 0.205, clothD, glove, extra=(fx * 0.17 * atk, fy * 0.17 * atk, 0.10 * atk))
    lean = 0.03 + 0.26 * atk
    P.b(hA[0], hA[1], hA[2] + 0.07, 0.045, 0.045, 0.07, leather)                 # adaga A
    P.b(hA[0], hA[1], hA[2] + 0.125, 0.13, 0.045, 0.03, gold)
    for i in range(4):
        k = i / 3.0
        P.b(hA[0] + fx * lean * k * k, hA[1] + fy * lean * k * k, hA[2] + 0.155 + i * 0.075,
            0.05 - 0.008 * i, 0.04, 0.08, steel if i < 3 else steelL)
    P.b(hB[0], hB[1], hB[2] + 0.065, 0.05, 0.05, 0.06, leather)                  # adaga B (apontada para frente)
    P.b(hB[0] + fx * 0.04 - fy * 0.05, hB[1] + fy * 0.04 + fx * 0.05, hB[2] + 0.075, 0.035, 0.035, 0.035, gold)
    P.b(hB[0] + fx * 0.04 + fy * 0.05, hB[1] + fy * 0.04 - fx * 0.05, hB[2] + 0.075, 0.035, 0.035, 0.035, gold)
    for i in range(4):
        P.b(hB[0] + fx * (0.07 + 0.07 * i), hB[1] + fy * (0.07 + 0.07 * i), hB[2] + 0.075 + 0.012 * i,
            0.06 - 0.008 * i, 0.06 - 0.008 * i, 0.045, steel if i < 3 else steelL)
    # cabeça: máscara vermelha embaixo, olhos de pele em cima, capuz com sombra na testa
    hz = 0.42 + hb
    hx, hy = sx * 1.4, sy * 1.4
    P.b(hx, hy, hz, 0.47, 0.47, 0.14, red)
    P.b(hx, hy, hz + 0.14, 0.46, 0.46, 0.18, skin)
    P.b(hx, hy, hz + 0.32, 0.52, 0.52, 0.14, hood)
    P.wrap(hx, hy, 0.46, 0.46, hz + 0.285, 0.04, hoodD, 0.03)                    # testa sombreada
    P.b(hx + 0.235, hy - 0.16, hz + 0.02, 0.028, 0.07, 0.30, hoodD)              # laterais do capuz
    P.b(hx - 0.16, hy + 0.235, hz + 0.02, 0.07, 0.028, 0.30, hoodD)
    P.b(hx + 0.19, hy + 0.19, hz + 0.38, 0.05, 0.05, 0.05, gold)                 # gema na frente do capuz
    _face3(P, hx, hy, 0.23, hz, g, eye=(255, 56, 56))
    tw = math.sin(t * 5) * 0.03 * g["trail"]
    for i in range(3):                                                           # ponta do capuz balançando
        P.b(hx - 0.17 + g["tx"] * 0.06 * i + tw * fy * i, hy - 0.17 + g["ty"] * 0.06 * i - tw * fx * i,
            hz + 0.40 - i * 0.04, 0.12 - 0.025 * i, 0.12 - 0.025 * i, 0.09, hood)
    for i in range(5):                                                           # rabo da máscara ao vento
        wv = math.sin(t * 6 - i) * 0.04 * g["trail"]
        P.b(hx - 0.17 + g["tx"] * (0.03 + 0.08 * i * (0.5 + 0.7 * g["trail"])) + wv * fy,
            hy - 0.17 + g["ty"] * (0.03 + 0.08 * i * (0.5 + 0.7 * g["trail"])) - wv * fx,
            hz + 0.06 - i * 0.025, 0.08, 0.08, 0.07, shade(red, 1.0 - i * 0.07))
    _orbit(P, g, t, 2, 0.52, 0.52, 0.045, (190, 36, 56), 2.4, 0.05)
    return P


_HERO_BUILDERS = {"knight": _knight, "ranger": _ranger, "mage": _mage, "guardian": _guardian, "rogue": _rogue}


# ------------------------------------------------------------------ visual por raça
# Cada raça muda o corpo (altura/largura), a cor da pele, a cor dos olhos e ganha detalhes próprios
# (orelhas, presas, barba, chifres, rabo, mochila...). Funciona sobre QUALQUER classe: é aplicado
# depois que o herói é montado, então Cavaleiro, Arqueira, Maga, Guardião e Ladino ganham todas.
RACE_LOOK = {
    "human":    {"xy": 1.00, "z": 1.00},
    "elf":      {"xy": 0.94, "z": 1.08, "skin": (208, 200, 216), "eye": (120, 238, 214)},
    "dwarf":    {"xy": 1.16, "z": 0.84, "skin": (200, 152, 128), "eye": (255, 196, 84)},
    "orc":      {"xy": 1.16, "z": 1.10, "skin": (98, 146, 82),   "eye": (255, 212, 52)},
    "halfling": {"xy": 0.92, "z": 0.78, "skin": (208, 158, 114), "eye": (150, 214, 255)},
    "tiefling": {"xy": 1.00, "z": 1.03, "skin": (182, 62, 86),   "eye": (255, 232, 90)},
}
_HERO_SKINS = {(168, 140, 124), (172, 146, 134), (166, 142, 128)}           # peles originais (arqueira, maga, ladino)
_HERO_EYES = {(44, 46, 78), (255, 140, 50), (214, 226, 206), (255, 110, 40), (255, 56, 56), (255, 96, 40)}


def _find_head(parts, hero):
    """Acha o bloco principal da cabeça: devolve (cx, cy, z_base, meia_largura, escala_k)."""
    if hero == "guardian":
        k = GUARDIAN_VIS
        for x, y, z, w, d, h, c in parts:
            if abs(w - 0.58 * k) < 1e-6 and abs(d - 0.58 * k) < 1e-6 and z > 0.5:
                return x + w / 2, y + d / 2, z, w / 2, k
    for x, y, z, w, d, h, c in parts:
        if 0.455 <= w <= 0.475 and abs(w - d) < 1e-6 and z >= 0.35 and h >= 0.13:
            return x + w / 2, y + d / 2, z, w / 2, 1.0
    return None


def apply_race(parts, hero, race, t=0.0, moving=False):
    look = RACE_LOOK.get(race)
    if not look or race == "human":
        return parts
    head = _find_head(parts, hero)
    skin = look.get("skin")
    eye = look.get("eye")
    out = []
    for x, y, z, w, d, h, c in parts:
        if skin is not None and c in _HERO_SKINS:
            c = skin
        elif eye is not None and c in _HERO_EYES and head and min(w, d) <= 0.016 * head[4] + 1e-6 \
                and abs(x - head[0]) < head[3] * 1.2 and abs(y - head[1]) < head[3] * 1.2 and head[2] < z < head[2] + 0.5 * head[4]:
            c = eye
        out.append((x, y, z, w, d, h, c))
    if head:
        hx, hy, hz, hw, k = head
        hw0 = hw / k                                    # meia-largura da cabeça em unidades "base"

        def B(dx, dy, dz, w, d, h, c):                  # caixa pelo centro, relativa à cabeça (unidades base)
            out.append((hx + (dx - w / 2) * k, hy + (dy - d / 2) * k, hz + dz * k, w * k, d * k, h * k, c))

        sd = shade(skin, 0.86) if skin else (120, 120, 120)
        if race == "elf":                                # orelhas longas e pontudas, inclinadas para cima
            for s in (1, -1):
                for i in range(3):
                    o = hw0 + 0.03 + 0.055 * i
                    B(s * o, -s * o, 0.10 + 0.065 * i, 0.10 - 0.025 * i, 0.10 - 0.025 * i, 0.075, skin if i < 2 else sd)
        elif race == "orc":                              # presas, orelhas curtas e brutas, testa pesada
            tus, tusL = (238, 230, 198), (255, 250, 226)
            u = 0.075
            B(hw0 - u - 0.02, hw0 + 0.022, 0.015, 0.04, 0.044, 0.07, tus)
            B(hw0 - u - 0.02, hw0 + 0.026, 0.085, 0.028, 0.032, 0.035, tusL)
            B(hw0 + 0.022, hw0 - u - 0.02, 0.015, 0.044, 0.04, 0.07, tus)
            B(hw0 + 0.026, hw0 - u - 0.02, 0.085, 0.032, 0.028, 0.035, tusL)
            for s in (1, -1):
                B(s * (hw0 + 0.04), -s * (hw0 + 0.04), 0.13, 0.09, 0.09, 0.09, skin)
                B(s * (hw0 + 0.07), -s * (hw0 + 0.07), 0.18, 0.05, 0.05, 0.06, sd)
        elif race == "dwarf":                            # barba ruiva trançada com argola de ouro
            bd, bdD, gold = (150, 74, 34), (112, 54, 28), (236, 192, 72)
            B(0.035, 0.035, -0.10, 0.44, 0.44, 0.16, bd)
            B(0.19, 0.19, -0.04, 0.10, 0.10, 0.07, bdD)
            B(0.13, 0.13, -0.19, 0.20, 0.20, 0.11, bd)
            B(0.13, 0.13, -0.22, 0.22, 0.22, 0.03, gold)
            B(0.14, 0.14, -0.31, 0.15, 0.15, 0.09, bdD)
            B(0.14, 0.14, -0.35, 0.10, 0.10, 0.04, bd)
        elif race == "halfling":                         # cachos de cabelo nas laterais + mochila de viajante
            hr, hrD = (126, 86, 52), (92, 62, 40)
            for s in (1, -1):
                B(s * (hw0 + 0.01), -s * (hw0 + 0.01), 0.06, 0.13, 0.13, 0.13, hr)
                B(s * (hw0 + 0.04), -s * (hw0 + 0.04), 0.10, 0.07, 0.07, 0.07, hrD)
            bk = 0.27 if hero != "guardian" else 0.36
            lea, rol = (112, 78, 50), (162, 70, 62)
            out.append((hx - bk - 0.10, hy - bk - 0.10, 0.12, 0.20, 0.20, 0.24, lea))
            out.append((hx - bk - 0.115, hy - bk - 0.115, 0.36, 0.23, 0.23, 0.08, rol))
            out.append((hx - bk - 0.02, hy - bk - 0.02, 0.17, 0.014, 0.10, 0.07, (232, 196, 90)))
        elif race == "tiefling":                         # chifres curvos + rabo com ponta de flecha
            hb_, ht_ = (86, 32, 46), (226, 196, 158)
            for s in (1, -1):
                outs = (0.95, 1.18, 1.34, 1.38, 1.30, 1.16)
                for i, o in enumerate(outs):
                    sz_ = 0.115 - 0.017 * i
                    B(s * hw0 * o, -s * hw0 * o, 0.16 + 0.07 * i, sz_, sz_, 0.085, hb_ if i < 3 else (ht_ if i == 5 else mix(ht_, 0.4, hb_)))
            reach = 0.25 if hero != "guardian" else 0.36
            sw = 1.0 + 0.6 * (1.0 if moving else 0.0)
            tl, tlD = shade(skin, 0.9), shade(skin, 0.72)
            for i in range(7):
                lat = 0.055 * sw * math.sin(t * 4.0 - i * 0.7) * (0.25 + i / 6.0)
                dist = reach + 0.07 * i
                tx_ = hx - dist * 0.7071 + lat * 0.7071
                ty_ = hy - dist * 0.7071 - lat * 0.7071
                sz_ = 0.085 - 0.007 * i
                out.append((tx_ - sz_ / 2, ty_ - sz_ / 2, 0.12 + 0.052 * i + 0.01 * i * i * 0.25, sz_, sz_, 0.07, tl if i % 2 == 0 else tlD))
            lat = 0.055 * sw * math.sin(t * 4.0 - 7 * 0.7)
            dist = reach + 0.07 * 7 + 0.03
            tx_, ty_ = hx - dist * 0.7071 + lat * 0.7071, hy - dist * 0.7071 - lat * 0.7071
            zt = 0.12 + 0.052 * 7 + 0.07
            spade = (150, 26, 52)
            out.append((tx_ - 0.07, ty_ - 0.07, zt, 0.14, 0.14, 0.04, spade))
            out.append((tx_ - 0.045, ty_ - 0.045, zt + 0.04, 0.09, 0.09, 0.04, spade))
            out.append((tx_ - 0.02, ty_ - 0.02, zt + 0.08, 0.04, 0.04, 0.04, mix(spade, 0.25)))
    sxy, sz = look["xy"], look["z"]
    if abs(sxy - 1.0) > 1e-6 or abs(sz - 1.0) > 1e-6:
        out = [(x * sxy, y * sxy, z * sz, w * sxy, d * sxy, h * sz, c) for x, y, z, w, d, h, c in out]
    return out


def parts_player(t, moving, hero=None, face=None, atk=0.0, race=None):
    P = list(_HERO_BUILDERS.get(hero or "knight", _knight)(t, moving, face, atk))
    if race and race != "human":
        P = apply_race(P, hero or "knight", race, t, moving)
    return P


def sit_parts(parts, fx=0.7071, fy=0.7071):
    """Pose sentada (tela de criação): pernas esticadas para a frente e corpo rente ao chão."""
    out = []
    drop = 0.08
    for x, y, z, w, d, h, c in parts:
        if z + h <= 0.15 and z < 0.10:                  # pernas e botas: repete para a frente
            for k in (0, 1, 2):
                out.append((x + fx * 0.10 * k, y + fy * 0.10 * k, z, w, d, h, c))
        else:                                           # resto do corpo desce até o chão
            z2 = z - drop
            if z2 < 0.0:
                h += z2
                z2 = 0.0
            if h > 0.008:
                out.append((x, y, z2, w, d, h, c))
    return out


def draw_pedestal(surf, cx, cy, s, col, glow=0.0):
    """Pedestal de pedra pastel com 'X' no topo e juntas de tijolo (referência visual)."""
    cam = (cx - OX, cy - OY)
    base = mix(col, 0.55, (176, 214, 220))
    draw_box_soft(surf, -0.50 * s, -0.50 * s, -0.20 * s, 1.0 * s, 1.0 * s, 0.20 * s, base, cam)
    p = lambda a, b, c: proj(a * s, b * s, c * s, cam)
    top = tshade(base, 1.16)
    mark = mix(top, 0.20 + 0.25 * glow, WARM_LIGHT)
    for q in (((-0.34, -0.06), (0.34, -0.06), (0.34, 0.06), (-0.34, 0.06)),
              ((-0.06, -0.34), (0.06, -0.34), (0.06, 0.34), (-0.06, 0.34))):
        pygame.draw.polygon(surf, mark, [p(a, b, 0.0) for a, b in q])
    jl = tshade(base, 0.74)
    pygame.draw.line(surf, jl, p(-0.50, 0.50, -0.10), p(0.50, 0.50, -0.10))
    pygame.draw.line(surf, tshade(base, 0.54), p(0.50, -0.50, -0.10), p(0.50, 0.50, -0.10))
    pygame.draw.line(surf, jl, p(0.0, 0.50, -0.20), p(0.0, 0.50, -0.10))
    pygame.draw.line(surf, tshade(base, 0.54), p(0.50, 0.0, -0.20), p(0.50, 0.0, -0.10))


# ---------------------------------------------------------------- ordem de desenho exata
_ORDER_CACHE = {}


def _exact_order(boxes, eps):
    """Ordena caixas alinhadas aos eixos de trás para frente (exato quando há um plano
    separador entre elas). boxes: (x, y, z, w, d, h, ...)."""
    n = len(boxes)
    mn = [(b[0], b[1], b[2]) for b in boxes]
    mx = [(b[0] + b[3], b[1] + b[4], b[2] + b[5]) for b in boxes]
    key = [(round(b[0] + b[3] / 2 + b[1] + b[4] / 2, 4), b[2]) for b in boxes]
    after = [[] for _ in range(n)]
    indeg = [0] * n
    for i in range(n):
        ix0, iy0, iz0 = mn[i]
        ix1, iy1, iz1 = mx[i]
        for j in range(i + 1, n):
            jx0, jy0, jz0 = mn[j]
            jx1, jy1, jz1 = mx[j]
            j_front = jx0 >= ix1 - eps or jy0 >= iy1 - eps or jz0 >= iz1 - eps
            i_front = ix0 >= jx1 - eps or iy0 >= jy1 - eps or iz0 >= jz1 - eps
            if j_front and not i_front:
                after[i].append(j)
                indeg[j] += 1
            elif i_front and not j_front:
                after[j].append(i)
                indeg[i] += 1
    heap = [(key[i], i) for i in range(n) if indeg[i] == 0]
    heapq.heapify(heap)
    out = []
    done = [False] * n
    while len(out) < n:
        if heap:
            _, i = heapq.heappop(heap)
            if done[i]:
                continue
        else:   # ciclo: solta a peça com menos pendências (desempate pela chave simples)
            i = min((i for i in range(n) if not done[i]), key=lambda i: (indeg[i], key[i]))
        done[i] = True
        out.append(i)
        for j in after[i]:
            if not done[j]:
                indeg[j] -= 1
                if indeg[j] <= 0:
                    heapq.heappush(heap, (key[j], j))
    return out


def world_parts(parts, x, y, z, s=1.0, flash=0.0):
    out = []
    for dx, dy, dz, w, d, h, c in parts:
        if flash > 0:
            c = mix(c, min(1, flash * 3))
        out.append((x + dx * s, y + dy * s, z + dz * s, w * s, d * s, h * s, c))
    return out


def draw_world_parts(surf, wparts, cam, key, eps):
    """Desenha as peças de um herói com ordem exata (recalculada ~15x/s e guardada em cache)."""
    now = time.perf_counter()
    ent = _ORDER_CACHE.get(key)
    if ent is None or ent[1] != len(wparts) or now - ent[2] > 0.066:
        ent = (_exact_order(wparts, eps), len(wparts), now)
        _ORDER_CACHE[key] = ent
    for i in ent[0]:
        x, y, z, w, d, h, c = wparts[i]
        draw_box_soft(surf, x, y, z, w, d, h, c, cam)


def _exact_order_dir(boxes, eps, dx, dy):
    """Igual a _exact_order, mas para uma câmera olhando de (dx, dy) no espaço do modelo.
    Serve para o herói girado: o modelo fica alinhado aos eixos e só a câmera 'gira'."""
    n = len(boxes)
    sx = 1 if dx > 1e-6 else (-1 if dx < -1e-6 else 0)
    sy = 1 if dy > 1e-6 else (-1 if dy < -1e-6 else 0)
    x0 = [b[0] for b in boxes]
    y0 = [b[1] for b in boxes]
    z0 = [b[2] for b in boxes]
    x1 = [b[0] + b[3] for b in boxes]
    y1 = [b[1] + b[4] for b in boxes]
    z1 = [b[2] + b[5] for b in boxes]
    key = [(round((x0[i] + x1[i]) * 0.5 * dx + (y0[i] + y1[i]) * 0.5 * dy, 4), z0[i]) for i in range(n)]
    after = [[] for _ in range(n)]
    indeg = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            j_front = ((sx > 0 and x0[j] >= x1[i] - eps) or (sx < 0 and x1[j] <= x0[i] + eps) or
                       (sy > 0 and y0[j] >= y1[i] - eps) or (sy < 0 and y1[j] <= y0[i] + eps) or
                       z0[j] >= z1[i] - eps)
            i_front = ((sx > 0 and x0[i] >= x1[j] - eps) or (sx < 0 and x1[i] <= x0[j] + eps) or
                       (sy > 0 and y0[i] >= y1[j] - eps) or (sy < 0 and y1[i] <= y0[j] + eps) or
                       z0[i] >= z1[j] - eps)
            if j_front and not i_front:
                after[i].append(j)
                indeg[j] += 1
            elif i_front and not j_front:
                after[j].append(i)
                indeg[i] += 1
    heap = [(key[i], i) for i in range(n) if indeg[i] == 0]
    heapq.heapify(heap)
    out = []
    done = [False] * n
    while len(out) < n:
        if heap:
            _, i = heapq.heappop(heap)
            if done[i]:
                continue
        else:   # ciclo: solta a peça com menos pendências
            i = min((i for i in range(n) if not done[i]), key=lambda i: (indeg[i], key[i]))
        done[i] = True
        out.append(i)
        for j in after[i]:
            if not done[j]:
                indeg[j] -= 1
                if indeg[j] <= 0:
                    heapq.heappush(heap, (key[j], j))
    return out


def draw_box_rot(surf, cx, cy, z, w, d, h, color, ang, cam=(0, 0), fx=False):
    """Voxel macio GIRADO `ang` rad em torno do eixo vertical (centro cx, cy). Só desenha as faces voltadas
    para a câmera; a cor de cada face vem da direção dela (mesma luz do draw_box_soft).
    fx=True (criaturas): faces grandes ganham miolo mais claro no topo e faixa de luz na borda
    superior das laterais, o que tira o aspecto chapado de 'tijolo' e dá volume de almofada."""
    ca, sa = math.cos(ang), math.sin(ang)
    ux, uy, vx, vy = ca * w / 2, sa * w / 2, -sa * d / 2, ca * d / 2
    cs = ((cx - ux - vx, cy - uy - vy), (cx + ux - vx, cy + uy - vy),
          (cx + ux + vx, cy + uy + vy), (cx - ux + vx, cy - uy + vy))
    nrm = ((sa, -ca), (ca, sa), (-sa, ca), (-ca, -sa))
    ct = tshade(color, 1.16)
    pygame.draw.polygon(surf, ct, [proj(a, b, z + h, cam) for a, b in cs])
    big = max(w, d, h) > 0.075
    if fx and w > 0.16 and d > 0.16:   # miolo do topo mais claro (volume de almofada)
        k = 0.64
        pygame.draw.polygon(surf, mix(ct, 0.13, WARM_LIGHT),
                            [proj(cx + (a - cx) * k, cy + (b - cy) * k, z + h, cam) for a, b in cs])
    if fx and w > 0.27 and d > 0.27:   # juntas de mini-voxels no topo (criaturas grandes não ficam com "pixel gigante")
        lt = shade(ct, 0.935)
        nu, nv = min(6, int(w / 0.14)), min(6, int(d / 0.14))
        for k in range(1, nu):
            f = k / nu
            pa = (cs[0][0] + (cs[1][0] - cs[0][0]) * f, cs[0][1] + (cs[1][1] - cs[0][1]) * f)
            pb = (cs[3][0] + (cs[2][0] - cs[3][0]) * f, cs[3][1] + (cs[2][1] - cs[3][1]) * f)
            pygame.draw.line(surf, lt, proj(pa[0], pa[1], z + h, cam), proj(pb[0], pb[1], z + h, cam))
        for k in range(1, nv):
            f = k / nv
            pa = (cs[0][0] + (cs[3][0] - cs[0][0]) * f, cs[0][1] + (cs[3][1] - cs[0][1]) * f)
            pb = (cs[1][0] + (cs[2][0] - cs[1][0]) * f, cs[1][1] + (cs[2][1] - cs[1][1]) * f)
            pygame.draw.line(surf, lt, proj(pa[0], pa[1], z + h, cam), proj(pb[0], pb[1], z + h, cam))
    vis = [False] * 4
    for i in range(4):
        nx, ny = nrm[i]
        if nx + ny <= 1e-4:
            continue
        vis[i] = True
        (ax, ay), (bx, by) = cs[i], cs[(i + 1) % 4]
        cf = tshade(color, 0.74 + 0.10 * (ny - nx))
        pygame.draw.polygon(surf, cf, [proj(ax, ay, z, cam), proj(bx, by, z, cam),
                                       proj(bx, by, z + h, cam), proj(ax, ay, z + h, cam)])
        if h > 0.11:   # oclusão ambiente na base
            band = min(0.10, h * 0.30)
            pygame.draw.polygon(surf, tshade(cf, 0.88), [proj(ax, ay, z, cam), proj(bx, by, z, cam),
                                                         proj(bx, by, z + band, cam), proj(ax, ay, z + band, cam)])
        if fx:   # juntas de mini-voxels nas laterais grandes
            L = math.hypot(bx - ax, by - ay)
            if L > 0.27 and h > 0.27:
                sc = shade(cf, 0.925)
                nu, nz = min(6, int(L / 0.14)), min(6, int(h / 0.14))
                for k in range(1, nu):
                    f = k / nu
                    xx, yy = ax + (bx - ax) * f, ay + (by - ay) * f
                    pygame.draw.line(surf, sc, proj(xx, yy, z, cam), proj(xx, yy, z + h, cam))
                for k in range(1, nz):
                    zz = z + h * k / nz
                    pygame.draw.line(surf, sc, proj(ax, ay, zz, cam), proj(bx, by, zz, cam))
        if fx and h > 0.20 and max(w, d) > 0.14:   # faixa de luz logo abaixo da borda de cima
            top_b = min(0.09, h * 0.22)
            pygame.draw.polygon(surf, mix(cf, 0.09, WARM_LIGHT),
                                [proj(ax, ay, z + h - top_b, cam), proj(bx, by, z + h - top_b, cam),
                                 proj(bx, by, z + h, cam), proj(ax, ay, z + h, cam)])
        if big:   # brilho na quina de cima
            k = 0.30 + 0.20 * max(0.0, min(1.0, (ny - nx + 1.0) / 2.0))
            pygame.draw.line(surf, mix(ct, k, WARM_LIGHT), proj(ax, ay, z + h, cam), proj(bx, by, z + h, cam))
    if big:   # brilho na quina vertical mais próxima da câmera
        cf = tshade(color, 0.84)
        for i in range(4):
            if vis[i] and vis[(i - 1) % 4]:
                ax, ay = cs[i]
                pygame.draw.line(surf, mix(cf, 0.22, WARM_LIGHT), proj(ax, ay, z, cam), proj(ax, ay, z + h, cam))


_FOE_SURF = {}
FOE_OUTLINE_BASE = (16, 14, 34)


def _foe_sprite(w, h):
    """Folha transparente reaproveitada (tamanhos em múltiplos de 16 para o cache funcionar)."""
    s = _FOE_SURF.get((w, h))
    if s is None:
        if len(_FOE_SURF) > 48:
            _FOE_SURF.clear()
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        _FOE_SURF[(w, h)] = s
    s.fill((0, 0, 0, 0))
    return s


_FOE_R = {}


def foe_shadow_r(kind):
    """Raio da sombra no chão proporcional ao corpo real da criatura (antes era fixo: 0.38)."""
    v = _FOE_R.get(kind)
    if v is None:
        try:
            ps = parts_enemy(kind, 0.0)
            zlow = [p for p in ps if p[2] < 0.3] or ps
            r = max(max(abs(p[0]), abs(p[0] + p[3]), abs(p[1]), abs(p[1] + p[4])) for p in zlow)
            v = max(0.38, min(1.0, r * 0.82))
        except Exception:
            v = 0.38
        _FOE_R[kind] = v
    return v


def foe_outline_color(kind):
    """Contorno 'seletivo': a cor da própria criatura bem escurecida e puxada para o azul-noite."""
    base = ENEMY_COLOR.get(kind, (120, 120, 120))
    return mix(shade(base, 0.30), 0.45, FOE_OUTLINE_BASE)


def draw_foe(surf, parts, ox, oy, oz, ang, cam, key, eps, kind="", elite=False, thick=1):
    """Desenha uma criatura: renderiza o modelo numa folha transparente, gera a silhueta
    e cola o contorno (1 px; 2 px nos chefões; dourado pulsante nos elites) antes do sprite.
    O contorno separa a criatura do chão e dá leitura mesmo quando a cor é parecida com o bioma."""
    r = zt = 0.0
    for x, y, z, w, d, h, c in parts:
        r = max(r, abs(x), abs(x + w), abs(y), abs(y + d))
        zt = max(zt, z + h)
    half_w = r * TW
    up, down = zt * ZH + r * TH, r * TH
    sw = (int(2 * half_w) + 14 + 15) // 16 * 16
    sh = (int(up + down) + 14 + 15) // 16 * 16
    ax, ay = sw // 2, sh - int(down) - 6
    spr = _foe_sprite(sw, sh)
    draw_hero_rot(spr, parts, 0.0, 0.0, 0.0, ang, (ax - OX, ay - OY), key, eps, 1e9, True)
    p0 = proj(ox, oy, oz, cam)
    bx, by = int(round(p0[0])) - ax, int(round(p0[1])) - ay
    if elite:
        pulse = 0.5 + 0.5 * math.sin(time.perf_counter() * 5.0)
        col, al = mix((255, 196, 60), 0.25 * pulse), 150 + int(105 * pulse)
        thick = max(thick, 2)
    else:
        col, al = foe_outline_color(kind), 215
    sil = spr.copy()
    sil.fill((0, 0, 0, al), special_flags=pygame.BLEND_RGBA_MULT)               # RGB -> 0, alpha escalado
    sil.fill((col[0], col[1], col[2], 0), special_flags=pygame.BLEND_RGBA_ADD)  # pinta a silhueta
    offs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if thick >= 2:
        offs += [(-1, -1), (1, -1), (-1, 1), (1, 1), (-2, 0), (2, 0), (0, -2), (0, 2)]
    for dx, dy in offs:
        surf.blit(sil, (bx + dx, by + dy))
    surf.blit(spr, (bx, by))


def scale_parts(parts, s, flash=0.0):
    """Escala os voxels do modelo (sem mover para o mundo): o giro é feito na hora de desenhar."""
    out = []
    for dx, dy, dz, w, d, h, c in parts:
        if flash > 0:
            c = mix(c, min(1, flash * 3))
        out.append((dx * s, dy * s, dz * s, w * s, d * s, h * s, c))
    return out


def draw_hero_rot(surf, parts, ox, oy, oz, ang, cam, key, eps=0.008, ttl=0.066, fx=False):
    """Desenha o herói girado `ang` rad (em torno do pé, em ox, oy, oz), peças em ordem exata de profundidade."""
    ca, sa = math.cos(ang), math.sin(ang)
    now = time.perf_counter()
    ent = _ORDER_CACHE.get(key)
    if ent is None or ent[1] != len(parts) or now - ent[2] > ttl:
        ent = (_exact_order_dir(parts, eps, ca + sa, ca - sa), len(parts), now)   # câmera no espaço do modelo
        _ORDER_CACHE[key] = ent
    for i in ent[0]:
        mx, my, mz, w, d, h, c = parts[i]
        qx, qy = mx + w / 2, my + d / 2
        draw_box_rot(surf, ox + qx * ca - qy * sa, oy + qx * sa + qy * ca, oz + mz, w, d, h, c, ang, cam, fx)


def _kobold(t):
    c, cD, bel, horn = (206, 92, 60), (150, 60, 44), (240, 200, 120), (240, 230, 190)
    arm = math.sin(t * 6) * 0.04
    P = [(-0.12, -0.06, 0, 0.09, 0.12, 0.05, cD), (0.03, -0.06, 0, 0.09, 0.12, 0.05, cD),
         (-0.10, -0.04, 0.05, 0.07, 0.08, 0.14, c), (0.03, -0.04, 0.05, 0.07, 0.08, 0.14, c),
         (-0.04, -0.28, 0.10, 0.08, 0.20, 0.06, c), (-0.03, -0.42, 0.14, 0.06, 0.14, 0.05, cD),
         (-0.14, -0.09, 0.18, 0.28, 0.18, 0.22, c), (-0.09, 0.09, 0.20, 0.18, 0.02, 0.16, bel),
         (-0.20, -0.04, 0.22 + arm, 0.06, 0.08, 0.14, c), (0.14, -0.04, 0.22 - arm, 0.06, 0.08, 0.14, c),
         (-0.13, -0.10, 0.40, 0.26, 0.22, 0.16, c), (-0.08, 0.12, 0.42, 0.16, 0.10, 0.08, mix(c, 0.25)),
         (-0.06, 0.22, 0.46, 0.03, 0.02, 0.03, DARK), (0.03, 0.22, 0.46, 0.03, 0.02, 0.03, DARK),
         (-0.10, -0.06, 0.56, 0.04, 0.04, 0.09, horn), (0.06, -0.06, 0.56, 0.04, 0.04, 0.09, horn),
         (0.20, 0.02, 0.05, 0.03, 0.03, 0.62, (120, 84, 50)), (0.19, 0.01, 0.67, 0.05, 0.05, 0.09, (200, 206, 216))]
    return P + _face(0.13, 0.11, 0.50, (255, 230, 60), DARK, 0.05)


def _gnoll(t):
    fur, spot, mane = (180, 144, 88), (110, 76, 46), (88, 58, 38)
    arm = math.sin(t * 5) * 0.04
    P = [(-0.16, -0.08, 0, 0.12, 0.16, 0.28, fur), (0.04, -0.08, 0, 0.12, 0.16, 0.28, fur),
         (-0.17, -0.09, 0, 0.14, 0.18, 0.05, spot), (0.03, -0.09, 0, 0.14, 0.18, 0.05, spot),
         (-0.18, -0.10, 0.26, 0.36, 0.20, 0.06, (150, 44, 44)), (-0.18, -0.10, 0.32, 0.36, 0.22, 0.26, fur),
         (-0.10, 0.12, 0.40, 0.05, 0.02, 0.05, spot), (0.04, 0.12, 0.48, 0.05, 0.02, 0.05, spot), (-0.18, 0.12, 0.44, 0.36, 0.02, 0.04, (120, 84, 50)),
         (-0.27, -0.06, 0.32 + arm, 0.09, 0.12, 0.26, fur), (0.18, -0.06, 0.32 - arm, 0.09, 0.12, 0.26, fur),
         (-0.12, -0.10, 0.60, 0.24, 0.20, 0.18, fur), (-0.07, 0.10, 0.62, 0.14, 0.14, 0.08, (70, 50, 40)),
         (-0.05, 0.24, 0.62, 0.10, 0.02, 0.03, WHITE), (-0.14, -0.04, 0.77, 0.06, 0.04, 0.09, spot), (0.08, -0.04, 0.77, 0.06, 0.04, 0.09, spot),
         (-0.04, -0.14, 0.62, 0.08, 0.10, 0.24, mane), (0.28, 0.0, 0.05, 0.03, 0.03, 0.88, (120, 84, 50)),
         (0.265, -0.015, 0.93, 0.06, 0.06, 0.12, (230, 226, 210))]
    return P + _face(0.12, 0.10, 0.70, (255, 220, 60), (160, 30, 30), 0.05)


def _zombie(t):
    sk, sD, rag = (122, 152, 112), (90, 118, 84), (92, 78, 60)
    sway = math.sin(t * 2) * 0.03
    P = [(-0.14, -0.07, 0, 0.12, 0.14, 0.30, (80, 70, 64)), (0.02, -0.07, 0, 0.12, 0.14, 0.24 + math.sin(t * 3) * 0.02, rag),
         (-0.17, -0.10, 0.30, 0.34, 0.20, 0.28, sk), (-0.17, 0.10, 0.34, 0.34, 0.02, 0.18, rag),
         (-0.08, 0.105, 0.40, 0.06, 0.01, 0.06, (170, 50, 50)),
         (-0.26, -0.02, 0.48 + sway, 0.08, 0.34, 0.08, sk), (0.18, -0.02, 0.50 - sway, 0.08, 0.34, 0.08, sk),
         (-0.26, 0.32, 0.46 + sway, 0.08, 0.06, 0.10, sD), (0.18, 0.32, 0.48 - sway, 0.08, 0.06, 0.10, sD),
         (-0.11, -0.08, 0.60, 0.26, 0.22, 0.20, sk), (-0.10, -0.08, 0.80, 0.10, 0.12, 0.04, (60, 60, 50)),
         (-0.05, 0.14, 0.62, 0.10, 0.02, 0.04, DARK), (-0.03, 0.14, 0.60, 0.06, 0.02, 0.03, (230, 230, 210))]
    return P + _face(0.15, 0.12, 0.70, (255, 240, 120), (150, 20, 20), 0.06)


def _ogre(t):
    sk, sD, cl = (204, 164, 112), (160, 124, 82), (120, 80, 50)
    arm = math.sin(t * 3) * 0.04
    P = [(-0.24, -0.12, 0, 0.20, 0.24, 0.26, sD), (0.04, -0.12, 0, 0.20, 0.24, 0.26, sD),
         (-0.32, -0.19, 0.20, 0.64, 0.38, 0.08, cl), (-0.30, -0.18, 0.28, 0.60, 0.36, 0.30, sk), (-0.04, 0.18, 0.40, 0.08, 0.02, 0.05, sD),
         (-0.34, -0.18, 0.56, 0.68, 0.34, 0.24, sk), (-0.50, -0.12, 0.30 + arm, 0.16, 0.22, 0.50, sk), (0.34, -0.12, 0.30 - arm, 0.16, 0.22, 0.50, sk),
         (-0.52, -0.13, 0.22 + arm, 0.20, 0.24, 0.12, sD), (0.32, -0.13, 0.22 - arm, 0.20, 0.24, 0.12, sD),
         (-0.16, -0.12, 0.80, 0.32, 0.28, 0.22, sk), (-0.12, 0.16, 0.82, 0.05, 0.03, 0.08, (240, 236, 210)), (0.07, 0.16, 0.82, 0.05, 0.03, 0.08, (240, 236, 210)),
         (-0.12, 0.16, 0.93, 0.24, 0.02, 0.04, DARK), (-0.03, 0.16, 0.86, 0.06, 0.04, 0.06, sD), (-0.16, -0.12, 0.99, 0.32, 0.28, 0.04, (70, 50, 40)),
         (0.40, 0.0, 0.15 - arm, 0.07, 0.07, 0.55, (120, 84, 50)), (0.34, -0.06, 0.65 - arm, 0.20, 0.20, 0.30, (110, 76, 46)),
         (0.31, 0.04, 0.78 - arm, 0.04, 0.04, 0.05, (200, 206, 216)), (0.46, 0.14, 0.72 - arm, 0.04, 0.04, 0.05, (200, 206, 216))]
    return P + _face(0.16, 0.14, 0.88, (255, 230, 80), (150, 20, 20), 0.05)


def _owlbear(t):
    fur, dk, fea, beak = (124, 86, 58), (84, 58, 40), (232, 222, 200), (242, 172, 52)
    arm = math.sin(t * 3) * 0.04
    P = []
    for (lx, ly) in [(-0.36, -0.34), (0.16, -0.34), (-0.36, 0.08), (0.16, 0.08)]:
        P.append((lx, ly, 0, 0.20, 0.22, 0.26, dk))
    P += [(-0.40, -0.36, 0.24, 0.80, 0.74, 0.46, fur), (-0.30, -0.30, 0.70, 0.60, 0.56, 0.10, dk),
          (-0.44, 0.38, 0.30, 0.88, 0.02, 0.30, mix(fur, 0.15)),
          (-0.46, 0.24, 0.42 + arm, 0.14, 0.24, 0.14, fur), (0.32, 0.24, 0.42 - arm, 0.14, 0.24, 0.14, fur),
          (-0.46, 0.48, 0.42 + arm, 0.04, 0.06, 0.06, (236, 232, 210)), (-0.38, 0.48, 0.42 + arm, 0.04, 0.06, 0.06, (236, 232, 210)),
          (0.32, 0.48, 0.42 - arm, 0.04, 0.06, 0.06, (236, 232, 210)), (0.40, 0.48, 0.42 - arm, 0.04, 0.06, 0.06, (236, 232, 210)),
          (-0.22, 0.10, 0.64, 0.44, 0.34, 0.34, fea), (-0.22, 0.10, 0.90, 0.44, 0.34, 0.08, fur),
          (-0.22, 0.12, 1.00, 0.07, 0.07, 0.09, fur), (0.15, 0.12, 1.00, 0.07, 0.07, 0.09, fur),
          (-0.06, 0.44, 0.64, 0.12, 0.12, 0.14, beak), (-0.04, 0.55, 0.62, 0.08, 0.04, 0.08, (200, 120, 40)),
          (-0.16, 0.44, 0.78, 0.11, 0.02, 0.11, (255, 220, 40)), (0.05, 0.44, 0.78, 0.11, 0.02, 0.11, (255, 220, 40)),
          (-0.12, 0.45, 0.80, 0.04, 0.01, 0.07, DARK), (0.09, 0.45, 0.80, 0.04, 0.01, 0.07, DARK),
          (0.22, 0.16, 0.78, 0.02, 0.12, 0.11, (255, 220, 40)), (0.23, 0.20, 0.80, 0.01, 0.05, 0.07, DARK)]
    return P


def _cube(t):
    w = 0.03 * math.sin(t * 3)
    out, inn = (120, 232, 190), (84, 196, 160)
    return [(-0.38, -0.38, 0.0, 0.76, 0.76, 0.76 + w, out), (-0.30, -0.30, 0.06, 0.60, 0.60, 0.62 + w, inn),
            (0.0, 0.08, 0.28 + w, 0.14, 0.14, 0.14, (236, 234, 220)), (0.02, 0.10, 0.34 + w, 0.03, 0.02, 0.03, DARK), (0.09, 0.10, 0.34 + w, 0.03, 0.02, 0.03, DARK),
            (0.14, 0.14, 0.18 + 0.03 * math.sin(t * 4), 0.07, 0.07, 0.04, (250, 206, 70)), (0.02, 0.22, 0.46 + w, 0.06, 0.06, 0.04, (250, 206, 70)),
            (0.10, 0.02, 0.38 + w, 0.05, 0.34, 0.03, (200, 206, 216)),
            (-0.38, -0.38, 0.76 + w, 0.76, 0.76, 0.03, (196, 255, 232))]


def _mimic(t):
    wood, lid, band, tongue = (150, 96, 50), (178, 118, 62), (76, 76, 88), (214, 70, 90)
    o = 0.10 * (1 + math.sin(t * 4)) * 0.5 + 0.04
    P = [(-0.36, -0.26, 0, 0.12, 0.12, 0.10, (110, 74, 40)), (0.24, -0.26, 0, 0.12, 0.12, 0.10, (110, 74, 40)),
         (-0.36, 0.14, 0, 0.12, 0.12, 0.10, (110, 74, 40)), (0.24, 0.14, 0, 0.12, 0.12, 0.10, (110, 74, 40)),
         (-0.40, -0.28, 0.10, 0.80, 0.56, 0.30, wood), (-0.41, -0.29, 0.10, 0.82, 0.58, 0.04, band), (-0.41, -0.29, 0.34, 0.82, 0.58, 0.04, band),
         (-0.36, -0.24, 0.38, 0.72, 0.48, 0.03, (96, 20, 36)),
         (-0.40, -0.30, 0.40, 0.80, 0.10, 0.30 + o, lid), (-0.40, -0.30, 0.70 + o, 0.80, 0.42, 0.08, lid), (-0.41, -0.31, 0.70 + o, 0.82, 0.44, 0.03, band),
         (-0.12, 0.10, 0.41, 0.24, 0.36, 0.04, tongue)]
    for i in range(6):
        x = -0.34 + i * 0.12
        P.append((x, 0.20, 0.41, 0.06, 0.06, 0.10, WHITE))
        P.append((x, 0.06, 0.62 + o, 0.06, 0.06, 0.08, WHITE))
    P += [(0.40, -0.10, 0.20, 0.02, 0.16, 0.10, (245, 205, 70)), (-0.08, 0.14, 0.78 + o, 0.16, 0.02, 0.10, WHITE), (-0.03, 0.15, 0.80 + o, 0.06, 0.01, 0.07, (200, 40, 40))]
    return P


def _troll(t):
    sk, sD, hair = (100, 148, 98), (72, 108, 72), (66, 104, 60)
    arm = math.sin(t * 3) * 0.04
    P = [(-0.22, -0.10, 0, 0.18, 0.22, 0.32, sD), (0.04, -0.10, 0, 0.18, 0.22, 0.32, sD),
         (-0.28, -0.17, 0.26, 0.56, 0.36, 0.08, (112, 80, 50)), (-0.28, -0.16, 0.32, 0.56, 0.34, 0.36, sk),
         (-0.20, 0.18, 0.40, 0.40, 0.02, 0.20, mix(sk, 0.18)), (0.0, 0.18, 0.50, 0.05, 0.02, 0.05, sD), (-0.14, 0.18, 0.44, 0.05, 0.02, 0.05, sD),
         (-0.44, -0.10, 0.14 - arm, 0.14, 0.18, 0.56, sk), (0.30, -0.10, 0.14 + arm, 0.14, 0.18, 0.56, sk),
         (-0.46, -0.10, 0.02 - arm, 0.18, 0.22, 0.14, sD), (0.28, -0.10, 0.02 + arm, 0.18, 0.22, 0.14, sD),
         (-0.14, 0.04, 0.68, 0.30, 0.30, 0.22, sk), (-0.14, 0.04, 0.90, 0.30, 0.30, 0.05, hair),
         (-0.03, 0.34, 0.74, 0.08, 0.08, 0.10, mix(sk, 0.25)), (-0.10, 0.34, 0.68, 0.04, 0.03, 0.07, (240, 236, 210)), (0.06, 0.34, 0.68, 0.04, 0.03, 0.07, (240, 236, 210)),
         (-0.18, 0.10, 0.76, 0.05, 0.04, 0.07, sk), (0.16, 0.10, 0.76, 0.05, 0.04, 0.07, sk)]
    return P + _face(0.15, 0.17, 0.80, (255, 70, 40), DARK, 0.06)


def _goblin_king(t):
    P = list(parts_enemy_old("goblin", t))
    gold, red = (244, 204, 70), (150, 30, 40)
    P += [(-0.24, -0.20, 0.10, 0.48, 0.04, 0.55, red), (-0.20, -0.12, 0.50, 0.40, 0.24, 0.05, (232, 232, 222)),
          (-0.13, -0.10, 0.72, 0.26, 0.18, 0.04, gold), (-0.13, -0.10, 0.76, 0.05, 0.05, 0.08, gold), (0.08, -0.10, 0.76, 0.05, 0.05, 0.08, gold),
          (-0.13, 0.03, 0.76, 0.05, 0.05, 0.08, gold), (0.08, 0.03, 0.76, 0.05, 0.05, 0.08, gold), (-0.03, 0.08, 0.73, 0.05, 0.02, 0.05, (230, 50, 60)),
          (0.24, 0.02, 0.10, 0.05, 0.05, 0.52, (120, 84, 50)), (0.18, -0.04, 0.60, 0.17, 0.17, 0.19, (110, 76, 46)),
          (0.16, 0.06, 0.72, 0.04, 0.04, 0.05, (200, 206, 216)), (0.34, -0.04, 0.68, 0.04, 0.04, 0.05, (200, 206, 216))]
    return P


def _beholder(t):
    z0 = 0.55 + 0.05 * math.sin(t * 2)
    col, colD = (164, 70, 124), (120, 48, 92)
    P = []
    for i, wd in enumerate((0.36, 0.52, 0.64, 0.72, 0.72, 0.64, 0.52, 0.36)):
        P.append((-wd / 2, -wd / 2, z0 + i * 0.09, wd, wd, 0.09, col if i % 2 else colD))
    P += [(-0.15, 0.36, z0 + 0.26, 0.30, 0.03, 0.24, WHITE), (-0.09, 0.38, z0 + 0.30, 0.18, 0.02, 0.16, (80, 220, 90)), (-0.04, 0.395, z0 + 0.34, 0.08, 0.01, 0.09, DARK),
          (0.36, -0.15, z0 + 0.26, 0.03, 0.30, 0.24, WHITE), (0.38, -0.09, z0 + 0.30, 0.02, 0.18, 0.16, (80, 220, 90)), (0.395, -0.04, z0 + 0.34, 0.01, 0.08, 0.09, DARK),
          (-0.26, 0.35, z0 + 0.04, 0.52, 0.03, 0.12, (70, 10, 30))]
    for i in range(6):
        P.append((-0.24 + i * 0.09, 0.36, z0 + 0.12, 0.05, 0.03, 0.05, WHITE))
    cols = [(255, 70, 70), (70, 140, 255), (255, 220, 60), (120, 255, 120), (255, 120, 255), (120, 255, 255), (255, 160, 60)]
    ztop0 = z0 + 0.72
    for i in range(7):
        a = i / 7 * math.tau
        wob = math.sin(t * 3 + i * 1.3) * 0.04
        ca, sa = math.cos(a), math.sin(a)
        for k in range(3):
            P.append((ca * (0.14 + 0.07 * k) + wob * k - 0.03, sa * (0.14 + 0.07 * k) + wob * k - 0.03, ztop0 - 0.05 + k * 0.11, 0.06, 0.06, 0.12, colD))
        ex, ey, ez = ca * 0.35 + wob * 3 - 0.06, sa * 0.35 + wob * 3 - 0.06, ztop0 + 0.30
        P += [(ex, ey, ez, 0.12, 0.12, 0.12, WHITE), (ex + 0.03, ey + 0.12, ez + 0.03, 0.06, 0.02, 0.06, cols[i]), (ex + 0.12, ey + 0.03, ez + 0.03, 0.02, 0.06, 0.06, cols[i])]
    return P


def _minotaur(t):
    fur, dk, sk, bone = (112, 72, 50), (70, 46, 34), (152, 98, 68), (240, 232, 208)
    arm = math.sin(t * 3) * 0.04
    P = [(-0.26, -0.12, 0, 0.20, 0.24, 0.08, (40, 30, 30)), (0.06, -0.12, 0, 0.20, 0.24, 0.08, (40, 30, 30)),
         (-0.24, -0.10, 0.08, 0.18, 0.20, 0.30, fur), (0.06, -0.10, 0.08, 0.18, 0.20, 0.30, fur),
         (-0.28, -0.14, 0.34, 0.56, 0.30, 0.08, (150, 40, 40)), (-0.32, -0.16, 0.42, 0.64, 0.32, 0.34, sk),
         (-0.20, 0.16, 0.50, 0.40, 0.02, 0.20, fur), (-0.20, 0.17, 0.60, 0.40, 0.01, 0.02, dk),
         (-0.46, -0.14, 0.66, 0.16, 0.28, 0.14, sk), (0.30, -0.14, 0.66, 0.16, 0.28, 0.14, sk),
         (-0.46, -0.10, 0.30 + arm, 0.14, 0.22, 0.40, sk), (0.32, -0.10, 0.30 - arm, 0.14, 0.22, 0.40, sk),
         (-0.47, -0.11, 0.34 + arm, 0.16, 0.24, 0.08, (222, 182, 70)), (0.31, -0.11, 0.34 - arm, 0.16, 0.24, 0.08, (222, 182, 70)),
         (-0.18, -0.14, 0.78, 0.36, 0.30, 0.26, fur), (-0.10, 0.16, 0.80, 0.20, 0.14, 0.14, (192, 142, 122)),
         (-0.06, 0.30, 0.84, 0.04, 0.02, 0.04, DARK), (0.02, 0.30, 0.84, 0.04, 0.02, 0.04, DARK), (-0.04, 0.31, 0.80, 0.08, 0.02, 0.03, (240, 200, 70)),
         (-0.30, -0.06, 0.98, 0.14, 0.06, 0.06, bone), (-0.38, -0.06, 1.04, 0.10, 0.06, 0.06, bone), (-0.40, -0.06, 1.10, 0.06, 0.06, 0.09, bone),
         (0.16, -0.06, 0.98, 0.14, 0.06, 0.06, bone), (0.28, -0.06, 1.04, 0.10, 0.06, 0.06, bone), (0.34, -0.06, 1.10, 0.06, 0.06, 0.09, bone),
         (0.42, 0.0, 0.10 - arm, 0.06, 0.06, 0.92, (120, 84, 50)), (0.46, -0.10, 0.88 - arm, 0.12, 0.26, 0.20, (200, 206, 216)),
         (0.58, -0.08, 0.92 - arm, 0.04, 0.22, 0.12, (240, 244, 250)), (0.32, -0.10, 0.88 - arm, 0.10, 0.26, 0.20, (150, 156, 170))]
    return P + _face(0.18, 0.14, 0.92, (255, 70, 40), DARK, 0.06)


def _lich(t):
    z0 = 0.12 + 0.05 * math.sin(t * 2)
    robe, robeD, bone, boneD = (82, 50, 124), (50, 30, 80), (238, 234, 214), (190, 186, 170)
    gold, glow = (244, 204, 70), (120, 255, 130)
    arm = math.sin(t * 2.5) * 0.04
    P = [(-0.26, -0.20, z0, 0.52, 0.40, 0.12, robeD), (-0.24, -0.18, z0 + 0.12, 0.48, 0.36, 0.14, robe),
         (-0.20, -0.14, z0 + 0.26, 0.40, 0.28, 0.30, robe), (-0.10, 0.14, z0 + 0.30, 0.20, 0.02, 0.22, (20, 10, 30))]
    for i in range(4):
        P.append((-0.24 + i * 0.13, -0.18, z0 - 0.08, 0.10, 0.34, 0.08, robeD if i % 2 else robe))
        P.append((-0.10, 0.15, z0 + 0.32 + i * 0.05, 0.20, 0.01, 0.025, bone))
    P += [(-0.26, -0.18, z0 + 0.56, 0.52, 0.36, 0.08, robeD),
          (-0.32, -0.08, z0 + 0.30 + arm, 0.10, 0.14, 0.26, robe), (0.22, -0.08, z0 + 0.30 - arm, 0.10, 0.14, 0.26, robe),
          (-0.32, -0.07, z0 + 0.24 + arm, 0.10, 0.12, 0.06, bone), (0.22, -0.07, z0 + 0.24 - arm, 0.10, 0.12, 0.06, bone),
          (-0.14, -0.11, z0 + 0.66, 0.28, 0.22, 0.22, bone), (-0.10, -0.08, z0 + 0.60, 0.20, 0.16, 0.06, boneD),
          (-0.10, 0.11, z0 + 0.76, 0.08, 0.02, 0.08, DARK), (0.02, 0.11, z0 + 0.76, 0.08, 0.02, 0.08, DARK),
          (-0.08, 0.115, z0 + 0.78, 0.04, 0.01, 0.04, glow), (0.04, 0.115, z0 + 0.78, 0.04, 0.01, 0.04, glow),
          (0.14, -0.09, z0 + 0.76, 0.02, 0.08, 0.08, DARK), (0.14, 0.01, z0 + 0.76, 0.02, 0.08, 0.08, DARK),
          (0.145, -0.07, z0 + 0.78, 0.01, 0.04, 0.04, glow), (0.145, 0.03, z0 + 0.78, 0.01, 0.04, 0.04, glow),
          (-0.02, 0.11, z0 + 0.70, 0.04, 0.02, 0.04, DARK),
          (-0.15, -0.12, z0 + 0.88, 0.30, 0.24, 0.04, gold), (-0.15, -0.12, z0 + 0.92, 0.04, 0.04, 0.08, gold), (0.11, -0.12, z0 + 0.92, 0.04, 0.04, 0.08, gold),
          (-0.15, 0.08, z0 + 0.92, 0.04, 0.04, 0.08, gold), (0.11, 0.08, z0 + 0.92, 0.04, 0.04, 0.08, gold), (-0.02, 0.12, z0 + 0.88, 0.04, 0.02, 0.04, glow),
          (0.30, 0.0, z0, 0.04, 0.04, 0.95, (60, 50, 60)), (0.26, -0.04, z0 + 0.95, 0.12, 0.12, 0.12, bone),
          (0.28, 0.08, z0 + 1.0, 0.03, 0.02, 0.04, glow), (0.38, 0.0, z0 + 1.0, 0.02, 0.03, 0.04, glow)]
    for i in range(3):
        a = t * 1.5 + i * 2.09
        P.append((math.cos(a) * 0.45 - 0.05, math.sin(a) * 0.45 - 0.05, z0 + 0.5 + 0.1 * math.sin(t * 3 + i), 0.10, 0.10, 0.10, glow))
    return P


def _mind_flayer(t):
    sk, skD = (156, 112, 196), (112, 78, 152)
    robe, robeD, gold = (66, 34, 100), (42, 22, 68), (244, 204, 70)
    arm = math.sin(t * 2.5) * 0.04
    P = [(-0.24, -0.16, 0.0, 0.48, 0.32, 0.14, robeD), (-0.22, -0.14, 0.14, 0.44, 0.28, 0.22, robe),
         (-0.20, -0.12, 0.36, 0.40, 0.24, 0.26, robe), (-0.04, 0.12, 0.40, 0.08, 0.02, 0.16, gold), (-0.20, 0.12, 0.58, 0.40, 0.02, 0.03, gold),
         (-0.28, -0.20, 0.60, 0.56, 0.06, 0.42, robeD), (-0.28, -0.20, 0.60, 0.06, 0.36, 0.34, robeD),
         (-0.30, -0.06, 0.34 + arm, 0.10, 0.14, 0.26, robe), (0.20, -0.06, 0.34 - arm, 0.10, 0.14, 0.26, robe),
         (-0.30, -0.05, 0.26 + arm, 0.08, 0.10, 0.08, sk), (0.20, -0.05, 0.26 - arm, 0.08, 0.10, 0.08, sk),
         (-0.14, -0.11, 0.62, 0.28, 0.22, 0.24, sk), (-0.12, -0.10, 0.86, 0.24, 0.20, 0.06, skD),
         (-0.10, 0.11, 0.66, 0.20, 0.02, 0.04, (60, 20, 70)),
         (0.28, 0.05, 0.62 + 0.05 * math.sin(t * 3), 0.10, 0.10, 0.10, (255, 130, 255))]
    for i in range(4):
        w = math.sin(t * 3 + i) * 0.02
        for k in range(4):
            P.append((-0.10 + i * 0.07, 0.11 + k * 0.025 + w * k, 0.58 - k * 0.08, 0.05, 0.05, 0.09, skD if k % 2 else sk))
    return P + _face(0.14, 0.11, 0.76, (255, 255, 255), (200, 200, 255), 0.06)


NEW_PARTS = {"kobold": _kobold, "gnoll": _gnoll, "zombie": _zombie, "ogre": _ogre, "owlbear": _owlbear,
             "gelatinous_cube": _cube, "mimic": _mimic, "troll": _troll, "goblin_king": _goblin_king,
             "beholder": _beholder, "minotaur": _minotaur, "lich": _lich, "mind_flayer": _mind_flayer}


parts_enemy_old = parts_enemy


def parts_enemy(kind, t):
    if kind in NEW_PARTS:
        return NEW_PARTS[kind](t)
    return parts_enemy_old(kind, t)


def pose_parts(parts, sx=1.0, sy=1.0, sz=1.0, lean=(0.0, 0.0)):
    """Squash/stretch e inclinação aplicados a todos os voxels."""
    return [(dx * sx + lean[0] * dz, dy * sy + lean[1] * dz, dz * sz, w * sx, d * sy, h * sz, c)
            for dx, dy, dz, w, d, h, c in parts]


def draw_parts_iso(surf, parts, ox, oy, s=1.0, soft=False, key=None):
    cam = (ox - OX, oy - OY)
    if soft:
        draw_world_parts(surf, world_parts(parts, 0.0, 0.0, 0.0, s), cam, ("menu", key), 0.008 * s)
        return
    items = []
    for dx, dy, dz, w, d, h, c in parts:
        x, y, z = dx * s, dy * s, dz * s
        items.append((x + w * s / 2 + y + d * s / 2, z, (x, y, z, w * s, d * s, h * s, c)))
    items.sort(key=lambda i: (round(i[0], 3), i[1]))
    for _, _, (x, y, z, w, d, h, c) in items:
        draw_box(surf, x, y, z, w, d, h, c, cam, True, 0.0)


ENEMY_NAMES = {"slime": "Gosma Verde", "goblin": "Goblin", "bat": "Morcego Gigante", "skeleton": "Esqueleto", "orc": "Orc Bravo",
               "wolfman": "Lobisomem", "ghost": "Fantasma", "golem": "Golem de Pedra",
               "kobold": "Kobold", "gnoll": "Gnoll", "zombie": "Zumbi", "ogre": "Ogro", "owlbear": "Urso-Coruja",
               "gelatinous_cube": "Cubo Gelatinoso", "mimic": "Mímico", "troll": "Troll",
               "goblin_king": "REI GOBLIN GIGANTE", "dragon": "DRAGÃO VERMELHO", "beholder": "BEHOLDER",
               "minotaur": "MINOTAURO", "lich": "LICH", "mind_flayer": "DEVORADOR DE MENTES",
               "goblin_chief": "CHEFE GOBLIN", "werewolf": "LOBISOMEM ALFA", "bat_queen": "RAINHA MORCEGO", "orc_chief": "CHEFE ORC"}
ENEMY_COLOR = {"slime": (80, 200, 90), "goblin": (90, 176, 108), "bat": (102, 118, 150), "skeleton": (230, 230, 214), "orc": (96, 156, 74),
               "wolfman": (150, 116, 100), "ghost": (200, 222, 255), "golem": (140, 140, 150),
               "kobold": (206, 92, 60), "gnoll": (180, 144, 88), "zombie": (122, 152, 112), "ogre": (204, 164, 112),
               "owlbear": (124, 86, 58), "gelatinous_cube": (120, 232, 190), "mimic": (150, 96, 50), "troll": (100, 148, 98),
               "goblin_king": (110, 200, 110), "dragon": (200, 60, 50), "beholder": (164, 70, 124),
               "minotaur": (112, 72, 50), "lich": (130, 90, 190), "mind_flayer": (156, 112, 196),
               "goblin_chief": (72, 140, 88), "werewolf": (120, 110, 106), "bat_queen": (162, 132, 255), "orc_chief": (122, 176, 102)}
ENEMY_SCALE = {"dragon": 1.5, "golem": 1.2, "orc": 1.1, "ogre": 1.3, "owlbear": 1.2, "troll": 1.3, "gelatinous_cube": 1.1,
               "goblin_king": 2.0, "beholder": 1.35, "minotaur": 1.5, "lich": 1.3, "mind_flayer": 1.3}
TIERS = [["slime", "kobold", "goblin", "bat"],
         ["skeleton", "zombie", "gnoll", "wolfman"],
         ["orc", "ghost", "mimic", "gelatinous_cube"],
         ["ogre", "owlbear", "troll", "golem"]]
REG_KINDS = [k for tier_ in TIERS for k in tier_]
BOSS_KINDS = ["goblin_chief", "dragon", "werewolf", "bat_queen", "orc_chief", "goblin_king", "beholder", "minotaur", "lich", "mind_flayer"]


# ======================================================================================
# PACOTE DE MONSTROS v3 (inspirado em Dungeons & Dragons)
# Sprites reconstruídos com mais camadas, sombreamento, animação e detalhes.
# Cada função devolve voxels (x, y, z, w, d, h, cor) no mesmo formato do resto do jogo.
# ======================================================================================
def m_eyes(P, hw, hd, z, ec=WHITE, pc=DARK, sz=0.055):
    P.extend(_face(hw, hd, z, ec, pc, sz))


def m_ring(P, cx, cy, z, rx, ry, n, size, c, t, speed=2.0, bob=0.03):
    for i in range(n):
        a = t * speed + i * math.tau / n
        P.b(cx + math.cos(a) * rx, cy + math.sin(a) * ry, z + bob * math.sin(t * 3 + i), size, size, size, c)


def m_flame(P, cx, cy, z, t, w=0.10, n=3, seed=0):
    cols = ((255, 90, 30), (255, 170, 40), (255, 235, 120))
    for i in range(n):
        f = 0.5 + 0.5 * math.sin(t * 9 + seed + i * 1.7)
        s = w * (1 - 0.25 * i)
        P.b(cx + 0.02 * math.sin(t * 7 + i + seed), cy + 0.02 * math.cos(t * 6 + i), z + i * 0.07 * (0.7 + f * 0.6),
            s, s, 0.08 + 0.05 * f, cols[min(i, 2)])


def m_legs2(P, sw, x, w, d, hf, hs, hk, c, cD, foot):
    """Duas pernas (pé, canela, coxa) que balançam com sw."""
    for s, off in ((-1, sw), (1, -sw)):
        l = max(0.0, off) * 0.05
        P.b(s * x, 0.015, l, w * 1.15, d * 1.4, hf, foot)
        P.b(s * x, 0.0, hf + l, w, d, hs, c)
        P.b(s * x, 0.0, hf + hs + l, w * 1.1, d * 1.05, hk, cD)



def m_wing(P, side, cx, cy, z, n, step, flap, c, cD, bone=None, span=0.07, thick=0.03, droop=0.0):
    """Asa de membrana contínua que sai para os lados (perpendicular à direção do olhar).
    flap = quanto as pontas sobem/descem; bone = cor dos ossos (dedos)."""
    ux, uy = -side * 0.7071, side * 0.7071
    fx, fy = 0.7071, 0.7071
    bone = bone or cD
    for i in range(n):
        r = 0.08 + i * step
        lift = flap * (i / max(1, n - 1)) - droop * (i / max(1, n - 1)) ** 2
        w = span * (1.15 - 0.55 * i / n)
        rows = (-1.0, 0.0, 1.0) if i < n - 2 else (0.0,)
        for rw in rows:
            off = rw * w * 0.95 - (0.03 * i if rw < 0 else 0.0) * 0.0
            px = cx + ux * r + fx * off
            py = cy + uy * r + fy * off
            P.b(px, py, z + lift, w * 1.25, w * 1.25, thick, c if rw else cD)
        P.b(cx + ux * r, cy + uy * r, z + lift + thick * 0.9, 0.035, 0.035, 0.022, bone)

# ------------------------------------------------------------------ TIER 0
def m_ooze(t):
    """Gosma Ácida: pilha de camadas gelatinosas com bolhas, crânio engolido e pingos."""
    sq = 1 + 0.09 * math.sin(t * 4)
    k, wk = 1 / sq, math.sqrt(sq)
    c, cL, cD = (78, 204, 104), (170, 248, 176), (36, 134, 70)
    P = _P()
    z = 0.0
    prof = [(1.00, 0.10), (1.14, 0.10), (1.10, 0.10), (0.96, 0.09), (0.78, 0.08), (0.52, 0.06)]
    for i, (f, h) in enumerate(prof):
        col = cL if i == len(prof) - 1 else (mix(c, 0.10) if i % 2 else c)
        P.b(0, 0, z, 0.62 * f * wk, 0.62 * f * wk, h * k, col)
        z += h * k
    P.b(0.30, 0.30, 0.00, 0.10, 0.10, 0.04, cD)
    P.b(-0.32, 0.20, 0.00, 0.12, 0.08, 0.03, cD)
    P.b(0.20, -0.30, 0.00, 0.08, 0.10, 0.03, cD)
    P.b(0.22, 0.22, 0.10, 0.15, 0.15, 0.14, (238, 234, 216))
    P.b(0.30, 0.30, 0.12, 0.03, 0.03, 0.05, DARK)
    P.b(0.17, 0.30, 0.12, 0.03, 0.03, 0.05, DARK)
    P.b(0.33, 0.13, 0.04, 0.05, 0.05, 0.03, (250, 206, 70))
    for i in range(4):
        u = (t * 0.30 + i * 0.27) % 1.0
        P.b(-0.16 + 0.12 * i - 0.1, -0.12 + 0.06 * i, 0.12 + u * 0.34, 0.05, 0.05, 0.05, mix(c, 0.65))
    P.b(-0.10, -0.10, z - 0.03, 0.14, 0.10, 0.03, WHITE)
    m_eyes(P, 0.345, 0.345, 0.27, WHITE, DARK, 0.075)
    P.b(0.04, 0.345, 0.17, 0.12, 0.02, 0.04, (30, 100, 56))
    return P


def m_kobold(t):
    c, cD, cL = (214, 98, 62), (150, 62, 44), (242, 150, 104)
    bel, horn, leath = (246, 208, 128), (244, 236, 200), (122, 84, 52)
    sw, wag = math.sin(t * 6), math.sin(t * 5)
    P = _P()
    m_legs2(P, sw, 0.07, 0.07, 0.08, 0.05, 0.09, 0.06, c, cD, cD)
    for i in range(6):
        P.b(-0.12 - 0.07 * i + wag * 0.02 * i, -0.12 - 0.07 * i - wag * 0.02 * i, 0.12 + 0.015 * i,
            0.08 - 0.01 * i, 0.08 - 0.01 * i, 0.07 - 0.008 * i, cD if i % 2 else c)
    P.b(0, 0, 0.20, 0.25, 0.19, 0.20, c)
    P.b(0, 0.098, 0.20, 0.15, 0.02, 0.17, bel)
    P.b(0.128, 0, 0.20, 0.02, 0.11, 0.17, bel)
    P.b(0, 0, 0.32, 0.27, 0.21, 0.08, leath)
    P.b(0, 0, 0.20, 0.27, 0.21, 0.03, (80, 56, 36))
    P.b(0.13, 0.11, 0.20, 0.04, 0.04, 0.04, (250, 206, 70))
    P.b(-0.17, 0, 0.22 + sw * 0.03, 0.06, 0.07, 0.16, c)
    P.b(0.17, 0, 0.22 - sw * 0.03, 0.06, 0.07, 0.16, c)
    P.b(0.17, 0.02, 0.19 - sw * 0.03, 0.07, 0.08, 0.05, cL)
    P.b(0.17, 0.10, 0.20 - sw * 0.03, 0.025, 0.14, 0.025, (206, 212, 224))
    P.b(0.17, 0.02, 0.22 - sw * 0.03, 0.05, 0.05, 0.03, leath)
    P.b(0, 0, 0.42, 0.25, 0.21, 0.15, c)
    P.b(0.07, 0.07, 0.44, 0.16, 0.16, 0.08, cL)
    P.b(0.14, 0.14, 0.50, 0.03, 0.03, 0.03, DARK)
    P.b(0.14, 0.08, 0.50, 0.03, 0.03, 0.03, DARK)
    P.b(0.08, 0.14, 0.50, 0.03, 0.03, 0.03, DARK)
    for sx in (-0.07, 0.07):
        P.b(sx, -0.06, 0.56, 0.04, 0.04, 0.10, horn)
    for i in range(3):
        P.b(-0.10 - 0.02 * i, -0.10 - 0.02 * i, 0.54 - 0.04 * i, 0.04, 0.10, 0.05, cD)
    m_eyes(P, 0.125, 0.105, 0.50, (255, 226, 60), DARK, 0.05)
    P.b(0.10, 0.155, 0.43, 0.02, 0.01, 0.03, WHITE)
    return P


# ------------------------------------------------------------------ helpers "chibi" (mesmas proporções do herói)
def _fat(P, cx, cy, hw):
    """Desenha na quina frontal de uma caixa quadrada (faces +x e +y).
    face 0 = +y (esquerda da tela), face 1 = +x (direita da tela); u = distância da quina."""
    def at(face, u, d_off, w, h, zz, col, dep=0.012):
        if face == 0:
            P.b(cx + hw - u - w / 2, cy + hw + d_off, zz, w, dep, h, col)
        else:
            P.b(cx + hw + d_off, cy + hw - u - w / 2, zz, dep, w, h, col)
    return at


def _c_legs(P, sw, boot, pant, sep=0.085, w=0.13, hl=0.075, hb=0.065, lift=0.06, toe=0.03):
    """Duas pernas curtinhas (bota + calça) no mesmo layout do herói."""
    for s, off in ((1, sw), (-1, -sw)):
        l = max(0.0, off) * lift
        cx, cy = sep * s, -sep * s
        P.b(cx, cy, hb - 0.005 + l, w * 0.9, w * 0.9, hl, pant)
        P.b(cx + toe, cy + toe, l, w + 0.02, w + 0.02, hb, boot)


def m_goblin(t):
    """Goblin: baixinho, orelhões pontudos, nariz grande, colete de couro, adaga e saquinho de moedas."""
    sk, skD, skL = (128, 206, 98), (86, 150, 64), (170, 230, 132)
    lea, leaD, cloth = (168, 118, 70), (104, 70, 44), (190, 70, 64)
    metal, gold = (206, 212, 226), (250, 208, 90)
    sw = math.sin(t * 7)
    arm = math.sin(t * 6) * 0.04
    b = abs(math.sin(t * 7)) * 0.012
    P = _P()
    _c_legs(P, sw, leaD, skD, sep=0.08, w=0.12, hl=0.07, hb=0.06)
    # tanga / saia de pano
    P.b(0.0, 0.0, 0.085, 0.29, 0.27, 0.05, cloth)
    P.b(0.12, 0.12, 0.035, 0.09, 0.09, 0.08, cloth)
    P.b(0.12, 0.12, 0.035, 0.09, 0.09, 0.025, shade(cloth, 0.75))
    # tronco: pele + colete de couro
    P.b(0.0, 0.0, 0.11 + b, 0.30, 0.28, 0.26, sk)
    P.b(0.0, 0.0, 0.11 + b, 0.325, 0.30, 0.20, lea)
    P.wrap(0.0, 0.0, 0.325, 0.30, 0.11 + b, 0.04, leaD)
    P.b(0.17, 0.15, 0.13 + b, 0.02, 0.05, 0.05, gold)                       # fivela
    for i in range(3):                                                        # costuras do colete
        P.b(0.164, 0.02 - 0.06 * i, 0.20 + b, 0.014, 0.03, 0.09, shade(lea, 1.25))
        P.b(-0.02 - 0.06 * i + 0.04, 0.152, 0.20 + b, 0.03, 0.014, 0.09, shade(lea, 1.25))
    P.b(0.0, 0.0, 0.31 + b, 0.30, 0.28, 0.05, sk)                           # ombros
    # saquinho de moedas no quadril
    P.b(0.19, -0.13, 0.10 + b, 0.10, 0.10, 0.10, leaD)
    P.b(0.19, -0.13, 0.19 + b, 0.07, 0.07, 0.03, lea)
    P.b(0.245, -0.13, 0.13 + b, 0.014, 0.04, 0.04, gold)
    # braço A (direita da tela): adaga
    ax, ay = 0.19 + arm * 0.7, -0.19 + arm * 0.7
    P.b(ax * 0.97, ay * 0.97, 0.24 + b, 0.085, 0.085, 0.14, sk)
    P.b(ax, ay, 0.19 + b, 0.095, 0.095, 0.075, skD)
    P.b(ax, ay, 0.255 + b, 0.05, 0.05, 0.06, leaD)
    P.b(ax, ay, 0.31 + b, 0.15, 0.05, 0.03, gold)
    for i in range(5):
        P.b(ax + 0.012 * i, ay + 0.012 * i, 0.34 + b + 0.065 * i, 0.05 - 0.006 * i, 0.04, 0.07, metal if i else shade(metal, 0.8))
    # braço B (esquerda da tela): segura uma moeda
    bx, by = -0.19 - arm * 0.7, 0.19 - arm * 0.7
    P.b(bx * 0.97, by * 0.97, 0.24 + b, 0.085, 0.085, 0.14, sk)
    P.b(bx, by, 0.19 + b, 0.095, 0.095, 0.075, skD)
    P.b(bx, by, 0.265 + b + 0.01 * math.sin(t * 5), 0.07, 0.07, 0.015, gold)
    # cabeça grande
    hz = 0.34 + b
    P.b(0.0, 0.0, hz, 0.44, 0.44, 0.30, sk)
    P.b(0.0, 0.0, hz, 0.44, 0.44, 0.04, skD)                                 # queixo sombreado
    P.wrap(0.0, 0.0, 0.44, 0.44, hz + 0.20, 0.04, skD, 0.03)                 # sobrancelha pesada
    # nariz grande e pontudo na quina
    P.b(0.215, 0.215, hz + 0.075, 0.085, 0.085, 0.085, skL)
    P.b(0.262, 0.262, hz + 0.075, 0.05, 0.05, 0.05, skD)
    # orelhões pontudos (um de cada lado), apontando para cima e para fora
    for sgn in (1, -1):
        for i in range(3):
            ex = 0.21 * sgn + 0.05 * sgn * i
            ey = -0.21 * sgn - 0.05 * sgn * i
            sz = 0.10 - 0.022 * i
            P.b(ex, ey, hz + 0.13 + 0.06 * i, sz, sz, 0.075 - 0.01 * i, sk if i < 2 else skL)
        P.b(0.215 * sgn + 0.02 * sgn, -0.215 * sgn - 0.02 * sgn, hz + 0.14, 0.045, 0.045, 0.05, mix(sk, 0.35, (230, 120, 130)))
    at = _fat(P, 0.0, 0.0, 0.22)
    blink = (t % 3.3) < 0.1
    eh = 0.10 * (0.2 if blink else 1.0)
    for face in (0, 1):
        at(face, 0.125, 0.003, 0.095, eh, hz + 0.14, (255, 226, 70), 0.014)
        if not blink:
            at(face, 0.10, 0.008, 0.045, 0.075, hz + 0.152, (188, 30, 30), 0.012)
            at(face, 0.092, 0.012, 0.022, 0.03, hz + 0.19, WHITE, 0.012)
        at(face, 0.095, 0.006, 0.15, 0.028, hz + 0.245, skD, 0.012)          # sobrancelha brava
        at(face, 0.07, 0.002, 0.15, 0.04, hz + 0.045, (82, 32, 40), 0.012)   # boca
        at(face, 0.085, 0.006, 0.032, 0.05, hz + 0.058, WHITE, 0.012)        # presas
        at(face, 0.17, 0.006, 0.032, 0.05, hz + 0.058, WHITE, 0.012)
    # boné de couro curto com pena
    P.b(0.0, 0.0, hz + 0.27, 0.46, 0.46, 0.045, lea)
    P.b(0.0, 0.0, hz + 0.315, 0.36, 0.36, 0.04, leaD)
    P.b(-0.15, -0.15, hz + 0.33 + 0.01 * math.sin(t * 6), 0.05, 0.05, 0.09, (240, 240, 235))
    P.b(-0.18, -0.18, hz + 0.39 + 0.015 * math.sin(t * 6), 0.045, 0.045, 0.06, cloth)
    return P


def m_skeleton(t):
    """Esqueleto guerreiro: crânio grande, costelas, elmo enferrujado, espada velha e escudo de madeira."""
    bone, boneD, boneS = (246, 242, 224), (198, 192, 170), (150, 144, 126)
    dark = (34, 28, 42)
    rust, rustD = (166, 124, 88), (116, 84, 60)
    cloth = (176, 58, 64)
    steel, wood, woodD, gold = (196, 204, 218), (134, 92, 56), (96, 64, 40), (232, 184, 84)
    sw = math.sin(t * 5)
    arm = math.sin(t * 3) * 0.035
    b = math.sin(t * 3) * 0.008
    P = _P()
    # pernas de osso
    for s, off in ((1, sw), (-1, -sw)):
        l = max(0.0, off) * 0.05
        cx, cy = 0.085 * s, -0.085 * s
        P.b(cx + 0.03, cy + 0.03, l, 0.15, 0.15, 0.045, boneD)
        P.b(cx, cy, 0.04 + l, 0.075, 0.075, 0.07, bone)
        P.b(cx, cy, 0.10 + l, 0.105, 0.105, 0.04, boneD)
    # bacia
    P.b(0.0, 0.0, 0.13 + b, 0.31, 0.25, 0.065, boneD)
    P.b(0.0, 0.0, 0.17 + b, 0.28, 0.22, 0.03, bone)
    # caixa torácica: núcleo escuro + costelas por fora
    P.b(0.0, 0.0, 0.19 + b, 0.26, 0.22, 0.24, dark)
    for i in range(4):
        w_ = 0.31 - 0.012 * i
        P.wrap(0.0, 0.0, w_, 0.27 - 0.012 * i, 0.205 + b + 0.056 * i, 0.034, bone, 0.034)
    P.b(0.152, 0.138, 0.20 + b, 0.04, 0.04, 0.22, boneD)                       # esterno na quina
    P.b(0.0, 0.0, 0.405 + b, 0.40, 0.14, 0.04, bone)                           # clavículas
    P.b(0.0, 0.0, 0.405 + b, 0.14, 0.40, 0.04, bone)
    # lenço rasgado no pescoço
    P.wrap(0.0, 0.0, 0.25, 0.21, 0.38 + b, 0.05, cloth, 0.03)
    P.b(0.14, 0.12, 0.30 + b, 0.04, 0.04, 0.09, cloth)
    P.b(0.14, 0.12, 0.27 + b, 0.03, 0.03, 0.04, shade(cloth, 0.7))
    # braço A (direita da tela): espada enferrujada
    ax, ay = 0.215 + arm * 0.7, -0.215 + arm * 0.7
    P.b(ax, ay, 0.395 + b, 0.095, 0.095, 0.09, boneD)                           # ombro
    P.b(ax, ay, 0.285 + b, 0.058, 0.058, 0.11, bone)                            # úmero
    P.b(ax, ay, 0.22 + b, 0.052, 0.052, 0.07, bone)                             # antebraço
    P.b(ax, ay, 0.165 + b, 0.085, 0.085, 0.06, boneD)                           # mão
    P.b(ax, ay, 0.19 + b, 0.05, 0.05, 0.07, woodD)
    P.b(ax, ay, 0.25 + b, 0.15, 0.05, 0.03, gold)
    for i in range(6):
        P.b(ax + 0.012 * i, ay + 0.012 * i, 0.28 + b + 0.07 * i, 0.055, 0.04, 0.075,
            rust if i < 2 else (steel if i < 5 else (236, 240, 250)))
    # braço B (esquerda da tela): escudo de madeira
    bx, by = -0.215 - arm * 0.7, 0.215 - arm * 0.7
    P.b(bx, by, 0.395 + b, 0.095, 0.095, 0.09, boneD)
    P.b(bx, by, 0.285 + b, 0.058, 0.058, 0.11, bone)
    P.b(bx, by, 0.22 + b, 0.052, 0.052, 0.07, bone)
    P.b(bx, by, 0.165 + b, 0.085, 0.085, 0.06, boneD)
    P.b(bx - 0.01, by + 0.09, 0.15 + b, 0.25, 0.045, 0.29, steel)
    P.b(bx - 0.01, by + 0.113, 0.17 + b, 0.20, 0.03, 0.25, wood)
    P.b(bx - 0.01, by + 0.113, 0.21 + b, 0.20, 0.032, 0.03, woodD)
    P.b(bx - 0.01, by + 0.113, 0.28 + b, 0.20, 0.032, 0.03, woodD)
    P.b(bx - 0.01, by + 0.132, 0.245 + b, 0.075, 0.03, 0.075, gold)
    # crânio
    hz = 0.42 + b
    P.b(0.0, 0.0, hz + 0.09, 0.46, 0.46, 0.25, bone)
    P.b(0.0, 0.0, hz, 0.40, 0.40, 0.095, boneD)                                 # mandíbula
    P.b(0.0, 0.0, hz + 0.34, 0.40, 0.40, 0.012, boneS)
    at = _fat(P, 0.0, 0.0, 0.23)
    aj = _fat(P, 0.0, 0.0, 0.20)
    for face in (0, 1):
        at(face, 0.115, 0.003, 0.115, 0.125, hz + 0.145, dark, 0.016)             # órbita
        at(face, 0.095, 0.010, 0.05, 0.06, hz + 0.165, (255, 70, 56), 0.014)      # olho em brasa
        at(face, 0.088, 0.014, 0.02, 0.025, hz + 0.205, (255, 214, 190), 0.012)
        at(face, 0.0, 0.003, 0.04, 0.05, hz + 0.105, dark, 0.014)                 # buraco do nariz
        for k in range(4):                                                         # dentes
            aj(face, 0.012 + 0.045 * k, 0.004, 0.034, 0.05, hz + 0.03, WHITE if k % 2 == 0 else boneD, 0.012)
        aj(face, 0.0, 0.002, 0.18, 0.012, hz + 0.075, dark, 0.012)                # fenda da boca
    at(1, 0.20, 0.004, 0.014, 0.09, hz + 0.20, boneS, 0.012)                      # rachaduras
    at(1, 0.185, 0.004, 0.04, 0.012, hz + 0.255, boneS, 0.012)
    at(0, 0.03, 0.004, 0.014, 0.07, hz + 0.20, boneS, 0.012)
    # elmo velho e enferrujado
    P.b(0.0, 0.0, hz + 0.275, 0.50, 0.50, 0.07, rust)
    P.b(0.0, 0.0, hz + 0.335, 0.42, 0.42, 0.065, rustD)
    P.b(0.0, 0.0, hz + 0.395, 0.06, 0.06, 0.06, rust)
    P.b(0.15, 0.15, hz + 0.275, 0.06, 0.06, 0.07, rustD)                          # amassado
    for i in range(3):                                                             # tirinha de pano ao vento
        wv = math.sin(t * 5 - i * 0.9) * 0.03
        P.b(-0.20 - 0.06 * i + wv, -0.20 - 0.06 * i - wv, hz + 0.31 - 0.03 * i, 0.07, 0.07, 0.055, shade(cloth, 1.0 - 0.1 * i))
    return P


def m_zombie(t):
    """Zumbi: pele esverdeada, farrapos, braços esticados para a frente, olho saltado e boca ensanguentada."""
    sk, skD, skL = (150, 186, 128), (104, 142, 92), (182, 214, 154)
    rag, ragD, ragL = (170, 142, 106), (112, 88, 64), (214, 190, 152)
    pant, pantD = (82, 96, 146), (56, 66, 108)
    blood, bone, hair = (160, 34, 42), (234, 226, 200), (62, 72, 50)
    sw = math.sin(t * 2.6)
    sway = math.sin(t * 2.2) * 0.022
    b = math.sin(t * 2.2) * 0.012
    P = _P()
    # pernas: uma bota/pé descalço arrastando
    for s, off in ((1, sw), (-1, -sw)):
        l = max(0.0, off) * 0.045
        cx, cy = 0.085 * s, -0.085 * s
        P.b(cx, cy, 0.06 + l, 0.12, 0.12, 0.075 if s > 0 else 0.055, pant if s > 0 else pantD)
        P.b(cx + 0.03, cy + 0.03, l, 0.15, 0.15, 0.065, skD if s > 0 else ragD)
    P.b(0.085 + 0.02, -0.085 + 0.02, 0.095, 0.125, 0.125, 0.025, shade(pant, 0.7))   # barra rasgada
    P.b(-0.085, 0.085 + 0.05, 0.015, 0.04, 0.05, 0.03, skL)                          # dedos do pé
    # tronco rasgado
    P.b(0.0, 0.0, 0.12 + b, 0.34, 0.32, 0.30, rag)
    P.b(0.0, 0.0, 0.12 + b, 0.35, 0.33, 0.05, ragD)
    at = _fat(P, 0.0, 0.0, 0.165)
    at(1, 0.07, 0.004, 0.13, 0.13, 0.20 + b, skD, 0.016)                              # rasgo mostrando a pele
    for k in range(3):
        at(1, 0.085 + 0.035 * k, 0.010, 0.014, 0.10, 0.215 + b, bone, 0.012)           # costelas à mostra
    at(1, 0.07, 0.011, 0.13, 0.025, 0.20 + b, blood, 0.012)
    at(0, 0.03, 0.004, 0.10, 0.07, 0.30 + b, ragL, 0.014)                              # remendo
    at(0, 0.12, 0.004, 0.10, 0.12, 0.17 + b, blood, 0.010)                             # mancha de sangue
    for i, hh in enumerate((0.05, 0.03, 0.06, 0.035)):                                 # barra esfarrapada
        P.b(0.16 - 0.095 * i * 0.7, 0.15 - 0.0, 0.12 + b - hh * 0.5, 0.07, 0.03, hh, ragD)
    P.wrap(0.0, 0.0, 0.34, 0.32, 0.17 + b, 0.035, (96, 72, 50))                         # cordão na cintura
    P.b(0.175, 0.16, 0.17 + b, 0.03, 0.04, 0.05, (96, 72, 50))
    # braços esticados para a frente (+x,+y), balançando
    for side, ph in ((1, 0.0), (-1, 2.2)):
        sx0, sy0 = 0.215 * side, -0.215 * side
        up = math.sin(t * 2.6 + ph) * 0.03
        P.b(sx0, sy0, 0.285 + b, 0.105, 0.105, 0.12, rag)                              # manga rasgada
        for i in range(1, 5):
            col = rag if i == 1 else (skD if i == 2 else sk)
            P.b(sx0 + 0.065 * i, sy0 + 0.065 * i, 0.31 + b + up + 0.006 * i, 0.095, 0.095, 0.09 if i < 4 else 0.08, col)
        hx, hy, hz_ = sx0 + 0.30, sy0 + 0.30, 0.315 + b + up
        for k in (-1, 0, 1):                                                           # dedos
            P.b(hx + 0.03 + k * 0.026, hy + 0.03 - k * 0.026, hz_ + 0.01, 0.03, 0.03, 0.03, skL)
        P.b(sx0 + 0.13, sy0 + 0.13, 0.405 + b + up, 0.03, 0.03, 0.025, bone if side > 0 else blood)   # osso exposto / sangue
    # cabeça
    hx_, hy_ = 0.03 + sway, 0.03 + sway
    hz = 0.42 + b
    P.b(hx_, hy_, hz, 0.46, 0.44, 0.33, sk)
    P.b(hx_, hy_, hz, 0.46, 0.44, 0.04, skD)
    atH = _fat(P, hx_, hy_, 0.22)
    # olho esquerdo da tela: fundo e fundo escuro; olho direito: grande e saltado
    atH(0, 0.095, 0.003, 0.11, 0.07, hz + 0.135, (80, 70, 90), 0.014)                  # olheira
    atH(0, 0.105, 0.006, 0.08, 0.075, hz + 0.18, (255, 248, 140), 0.014)
    atH(0, 0.09, 0.010, 0.04, 0.05, hz + 0.19, (170, 24, 24), 0.012)
    atH(1, 0.09, 0.003, 0.11, 0.07, hz + 0.135, (80, 70, 90), 0.014)
    atH(1, 0.10, 0.008, 0.10, 0.11, hz + 0.165, (255, 248, 140), 0.016)
    atH(1, 0.085, 0.014, 0.05, 0.07, hz + 0.185, (170, 24, 24), 0.014)
    atH(1, 0.078, 0.018, 0.022, 0.03, hz + 0.225, WHITE, 0.012)
    for face in (0, 1):
        atH(face, 0.05, 0.003, 0.17, 0.06, hz + 0.04, (74, 26, 34), 0.012)            # boca aberta
        atH(face, 0.07, 0.007, 0.035, 0.03, hz + 0.075, (222, 214, 190), 0.012)        # dentes tortos
        atH(face, 0.125, 0.007, 0.035, 0.025, hz + 0.075, (210, 200, 172), 0.012)
        atH(face, 0.09, 0.008, 0.03, 0.05, hz + 0.0, blood, 0.012)                     # baba de sangue
        atH(face, 0.0, 0.002, 0.04, 0.05, hz + 0.115, skD, 0.012)                      # nariz podre
    # cabelo ralo, curativo e crânio exposto
    P.b(hx_, hy_, hz + 0.31, 0.46, 0.44, 0.03, skD)
    P.b(hx_ - 0.10, hy_ - 0.06, hz + 0.34, 0.10, 0.10, 0.07, hair)
    P.b(hx_ + 0.05 + 0.1 * 0, hy_ - 0.12, hz + 0.34, 0.06, 0.06, 0.09 + 0.01 * math.sin(t * 3), hair)
    P.b(hx_ - 0.14, hy_ + 0.08, hz + 0.34, 0.07, 0.07, 0.06, hair)
    P.b(hx_ + 0.12, hy_ + 0.10, hz + 0.34, 0.12, 0.10, 0.035, bone)                   # crânio à mostra
    P.wrap(hx_, hy_, 0.46, 0.44, hz + 0.235, 0.05, ragL, 0.03)                          # atadura na testa
    P.b(hx_ - 0.24, hy_ - 0.20, hz + 0.235, 0.05, 0.05, 0.10 + 0.01 * math.sin(t * 4), ragL)
    return P


def m_bat(t):
    """Morcego Gigante v4: tronco peludo com peito claro, orelhões, presas, garras e asas em 'V'
    (a ponta sobe e desce no bater) com membrana grossa e ossos mais claros na borda."""
    wing, wingD, bone = (124, 118, 186), (72, 64, 126), (196, 188, 232)
    fur, furL, furD = (98, 90, 132), (138, 128, 172), (60, 54, 90)
    eye, pink = (255, 226, 110), (240, 170, 200)
    fl = math.sin(t * 9)
    z0 = 0.34 + 0.05 * math.sin(t * 3 + 1.0)
    P = _P()
    P.b(0, 0, z0, 0.26, 0.24, 0.22, fur)                      # tronco
    P.b(0.07, 0.07, z0 + 0.03, 0.16, 0.16, 0.15, furL)        # peito claro
    P.b(-0.11, -0.11, z0, 0.14, 0.14, 0.14, furD)             # traseira
    for sd in (-1, 1):                                        # pezinhos com garras
        fx, fy = -0.03 + sd * 0.05, -0.03 - sd * 0.05
        P.b(fx, fy, z0 - 0.09, 0.045, 0.045, 0.10, furD)
        P.b(fx + 0.02, fy + 0.02, z0 - 0.11, 0.03, 0.03, 0.03, (230, 224, 210))
    P.b(0, 0, z0 + 0.22, 0.26, 0.24, 0.18, fur)               # cabeça
    P.b(0.10, 0.10, z0 + 0.25, 0.10, 0.10, 0.07, furL)        # focinho
    P.b(0.152, 0.152, z0 + 0.285, 0.035, 0.035, 0.03, (44, 30, 52))   # nariz
    P.b(0.152, 0.075, z0 + 0.235, 0.022, 0.022, 0.05, WHITE)  # presas
    P.b(0.075, 0.152, z0 + 0.235, 0.022, 0.022, 0.05, WHITE)
    for sd in (-1, 1):                                        # orelhões pontudos
        ex, ey = -0.03 + sd * 0.062, -0.03 - sd * 0.062
        P.b(ex, ey, z0 + 0.39, 0.075, 0.075, 0.17, fur)
        P.b(ex + 0.012, ey + 0.012, z0 + 0.42, 0.045, 0.045, 0.11, pink)
        P.b(ex, ey, z0 + 0.56, 0.04, 0.04, 0.05, furD)
    for side in (1, -1):
        m_wing(P, side, 0, 0, z0 + 0.10, 7, 0.095, 0.10 + 0.24 * fl, wing, wingD, bone, 0.10, 0.042, 0.06)
    m_eyes(P, 0.13, 0.12, z0 + 0.30, eye, (170, 30, 40), 0.055)
    return P


def m_stirge(t):
    """Estirge v4: mosquito gigante - olhos compostos vermelhos, tromba longa com ponta de sangue,
    abdômen listrado que balança, seis perninhas e dois pares de asas translúcidas batendo rápido."""
    fl = math.sin(t * 24)
    z0 = 0.44 + 0.06 * math.sin(t * 3)
    c, cD, cL, wing = (178, 84, 62), (104, 46, 42), (216, 130, 96), (232, 226, 246)
    sway = 0.02 * math.sin(t * 3)
    P = _P()
    P.b(0, 0, z0, 0.22, 0.20, 0.20, c)                        # tórax
    P.b(0.05, 0.05, z0 + 0.04, 0.14, 0.14, 0.13, cL)          # dorso claro
    for i in range(4):                                        # abdômen listrado em curva descendente
        k = 0.11 + 0.075 * i
        P.b(-k - sway * i, -k + sway * i, z0 - 0.02 - 0.035 * i, 0.17 - 0.025 * i, 0.15 - 0.025 * i, 0.14 - 0.012 * i,
            cD if i % 2 else c)
    P.b(0.03, 0.03, z0 + 0.19, 0.20, 0.18, 0.15, c)           # cabeça
    for sd in (-1, 1):                                        # olhões compostos
        P.b(0.03 + sd * 0.085, 0.03 - sd * 0.085, z0 + 0.22, 0.075, 0.075, 0.085, (232, 60, 56))
        P.b(0.03 + sd * 0.085 + 0.02, 0.03 - sd * 0.085 + 0.02, z0 + 0.26, 0.025, 0.025, 0.03, (255, 200, 190))
    for i in range(6):                                        # tromba comprida
        P.b(0.13 + 0.05 * i, 0.13 + 0.05 * i, z0 + 0.22 - 0.022 * i, 0.05 - 0.0035 * i, 0.05 - 0.0035 * i, 0.045,
            (236, 228, 214) if i < 5 else (255, 70, 64))
    for k in range(3):                                        # perninhas pendentes
        for sd in (-1, 1):
            P.b(-0.03 + 0.05 * k + sd * 0.07, 0.03 - 0.05 * k - sd * 0.07, z0 - 0.17, 0.022, 0.022, 0.19, cD)
    for side, base in ((1, 0.20), (-1, 0.20)):                # dois pares de asas (cima grande, baixo pequeno)
        m_wing(P, side, -0.03, -0.03, z0 + 0.19, 5, 0.085, 0.10 + fl * 0.16, wing, mix(wing, 0.0, ), (150, 140, 180), 0.065, 0.03, 0.0)
        m_wing(P, side, -0.08, -0.08, z0 + 0.14, 3, 0.07, 0.04 - fl * 0.12, mix(wing, 0.1, (180, 170, 210)), wing, (150, 140, 180), 0.045, 0.026, 0.0)
    return P


# ------------------------------------------------------------------ TIER 1
def m_gnoll(t):
    fur, spot, mane, bone = (190, 150, 90), (112, 78, 46), (80, 52, 34), (236, 230, 212)
    sw, arm = math.sin(t * 6), math.sin(t * 5) * 0.04
    P = _P()
    m_legs2(P, sw, 0.09, 0.10, 0.12, 0.05, 0.14, 0.10, fur, spot, spot)
    P.b(0, 0, 0.28, 0.38, 0.22, 0.06, (150, 44, 44))
    P.b(0, 0, 0.32, 0.38, 0.24, 0.26, fur)
    for i in range(3):
        P.b(0.0, 0.13, 0.36 + 0.07 * i, 0.30 - 0.04 * i, 0.02, 0.035, bone)
    P.b(0.19, 0.0, 0.40, 0.02, 0.12, 0.05, spot)
    P.b(-0.06, 0.12, 0.50, 0.05, 0.02, 0.05, spot)
    P.b(0.0, 0, 0.56, 0.42, 0.26, 0.06, (110, 80, 54))
    P.b(-0.24, 0.0, 0.34 + arm, 0.09, 0.12, 0.26, fur)
    P.b(0.24, 0.0, 0.34 - arm, 0.09, 0.12, 0.26, fur)
    P.b(0.24, 0.03, 0.30 - arm, 0.10, 0.13, 0.05, spot)
    P.b(0.24, 0.10, 0.10 - arm, 0.04, 0.04, 0.44, (120, 84, 50))
    P.b(0.24, 0.10, 0.52 - arm, 0.06, 0.06, 0.14, (196, 202, 214))
    P.b(0.24, 0.10, 0.64 - arm, 0.035, 0.035, 0.06, (230, 236, 244))
    P.b(0, -0.02, 0.62, 0.26, 0.22, 0.17, fur)
    P.b(0.08, 0.08, 0.62, 0.17, 0.17, 0.09, (96, 66, 46))
    P.b(0.15, 0.15, 0.68, 0.06, 0.06, 0.04, DARK)
    P.b(0.10, 0.10, 0.61, 0.15, 0.02, 0.02, WHITE)
    for sx in (-0.10, 0.10):
        P.b(sx, -0.05, 0.78, 0.07, 0.04, 0.10, spot)
    for i in range(5):
        P.b(-0.06 - 0.02 * i, -0.10 - 0.02 * i, 0.82 - 0.04 * i, 0.06, 0.06, 0.12 - 0.01 * i, mane)
    P.b(0.02, 0.06, 0.74, 0.04, 0.04, 0.04, spot)
    m_eyes(P, 0.13, 0.11, 0.70, (255, 220, 60), (160, 30, 30), 0.05)
    return P


def m_wolfman(t):
    """Lobisomem: grandão, corcunda, focinho comprido, juba, garras enormes e rabo peludo."""
    fur, furD, furL = (132, 116, 108), (84, 72, 70), (186, 168, 148)
    belly, claw, pants = (214, 198, 172), (240, 232, 206), (96, 72, 58)
    eye, tongue = (255, 214, 60), (206, 70, 84)
    sw = math.sin(t * 6)
    arm = math.sin(t * 5) * 0.045
    b = abs(math.sin(t * 3)) * 0.014
    breathe = math.sin(t * 3) * 0.012
    P = _P()
    # pernas fortes com patas grandes e garras
    for s, off in ((1, sw), (-1, -sw)):
        l = max(0.0, off) * 0.05
        cx, cy = 0.095 * s, -0.095 * s
        P.b(cx + 0.04, cy + 0.04, l, 0.18, 0.18, 0.06, furD)
        for k in (-1, 0, 1):
            P.b(cx + 0.13 + 0.0, cy + 0.13 - 0.0 + 0.045 * k * 0, l, 0.03, 0.03, 0.03, claw) if k == 0 else None
        P.b(cx, cy, 0.055 + l, 0.14, 0.14, 0.085, fur)
    P.b(0.0, 0.0, 0.10, 0.36, 0.32, 0.07, pants)                              # calça rasgada
    P.b(0.17, 0.15, 0.06, 0.07, 0.07, 0.07, pants)
    P.b(0.0, 0.0, 0.07, 0.30, 0.28, 0.04, furD)
    # peito largo, barriga clara e costas peludas
    P.b(0.0, 0.0, 0.15 + b, 0.38, 0.34, 0.20, fur)
    P.b(0.0, 0.0, 0.32 + b + breathe, 0.44, 0.38, 0.17, furD)
    at = _fat(P, 0.0, 0.0, 0.17)
    at(0, 0.03, 0.004, 0.20, 0.17, 0.17 + b, belly, 0.014)
    at(1, 0.03, 0.004, 0.20, 0.17, 0.17 + b, belly, 0.014)
    for k in range(3):                                                        # pelos do peito
        P.b(0.20 - 0.04 * k, 0.20 - 0.04 * k, 0.30 + b - 0.0 * k, 0.07, 0.07, 0.10, furL)
    P.wrap(0.0, 0.0, 0.40, 0.35, 0.28 + b, 0.04, pants, 0.02)
    # braços longos com garras
    for side, ph in ((1, 0.0), (-1, math.pi)):
        a = math.sin(t * 5 + ph) * 0.045
        ax, ay = 0.27 * side + a * 0.7, -0.27 * side + a * 0.7
        P.b(ax, ay, 0.40 + b, 0.15, 0.15, 0.10, furD)                         # ombro
        P.b(ax, ay, 0.26 + b, 0.12, 0.12, 0.16, fur)
        P.b(ax, ay, 0.17 + b, 0.14, 0.14, 0.10, furD)                         # punho
        for k in (-1, 0, 1):
            P.b(ax + 0.03 + 0.0, ay + 0.03 + 0.04 * k * 0.7 - 0.0, 0.10 + b, 0.03, 0.03, 0.08, claw)
        for k in (-1, 1):
            P.b(ax + 0.05 * k * 0.7 + 0.05, ay - 0.05 * k * 0.7 + 0.05, 0.11 + b, 0.03, 0.03, 0.07, claw)
    # rabo peludo (atrás)
    for i in range(5):
        wv = math.sin(t * 4 - i * 0.8) * 0.03
        P.b(-0.20 - 0.06 * i + wv, -0.20 - 0.06 * i - wv, 0.20 + 0.035 * i + b, 0.12 - 0.012 * i, 0.12 - 0.012 * i, 0.11,
            furL if i == 4 else (fur if i % 2 else furD))
    # juba em volta do pescoço
    P.b(0.0, 0.0, 0.46 + b, 0.46, 0.42, 0.07, furL)
    P.wrap(0.0, 0.0, 0.46, 0.42, 0.46 + b, 0.07, furL, 0.04)
    # cabeça de lobo
    hz = 0.50 + b
    P.b(0.0, 0.0, hz, 0.40, 0.40, 0.30, fur)
    P.b(0.0, 0.0, hz + 0.26, 0.40, 0.40, 0.045, furD)
    # focinho comprido na quina + mandíbula aberta
    P.b(0.255, 0.255, hz + 0.075, 0.17, 0.17, 0.13, furL)
    P.b(0.255, 0.255, hz + 0.19, 0.15, 0.15, 0.03, fur)
    P.b(0.355, 0.355, hz + 0.14, 0.065, 0.065, 0.065, (28, 24, 32))          # nariz
    jaw = 0.5 + 0.5 * math.sin(t * 3)
    P.b(0.245, 0.245, hz + 0.0 - 0.02 * jaw, 0.15, 0.15, 0.045, furD)
    P.b(0.255, 0.255, hz + 0.05 - 0.01 * jaw, 0.12, 0.12, 0.03, (84, 24, 34))
    P.b(0.285, 0.285, hz + 0.045, 0.05, 0.05, 0.02, tongue)
    atM = _fat(P, 0.255, 0.255, 0.085)
    for face in (0, 1):
        for k in (0, 1):
            atM(face, 0.01 + 0.075 * k, 0.012, 0.025, 0.05, hz + 0.058, WHITE, 0.012)        # presas
            atM(face, 0.04 + 0.05 * k, 0.012, 0.02, 0.035, hz + 0.047 - 0.02 * jaw, WHITE, 0.012)
    # olhos amarelos com pupila de fenda e sobrancelha brava
    ah = _fat(P, 0.0, 0.0, 0.20)
    for face in (0, 1):
        ah(face, 0.075, 0.004, 0.09, 0.09, hz + 0.145, eye, 0.016)
        ah(face, 0.105, 0.010, 0.02, 0.09, hz + 0.145, DARK, 0.014)
        ah(face, 0.06, 0.008, 0.13, 0.03, hz + 0.235, furD, 0.014)
    # orelhas pontudas
    for sgn in (1, -1):
        ex, ey = 0.12 * sgn + 0.09, -0.12 * sgn + 0.09
        P.b(0.15 * sgn - 0.02, -0.15 * sgn - 0.02, hz + 0.30, 0.11, 0.11, 0.08, furD)
        P.b(0.15 * sgn - 0.02, -0.15 * sgn - 0.02, hz + 0.37, 0.08, 0.08, 0.07, fur)
        P.b(0.15 * sgn - 0.02, -0.15 * sgn - 0.02, hz + 0.43, 0.045, 0.045, 0.05, furD)
        P.b(0.15 * sgn - 0.005, -0.15 * sgn - 0.005, hz + 0.31, 0.04, 0.04, 0.07, (222, 140, 150))
    return P


# ------------------------------------------------------------------ utilidades de quadrúpedes
def dp(a, s=0.0):
    """Quadrúpedes ficam de perfil: 'a' = ao longo do corpo (+x é a frente), 's' = para o lado (+y mostra o flanco)."""
    return (a, s)


def m_quad(P, t, c, cD, cL, body_len=0.52, bw=0.26, bh=0.24, lh=0.20, lw=0.08, legs=None, walk=6.0, foot=None):
    legs = legs or ((-0.22, -0.11), (-0.22, 0.11), (0.22, -0.11), (0.22, 0.11))
    for i, (a, s) in enumerate(legs):
        sw = math.sin(t * walk + (0.0 if ((a > 0) == (s > 0)) else math.pi) + i * 0.4)
        l = max(0.0, sw) * 0.06
        x, y = dp(a, s)
        P.b(x, y, l, lw * 1.35, lw * 1.35, 0.04, foot or cD)
        P.b(x, y, 0.04 + l, lw, lw, lh - 0.04, cD)
        P.b(x, y, lh - 0.04 + l, lw * 1.45, lw * 1.45, 0.10, c)
    n = 3
    for k in range(n):
        a = -body_len / 2 + body_len * k / (n - 1)
        x, y = dp(a)
        P.b(x, y, lh + 0.04, bw, bw, bh, c)
        P.b(x, y, lh + 0.04 + bh - 0.01, bw * 0.78, bw * 0.78, 0.04, cL)


# ------------------------------------------------------------------ TIER 2
def m_orc(t):
    skin, skinD, leath = (108, 168, 80), (74, 124, 56), (112, 76, 46)
    metal, metalL, bone, red = (138, 144, 158), (196, 202, 216), (240, 238, 224), (196, 44, 44)
    sw, arm = math.sin(t * 5), math.sin(t * 3) * 0.03
    P = _P()
    m_legs2(P, sw, 0.12, 0.14, 0.16, 0.06, 0.13, 0.10, (88, 62, 42), leath, (58, 42, 30))
    P.b(0, 0, 0.30, 0.52, 0.34, 0.07, leath)
    P.b(0.26, 0.06, 0.28, 0.06, 0.07, 0.08, bone)
    P.b(0.06, 0.17, 0.28, 0.07, 0.06, 0.08, bone)
    P.b(0, 0, 0.37, 0.56, 0.36, 0.30, skin)
    P.b(0, 0.185, 0.40, 0.36, 0.02, 0.24, metal)
    P.b(0.285, 0, 0.40, 0.02, 0.22, 0.24, metal)
    for i in range(3):
        P.b(0, 0.195, 0.44 + 0.07 * i, 0.30, 0.01, 0.025, metalL)
    P.b(-0.10, 0.20, 0.50, 0.03, 0.02, 0.17, leath)
    P.b(0.10, 0.20, 0.50, 0.03, 0.02, 0.17, leath)
    for s_ in (-1, 1):
        P.b(s_ * 0.38, 0, 0.62, 0.18, 0.30, 0.09, metal)
        P.b(s_ * 0.38, 0, 0.70, 0.07, 0.07, 0.10, bone)
        P.b(s_ * 0.38, -0.01, 0.34 - s_ * arm, 0.12, 0.16, 0.28, skin)
        P.b(s_ * 0.38, 0.0, 0.28 - s_ * arm, 0.14, 0.18, 0.08, skinD)
    P.b(0, 0, 0.67, 0.36, 0.30, 0.20, skin)
    P.b(0.10, 0.10, 0.67, 0.20, 0.20, 0.08, skinD)
    P.b(0.17, 0.20, 0.72, 0.035, 0.035, 0.09, bone)
    P.b(0.20, 0.17, 0.72, 0.035, 0.035, 0.09, bone)
    P.b(0.0, 0.16, 0.76, 0.22, 0.01, 0.03, red)
    P.b(0, 0, 0.84, 0.38, 0.32, 0.06, metal)
    P.b(0, 0, 0.90, 0.20, 0.18, 0.05, metalL)
    for s_ in (-1, 1):
        P.b(s_ * 0.22, 0, 0.88, 0.05, 0.05, 0.14, bone)
        P.b(s_ * 0.27, 0, 1.00, 0.04, 0.04, 0.07, bone)
    P.b(0.50, 0.16, 0.08 - arm, 0.05, 0.05, 0.84, leath)
    P.b(0.50, 0.16, 0.74 - arm, 0.05, 0.30, 0.24, (180, 186, 202))
    P.b(0.50, 0.32, 0.78 - arm, 0.05, 0.05, 0.16, metalL)
    P.b(0.50, 0.00, 0.82 - arm, 0.06, 0.08, 0.09, metal)
    m_eyes(P, 0.185, 0.155, 0.76, (255, 232, 60), (200, 30, 30), 0.06)
    return P


def m_ghost(t):
    """Espectro encapuzado, com cauda de névoa, correntes e luzes fantasmas."""
    z0 = 0.30 + 0.06 * math.sin(t * 3)
    c, cD, cL, glow = (206, 226, 255), (140, 170, 228), (238, 248, 255), (120, 236, 255)
    sw = math.sin(t * 2) * 0.02
    P = _P()
    for i in range(6):
        a = i * math.tau / 6
        h = 0.14 + 0.08 * math.sin(t * 5 + i * 1.4)
        P.b(math.cos(a) * 0.17, math.sin(a) * 0.17, z0 - h, 0.12, 0.12, h, cD if i % 2 else c)
        P.b(math.cos(a) * 0.17, math.sin(a) * 0.17, z0 - h - 0.07, 0.07, 0.07, 0.07, mix(c, 0.5))
    for i, (wd, h) in enumerate([(0.48, 0.14), (0.46, 0.14), (0.42, 0.12), (0.40, 0.12), (0.36, 0.10)]):
        P.b(sw * i * 0.3, 0, z0 + sum(x[1] for x in [(0.48, 0.14), (0.46, 0.14), (0.42, 0.12), (0.40, 0.12), (0.36, 0.10)][:i]), wd, wd * 0.9, h, c if i % 2 == 0 else mix(c, 0.1))
    zt = z0 + 0.62
    P.b(sw, 0, zt, 0.40, 0.36, 0.14, c)
    P.b(sw, 0, zt + 0.14, 0.30, 0.28, 0.08, cL)
    P.b(sw, 0, zt + 0.22, 0.16, 0.16, 0.05, cL)
    P.b(0, 0.185, zt + 0.02, 0.24, 0.02, 0.16, (14, 18, 40))
    P.b(0.205, 0, zt + 0.02, 0.02, 0.22, 0.16, (14, 18, 40))
    m_eyes(P, 0.15, 0.13, zt + 0.07, glow, (255, 255, 255), 0.055)
    for s_ in (1, -1):
        r = math.sin(t * 4 + s_) * 0.04
        P.b(0.30 * s_ * 0.9, 0.04, z0 + 0.30 + r, 0.10, 0.28, 0.10, cD)
        for k in range(3):
            P.b(0.30 * s_ * 0.9 + (k - 1) * 0.03, 0.22, z0 + 0.28 + r, 0.02, 0.10, 0.03, cL)
    for i in range(5):
        P.b(0.02 + 0.07 * (i % 2), 0.20 + 0.0, z0 + 0.42 - 0.06 * i, 0.06, 0.02, 0.05, (120, 126, 150))
    m_ring(P, 0, 0, z0 + 0.40, 0.46, 0.46, 3, 0.07, glow, t, 2.0, 0.06)
    return P


def m_mimic(t):
    wood, woodD, lid, band = (156, 100, 52), (108, 68, 36), (186, 124, 66), (92, 92, 108)
    tongue, gold = (222, 72, 98), (252, 210, 72)
    o = 0.18 * (0.5 + 0.5 * math.sin(t * 4)) + 0.04
    hop = max(0.0, math.sin(t * 4)) * 0.03
    P = _P()
    for sx, sy in ((-0.30, -0.20), (0.30, -0.20), (-0.30, 0.20), (0.30, 0.20)):
        P.b(sx, sy, hop, 0.12, 0.12, 0.12, woodD)
        P.b(sx, sy, 0.0, 0.14, 0.14, 0.03, (70, 46, 26))
    P.b(0, 0, 0.12 + hop, 0.80, 0.56, 0.30, wood)
    P.b(0, 0, 0.12 + hop, 0.82, 0.58, 0.04, band)
    P.b(0, 0, 0.38 + hop, 0.82, 0.58, 0.04, band)
    for s_ in (-0.26, 0.26):
        P.b(s_, 0, 0.12 + hop, 0.06, 0.58, 0.30, band)
    P.b(0, 0.295, 0.22 + hop, 0.12, 0.02, 0.14, gold)
    P.b(0.415, 0, 0.22 + hop, 0.02, 0.12, 0.14, gold)
    P.b(0, 0.31, 0.26 + hop, 0.03, 0.01, 0.06, DARK)
    P.b(0, 0, 0.42 + hop, 0.72, 0.48, 0.03, (104, 22, 42))
    for i in range(5):
        P.b(-0.26 + 0.11 * i, -0.04 + 0.05 * (i % 3), 0.45 + hop, 0.06, 0.06, 0.03, gold)
    P.b(0.10, 0.10, 0.45 + hop, 0.22, 0.34, 0.04, tongue)
    P.b(0.10, 0.28, 0.46 + hop, 0.12, 0.10, 0.04, mix(tongue, 0.2))
    for i in range(6):
        P.b(-0.30 + i * 0.12, 0.28, 0.45 + hop, 0.055, 0.05, 0.11, WHITE)
        P.b(0.40, -0.22 + i * 0.09, 0.45 + hop, 0.05, 0.055, 0.11, WHITE)
    P.b(0, -0.20, 0.44 + hop, 0.82, 0.12, 0.30 + o, lid)
    P.b(0, -0.06, 0.74 + hop + o, 0.82, 0.44, 0.08, lid)
    P.b(0, -0.06, 0.74 + hop + o, 0.84, 0.46, 0.03, band)
    for i in range(6):
        P.b(-0.30 + i * 0.12, 0.14, 0.64 + hop + o, 0.055, 0.05, 0.10, WHITE)
        P.b(0.38, -0.20 + i * 0.09, 0.64 + hop + o, 0.05, 0.055, 0.10, WHITE)
    for sx in (-0.18, 0.18):
        P.b(sx, -0.06, 0.82 + hop + o, 0.05, 0.05, 0.10, woodD)
        P.b(sx, -0.06, 0.92 + hop + o, 0.13, 0.13, 0.13, WHITE)
        P.b(sx + 0.05, 0.02, 0.95 + hop + o, 0.05, 0.03, 0.07, (200, 40, 40))
    return P


def m_cube(t):
    w = 0.03 * math.sin(t * 3)
    out, inn, hl = (118, 232, 188), (76, 190, 156), (200, 255, 236)
    bone, gold, steel = (238, 234, 218), (252, 208, 72), (200, 206, 216)
    P = _P()
    P.b(0, 0, 0, 0.80, 0.80, 0.80 + w, out)
    P.b(0, 0, 0.04, 0.66, 0.66, 0.66 + w, inn)
    P.b(0, 0, 0.78 + w, 0.80, 0.80, 0.03, hl)
    for i in range(4):
        a = i * math.pi / 2 + t * 0.5
        P.b(math.cos(a) * 0.28, math.sin(a) * 0.28, 0.80 + w, 0.10, 0.10, 0.04 + 0.03 * math.sin(t * 4 + i), hl)
    P.b(0.30, 0.0, 0.36 + w, 0.16, 0.16, 0.16, bone)
    P.b(0.40, 0.04, 0.38 + w, 0.03, 0.03, 0.05, DARK)
    P.b(0.40, -0.04, 0.38 + w, 0.03, 0.03, 0.05, DARK)
    P.b(0.40, 0.0, 0.31 + w, 0.03, 0.06, 0.03, DARK)
    P.b(0.06, 0.40, 0.20 + w, 0.20, 0.03, 0.04, bone)
    P.b(0.06, 0.40, 0.28 + w, 0.20, 0.03, 0.04, bone)
    P.b(0.06, 0.40, 0.36 + w, 0.16, 0.03, 0.04, bone)
    P.b(-0.22, 0.40, 0.54 + w, 0.18, 0.03, 0.06, steel)
    P.b(-0.22, 0.40, 0.60 + w, 0.04, 0.03, 0.14, (196, 120, 60))
    for (x, y, z) in ((0.40, 0.22, 0.20), (0.40, -0.22, 0.52), (0.18, 0.40, 0.62), (0.40, 0.14, 0.62), (-0.04, 0.40, 0.10)):
        P.b(x, y, z + w, 0.07, 0.07, 0.04, gold)
    P.b(0.0, -0.10, 0.70 + w, 0.03, 0.03, 0.22, steel)
    P.b(0.0, -0.10, 0.88 + w, 0.10, 0.03, 0.03, (196, 120, 60))
    P.b(-0.18, -0.18, 0.40 + w, 0.18, 0.18, 0.10, bone)
    for i in range(3):
        P.b(0.44, 0.28 - 0.14 * i, 0.0, 0.06, 0.08, 0.04 + 0.03 * math.sin(t * 3 + i), out)
    return P


def m_rust(t):
    """Monstro da Ferrugem: tatu-farejador com antenas que enferrujam metal."""
    c, cD, cL, plate = (196, 116, 64), (132, 76, 44), (232, 160, 94), (158, 90, 52)
    ant = (250, 226, 196)
    P = _P()
    m_quad(P, t, c, cD, cL, 0.56, 0.34, 0.24, 0.14, 0.09, ((-0.24, -0.15), (-0.24, 0.15), (0.24, -0.15), (0.24, 0.15)), 5.0)
    for k in range(5):
        a = -0.30 + 0.15 * k
        P.b(a, 0, 0.44, 0.17, 0.36 - 0.01 * k, 0.05, plate if k % 2 else cD)
        P.b(a, 0, 0.49, 0.06, 0.06, 0.06, (224, 142, 82))
    P.b(0.52, 0, 0.22, 0.26, 0.26, 0.24, c)
    P.b(0.68, 0, 0.22, 0.12, 0.20, 0.14, cL)
    P.b(0.75, 0.07, 0.28, 0.03, 0.03, 0.04, DARK)
    P.b(0.75, -0.07, 0.28, 0.03, 0.03, 0.04, DARK)
    P.b(0.52, 0, 0.46, 0.22, 0.24, 0.04, plate)
    m_eyes(P, 0.66, 0.12, 0.36, (255, 240, 200), DARK, 0.045)
    for s_ in (-1, 1):
        sw_ = math.sin(t * 4 + s_) * 0.05
        for k in range(7):
            P.b(0.58 + 0.07 * k, 0.10 * s_ + sw_ * k * 0.4, 0.46 + 0.05 * k - 0.004 * k * k, 0.07, 0.05, 0.05, ant if k < 5 else (252, 170, 150))
        for k in range(5):
            P.b(0.58 + 0.07 * 6 + 0.04 * math.sin(k + t * 3), 0.10 * s_ + sw_ * 2.4 + 0.04 * math.cos(k * 1.3 + t * 3), 0.74 + 0.03 * k, 0.04, 0.04, 0.04, ant)
    for k in range(3):
        P.b(-0.36 - 0.12 * k, 0, 0.28 + 0.03 * k, 0.14, 0.14, 0.10, cD)
    P.b(-0.74, 0, 0.36, 0.06, 0.30, 0.06, (120, 70, 44))
    P.b(-0.74, 0, 0.36, 0.07, 0.07, 0.20 + 0.04 * math.sin(t * 6), (90, 56, 36))
    return P

def m_harpy(t):
    skin, hair, feat, featD, gold = (238, 196, 160), (120, 70, 150), (150, 100, 70), (100, 66, 46), (252, 210, 90)
    fl = math.sin(t * 8)
    z0 = 0.32 + 0.05 * math.sin(t * 4)
    P = _P()
    for s_ in (-1, 1):
        P.b(s_ * 0.07, 0, z0 - 0.02, 0.07, 0.07, 0.20, featD)
        for k in (-1, 0, 1):
            x, y = (s_ * 0.07 + 0.03 * k, 0.07)
            P.b(x, y, z0 - 0.04, 0.025, 0.07, 0.025, gold)
    P.b(0, 0, z0 + 0.12, 0.26, 0.20, 0.22, feat)
    for k in range(4):
        P.b(-0.10 + 0.07 * k, -0.04, z0 + 0.04 - 0.01 * k, 0.07, 0.05, 0.12, featD if k % 2 else feat)
    P.b(0, 0.0, z0 + 0.22, 0.26, 0.20, 0.14, skin)
    P.b(0, 0.105, z0 + 0.24, 0.26, 0.02, 0.06, (188, 80, 120))
    P.b(0.135, 0, z0 + 0.24, 0.02, 0.20, 0.06, (188, 80, 120))
    P.b(0, 0, z0 + 0.36, 0.22, 0.20, 0.18, skin)
    P.b(0, -0.05, z0 + 0.38, 0.26, 0.14, 0.22, hair)
    P.b(0.0, 0, z0 + 0.52, 0.26, 0.24, 0.05, hair)
    for k in range(3):
        P.b(-0.12 - 0.02 * k, -0.10 - 0.02 * k, z0 + 0.50 - 0.09 * k, 0.07, 0.07, 0.10, hair)
    P.b(0.08, 0.10, z0 + 0.40, 0.05, 0.03, 0.04, (252, 190, 60))
    m_eyes(P, 0.115, 0.105, z0 + 0.43, (255, 230, 80), (120, 20, 40), 0.045)
    for s_ in (1, -1):
        m_wing(P, s_, 0, -0.02, z0 + 0.28, 7, 0.115, fl * 0.20 + 0.04, feat, featD, (222, 190, 120), 0.09, 0.035, 0.10)
    return P


def m_displacer(t):
    c, cD, cL, glow = (46, 70, 104), (26, 40, 66), (84, 120, 164), (140, 220, 255)
    P = _P()
    legs6 = ((-0.32, -0.12), (-0.32, 0.12), (0.0, -0.12), (0.0, 0.12), (0.30, -0.12), (0.30, 0.12))
    m_quad(P, t, c, cD, cL, 0.72, 0.28, 0.22, 0.17, 0.075, legs6, 7.0, foot=(200, 210, 224))
    P.b(0.58, 0, 0.26, 0.28, 0.28, 0.24, c)
    P.b(0.74, 0, 0.26, 0.14, 0.22, 0.12, cL)
    P.b(0.82, 0, 0.30, 0.03, 0.05, 0.03, DARK)
    P.b(0.58, -0.10, 0.52, 0.05, 0.05, 0.08, cD)
    P.b(0.58, 0.10, 0.52, 0.05, 0.05, 0.08, cD)
    P.b(0.74, 0.07, 0.24, 0.02, 0.02, 0.05, WHITE)
    P.b(0.74, -0.07, 0.24, 0.02, 0.02, 0.05, WHITE)
    m_eyes(P, 0.72, 0.12, 0.40, (120, 255, 190), DARK, 0.045)
    for k in range(7):
        P.b(-0.40 - 0.09 * k, 0.04 * math.sin(t * 4 + k), 0.42 + 0.03 * k * (1 + 0.6 * math.sin(t * 3)), 0.10 - 0.008 * k, 0.09 - 0.008 * k, 0.07, cD)
    for s_ in (-1, 1):
        for k in range(7):
            sd = 0.20 * s_ + 0.05 * math.sin(t * 3 + k * 0.7 + s_) * (k / 3)
            P.b(0.30 + 0.09 * k, sd, 0.44 + 0.07 * math.sin(k * 0.55 + t * 2 + s_) + 0.02 * k, 0.09, 0.06, 0.06, cL if k % 2 else c)
        P.b(0.30 + 0.09 * 6 + 0.06, 0.20 * s_, 0.44 + 0.07 * math.sin(6 * 0.55 + t * 2 + s_) + 0.14, 0.09, 0.09, 0.06, glow)
    for k in range(4):
        P.b(-0.30 + 0.30 * k, -0.34 + 0.04 * math.sin(t * 5 + k), 0.22 + 0.12 * (k % 2), 0.16, 0.08, 0.12, mix(c, 0.55, (200, 230, 255)))
    return P

# ------------------------------------------------------------------ TIER 3
def m_ogre(t):
    sk, skD, cl, bone = (208, 168, 116), (162, 124, 84), (120, 80, 50), (240, 236, 212)
    sw, arm = math.sin(t * 3), math.sin(t * 3) * 0.04
    P = _P()
    m_legs2(P, sw * 0.7, 0.14, 0.18, 0.20, 0.08, 0.14, 0.08, skD, skD, (96, 70, 50))
    P.b(0, 0, 0.30, 0.64, 0.44, 0.10, cl)
    P.b(0.0, 0.23, 0.14, 0.18, 0.02, 0.20, cl)
    P.b(0.0, 0.245, 0.14, 0.05, 0.02, 0.06, bone)
    P.b(0, 0, 0.36, 0.66, 0.46, 0.32, sk)
    P.b(0, 0.24, 0.40, 0.44, 0.02, 0.20, mix(sk, 0.15))
    P.b(0.0, 0.25, 0.46, 0.06, 0.02, 0.05, skD)
    P.b(0, 0, 0.66, 0.74, 0.44, 0.24, sk)
    for i in range(6):
        a = math.pi * (i / 5)
        P.b(math.cos(a) * 0.22, 0.24, 0.76 - math.sin(a) * 0.09, 0.05, 0.03, 0.05, bone)
    P.b(-0.46, 0.0, 0.38 + arm, 0.18, 0.24, 0.52, sk)
    P.b(0.46, 0.0, 0.38 - arm, 0.18, 0.24, 0.52, sk)
    P.b(-0.46, 0.0, 0.28 + arm, 0.22, 0.26, 0.12, skD)
    P.b(0.46, 0.0, 0.28 - arm, 0.22, 0.26, 0.12, skD)
    P.b(0, 0.02, 0.90, 0.36, 0.30, 0.22, sk)
    P.b(0.10, 0.12, 0.90, 0.20, 0.20, 0.09, skD)
    P.b(0.14, 0.24, 0.96, 0.04, 0.04, 0.08, bone)
    P.b(0.22, 0.14, 0.96, 0.04, 0.04, 0.08, bone)
    P.b(0.12, 0.22, 1.00, 0.05, 0.03, 0.05, mix(sk, 0.1))
    P.b(0, -0.02, 1.12, 0.38, 0.32, 0.05, (70, 50, 40))
    P.b(0.10, -0.10, 1.17, 0.05, 0.05, 0.07, (70, 50, 40))
    P.b(-0.10, 0.0, 1.17, 0.05, 0.05, 0.07, (70, 50, 40))
    m_eyes(P, 0.185, 0.155, 1.00, (255, 230, 70), (150, 20, 20), 0.055)
    P.b(0.50, 0.16, 0.10 - arm, 0.09, 0.09, 0.62, (120, 86, 52))
    P.b(0.50, 0.16, 0.70 - arm, 0.22, 0.22, 0.34, (110, 78, 48))
    for (x, y, z) in ((0.38, 0.16, 0.90), (0.50, 0.28, 0.86), (0.62, 0.16, 0.80), (0.50, 0.04, 1.02), (0.50, 0.28, 1.00)):
        P.b(x, y, z - arm, 0.05, 0.05, 0.06, (206, 212, 224))
    return P


def m_owlbear(t):
    fur, dk, fea, feaD, beak = (126, 88, 60), (84, 58, 40), (236, 226, 204), (196, 176, 150), (246, 176, 54)
    arm = math.sin(t * 3) * 0.04
    P = _P()
    for (lx, ly) in [(-0.34, -0.34), (0.16, -0.34), (-0.34, 0.12), (0.16, 0.12)]:
        P.b(lx + 0.10, ly + 0.10, 0, 0.24, 0.24, 0.10, dk)
        P.b(lx + 0.10, ly + 0.10, 0.10, 0.20, 0.20, 0.16, fur)
    P.b(0, 0, 0.26, 0.84, 0.76, 0.46, fur)
    P.b(0, 0, 0.72, 0.64, 0.58, 0.12, dk)
    P.b(0.0, 0.40, 0.30, 0.80, 0.03, 0.30, mix(fur, 0.15))
    for i in range(4):
        P.b(-0.30 + i * 0.20, 0.42, 0.34 + 0.04 * (i % 2), 0.10, 0.03, 0.10, feaD)
    for s_ in (-1, 1):
        P.b(s_ * 0.46, 0.20, 0.44 + s_ * arm, 0.16, 0.30, 0.18, fur)
        for k in (-1, 0, 1):
            P.b(s_ * 0.46 + 0.05 * k, 0.40, 0.42 + s_ * arm, 0.035, 0.08, 0.05, (240, 236, 214))
    P.b(0, 0.12, 0.66, 0.50, 0.40, 0.36, fea)
    P.b(0, 0.12, 0.92, 0.50, 0.40, 0.10, fur)
    for k in range(4):
        P.b(-0.20 + 0.13 * k, 0.12, 1.00, 0.08, 0.08, 0.10 + 0.03 * (k % 2), fur if k % 2 else dk)
    P.b(-0.22, 0.14, 1.04, 0.07, 0.07, 0.13, dk)
    P.b(0.22, 0.14, 1.04, 0.07, 0.07, 0.13, dk)
    P.b(0.08, 0.48, 0.64, 0.14, 0.14, 0.15, beak)
    P.b(0.10, 0.60, 0.62, 0.08, 0.06, 0.09, (200, 120, 40))
    P.b(0.0, 0.45, 0.70, 0.40, 0.02, 0.18, feaD)
    P.b(0.45, 0.0, 0.70, 0.02, 0.40, 0.18, feaD)
    P.b(0.12, 0.45, 0.80, 0.12, 0.02, 0.12, (255, 224, 40))
    P.b(-0.10, 0.45, 0.80, 0.12, 0.02, 0.12, (255, 224, 40))
    P.b(0.45, 0.14, 0.80, 0.02, 0.12, 0.12, (255, 224, 40))
    P.b(0.14, 0.45, 0.83, 0.05, 0.02, 0.07, DARK)
    P.b(-0.08, 0.45, 0.83, 0.05, 0.02, 0.07, DARK)
    P.b(0.45, 0.16, 0.83, 0.02, 0.05, 0.07, DARK)
    P.b(-0.30, -0.30, 0.42, 0.14, 0.14, 0.14, dk)
    return P


def m_troll(t):
    sk, skD, hair, claw = (104, 152, 100), (70, 106, 70), (60, 98, 56), (230, 226, 200)
    sw, arm = math.sin(t * 3), math.sin(t * 3) * 0.05
    P = _P()
    m_legs2(P, sw * 0.6, 0.12, 0.17, 0.19, 0.07, 0.15, 0.10, skD, skD, (90, 70, 54))
    P.b(0.04, 0.04, 0.32, 0.52, 0.36, 0.08, (112, 80, 50))
    P.b(0.04, 0.04, 0.38, 0.54, 0.38, 0.34, sk)
    P.b(0.04, 0.24, 0.44, 0.38, 0.02, 0.20, mix(sk, 0.18))
    P.b(0.04, 0.245, 0.52, 0.05, 0.02, 0.05, skD)
    for i in range(5):
        P.b(-0.10 - 0.04 * i, -0.10 - 0.03 * i, 0.58 + 0.03 * i, 0.12, 0.12, 0.10, hair if i % 2 else mix(hair, 0.15))
    P.b(0.04, 0.04, 0.70, 0.46, 0.32, 0.14, sk)
    for s_ in (-1, 1):
        P.b(s_ * 0.40 + 0.04, 0.12, 0.20 - s_ * arm, 0.14, 0.18, 0.54, sk)
        P.b(s_ * 0.40 + 0.04, 0.14, 0.04 - s_ * arm, 0.18, 0.22, 0.14, skD)
        for k in (-1, 0, 1):
            P.b(s_ * 0.40 + 0.04 + 0.05 * k, 0.26, 0.04 - s_ * arm, 0.03, 0.07, 0.05, claw)
    P.b(0.06, 0.12, 0.80, 0.32, 0.30, 0.24, sk)
    P.b(0.06, 0.12, 1.02, 0.32, 0.30, 0.05, hair)
    P.b(0.10, 0.34, 0.86, 0.10, 0.10, 0.14, mix(sk, 0.22))
    P.b(0.10, 0.34, 0.80, 0.10, 0.04, 0.05, skD)
    P.b(0.06, 0.30, 0.76, 0.18, 0.03, 0.04, (30, 16, 20))
    for k in (-1, 1):
        P.b(0.06 + 0.07 * k, 0.32, 0.77, 0.03, 0.02, 0.05, WHITE)
    for s_ in (-1, 1):
        P.b(0.06 + s_ * 0.19, 0.14, 0.92, 0.07, 0.04, 0.07, sk)
    P.b(0.24, 0.10, 0.96, 0.03, 0.03, 0.03, skD)
    P.b(0.16, 0.30, 0.96, 0.03, 0.03, 0.03, skD)
    m_eyes(P, 0.20, 0.28, 0.90, (255, 70, 40), DARK, 0.05)
    for i in range(3):
        u = (t * 0.6 + i * 0.33) % 1.0
        P.b(0.24 + 0.1 * math.sin(i * 2.1), 0.2 + 0.1 * math.cos(i * 1.7), 0.50 + u * 0.4, 0.03, 0.03, 0.03, (150, 255, 150))
    return P


def m_golem(t):
    rock, rockD, rockL, moss = (146, 146, 158), (104, 104, 120), (178, 178, 190), (84, 146, 80)
    rune = (90, 232, 255)
    pulse = 0.5 + 0.5 * math.sin(t * 3)
    core = mix((70, 200, 255), pulse * 0.6)
    arm = math.sin(t * 2.5) * 0.04
    P = _P()
    for s_ in (-1, 1):
        P.b(s_ * 0.20, 0, 0, 0.28, 0.36, 0.16, rockD)
        P.b(s_ * 0.20, 0, 0.16, 0.22, 0.28, 0.24, rock)
    P.b(0, 0, 0.38, 0.68, 0.42, 0.10, rockD)
    P.b(0, 0, 0.48, 0.92, 0.56, 0.52, rock)
    P.b(0, 0, 0.98, 0.84, 0.50, 0.08, rockL)
    P.b(0.0, 0.29, 0.58, 0.30, 0.02, 0.28, (30, 60, 80))
    P.b(0.0, 0.30, 0.64, 0.18, 0.02, 0.16, core)
    P.b(0.47, 0.0, 0.58, 0.02, 0.28, 0.28, (30, 60, 80))
    P.b(0.48, 0.0, 0.64, 0.02, 0.16, 0.16, core)
    for (x, y, z, w, d, h) in ((-0.30, 0.29, 0.80, 0.16, 0.02, 0.03), (0.30, 0.29, 0.54, 0.03, 0.02, 0.16), (0.47, -0.18, 0.86, 0.02, 0.14, 0.03), (0.47, 0.18, 0.52, 0.02, 0.03, 0.16)):
        P.b(x, y, z, w, d, h, mix(rune, 0.0))
    P.b(-0.30, 0.29, 0.60, 0.02, 0.02, 0.18, (40, 40, 50))
    P.b(0.20, 0.29, 0.90, 0.14, 0.02, 0.02, (50, 50, 60))
    for s_ in (-1, 1):
        P.b(s_ * 0.60, 0, 0.84, 0.24, 0.42, 0.20, rockD)
        P.b(s_ * 0.60, 0, 0.34 - s_ * arm, 0.22, 0.30, 0.52, rock)
        P.b(s_ * 0.62, 0, 0.18 - s_ * arm, 0.30, 0.38, 0.18, rockD)
        P.b(s_ * 0.62, 0.16, 0.16 - s_ * arm, 0.08, 0.06, 0.08, rockL)
    P.b(-0.30, -0.02, 1.02, 0.34, 0.26, 0.05, moss)
    P.b(0.26, 0.10, 1.02, 0.18, 0.16, 0.04, moss)
    P.b(0, 0.02, 1.06, 0.40, 0.34, 0.26, rock)
    P.b(0, 0.02, 1.30, 0.34, 0.28, 0.04, rockL)
    P.b(0.0, 0.20, 1.12, 0.30, 0.02, 0.06, DARK)
    P.b(0.21, 0.02, 1.12, 0.02, 0.26, 0.06, DARK)
    m_eyes(P, 0.20, 0.17, 1.14, (255, 224, 70), (255, 120, 40), 0.055)
    return P


def m_gargoyle(t):
    st, stD, stL, red = (122, 126, 140), (84, 88, 104), (160, 164, 178), (255, 70, 60)
    fl = math.sin(t * 5)
    z0 = 0.05 + 0.04 * math.sin(t * 5) * 0.5
    P = _P()
    for s_ in (-1, 1):
        P.b(s_ * 0.12, 0.02, z0, 0.14, 0.20, 0.10, stD)
        P.b(s_ * 0.12, 0.0, z0 + 0.10, 0.13, 0.14, 0.14, st)
        for k in (-1, 0, 1):
            P.b(s_ * 0.12 + 0.04 * k, 0.12, z0, 0.03, 0.06, 0.04, stL)
    P.b(0, 0, z0 + 0.24, 0.34, 0.26, 0.18, st)
    P.b(0.04, 0.04, z0 + 0.40, 0.36, 0.28, 0.20, stL)
    P.b(0.0, 0.15, z0 + 0.28, 0.20, 0.02, 0.14, stD)
    for s_ in (-1, 1):
        P.b(s_ * 0.24, 0.12, z0 + 0.18, 0.09, 0.22, 0.09, st)
        P.b(s_ * 0.24, 0.26, z0 + 0.16, 0.10, 0.07, 0.07, stD)
        for k in (-1, 0, 1):
            P.b(s_ * 0.24 + 0.03 * k, 0.31, z0 + 0.14, 0.02, 0.05, 0.03, stL)
    P.b(0.08, 0.10, z0 + 0.60, 0.26, 0.24, 0.20, st)
    P.b(0.16, 0.20, z0 + 0.60, 0.16, 0.14, 0.09, stD)
    for s_ in (-1, 1):
        P.b(0.08 + s_ * 0.10, 0.08, z0 + 0.80, 0.05, 0.05, 0.14, stL)
    P.b(0.26, 0.28, z0 + 0.60, 0.03, 0.03, 0.06, WHITE)
    P.b(0.16, 0.30, z0 + 0.60, 0.03, 0.03, 0.06, WHITE)
    m_eyes(P, 0.21, 0.19, z0 + 0.72, red, (255, 220, 120), 0.05)
    for k in range(5):
        a = -0.2 - 0.09 * k
        x, y = dp(a, 0.05 * math.sin(t * 3 + k))
        P.b(x, y, z0 + 0.12 + 0.02 * k, 0.09 - 0.012 * k, 0.09 - 0.012 * k, 0.07, stD)
    for s_ in (1, -1):
        m_wing(P, s_, 0, -0.04, z0 + 0.50, 5, 0.11, fl * 0.12 + 0.34, stD, st, stL, 0.08, 0.04, 0.0)
    return P


def m_basilisk(t):
    c, cD, cL, crest, gl = (112, 126, 60), (72, 86, 40), (160, 174, 98), (200, 70, 60), (190, 255, 90)
    P = _P()
    legs8 = ((-0.34, -0.17), (-0.34, 0.17), (-0.12, -0.17), (-0.12, 0.17), (0.10, -0.17), (0.10, 0.17), (0.32, -0.17), (0.32, 0.17))
    m_quad(P, t, c, cD, cL, 0.76, 0.30, 0.20, 0.13, 0.07, legs8, 7.0)
    for k in range(6):
        P.b(-0.34 + 0.17 * k, 0, 0.40, 0.09, 0.06, 0.08 + 0.03 * (k % 2), crest)
    P.b(0.56, 0, 0.26, 0.28, 0.28, 0.22, c)
    P.b(0.72, 0, 0.26, 0.14, 0.22, 0.12, cL)
    P.b(0.80, 0.06, 0.32, 0.03, 0.03, 0.04, DARK)
    P.b(0.80, -0.06, 0.32, 0.03, 0.03, 0.04, DARK)
    P.b(0.74, 0, 0.26, 0.13, 0.20, 0.03, (170, 60, 60))
    P.b(0.56, 0, 0.48, 0.20, 0.30, 0.05, crest)
    for s_ in (-1, 1):
        P.b(0.54, 0.16 * s_, 0.50, 0.05, 0.05, 0.10, crest)
    glow = 0.5 + 0.5 * math.sin(t * 5)
    m_eyes(P, 0.70, 0.145, 0.40, mix(gl, glow * 0.3), (60, 80, 20), 0.065)
    for k in range(8):
        P.b(-0.44 - 0.10 * k, 0.07 * math.sin(t * 3 + k * 0.7), 0.20 - 0.012 * k, 0.20 - 0.022 * k, 0.22 - 0.025 * k, 0.12, cD if k % 2 else c)
    for k in range(3):
        P.b(0.88 + 0.05 * k, 0.12 * (k - 1), 0.04, 0.08, 0.08, 0.05 + 0.03 * k, (164, 164, 172))
    return P

def m_hellhound(t):
    c, cD, cL, ember = (54, 34, 38), (30, 20, 24), (96, 54, 54), (255, 110, 40)
    P = _P()
    m_quad(P, t, c, cD, cL, 0.66, 0.30, 0.24, 0.22, 0.09, None, 8.0, foot=(72, 40, 40))
    for k in range(5):
        P.b(-0.26 + 0.14 * k, 0.16, 0.34 + 0.10 * (k % 2), 0.05, 0.03, 0.05, ember)
    P.b(0.52, 0, 0.42, 0.30, 0.30, 0.26, c)
    P.b(0.68, 0, 0.42, 0.14, 0.22, 0.13, cL)
    P.b(0.76, 0.07, 0.50, 0.03, 0.03, 0.04, DARK)
    P.b(0.76, -0.07, 0.50, 0.03, 0.03, 0.04, DARK)
    P.b(0.69, 0.0, 0.42, 0.12, 0.20, 0.025, (255, 60, 40))
    for k in (-1, 1):
        P.b(0.70, 0.08 * k, 0.43, 0.025, 0.02, 0.05, WHITE)
        P.b(0.46, 0.12 * k, 0.68, 0.06, 0.06, 0.13, cD)
    P.b(0.40, 0, 0.60, 0.10, 0.34, 0.05, (160, 160, 168))
    for k in (-1, 1):
        P.b(0.40, 0.17 * k, 0.64, 0.04, 0.04, 0.07, (210, 210, 220))
    m_eyes(P, 0.66, 0.15, 0.56, (255, 200, 60), (255, 60, 30), 0.055)
    m_flame(P, 0.50, 0, 0.68, t, 0.13, 3, 0.0)
    m_flame(P, 0.26, 0, 0.62, t, 0.15, 3, 1.3)
    m_flame(P, 0.02, 0, 0.60, t, 0.15, 3, 2.1)
    for k in range(5):
        m_flame(P, -0.40 - 0.07 * k, 0, 0.40 + 0.05 * k, t, 0.09, 2, 3.0 + k)
    return P


# ------------------------------------------------------------------ CHEFES
def m_wingy(P, side, rx, rz, n, step, flap, c, cD, bone, span=0.16, thick=0.035, sweep=0.12, droop=0.0):
    """Asa de dragão/demônio que sai pelos lados (eixo y) e é varrida para trás."""
    for i in range(n):
        r = 0.22 + step * i
        u = i / max(1, n - 1)
        lift = flap * u - droop * u * u
        x = rx - sweep * i
        w = span * (1.25 - 0.55 * i / n)
        for rw in ((-1.0, 0.0, 1.0) if i < n - 2 else (0.0,)):
            P.b(x + rw * w * 0.9, side * r, rz + lift, w * 1.2, step * 1.3, thick, c if rw else cD)
        P.b(x, side * r, rz + lift + thick * 0.9, 0.045, step * 1.15, 0.03, bone)
    for f in (0.35, 0.62, 0.9):
        for i in range(int(n * f), n):
            u = i / max(1, n - 1)
            P.b(rx - sweep * i - 0.10 * (i - n * f), side * (0.22 + step * i), rz + flap * u - droop * u * u + 0.03, 0.04, 0.05, 0.025, bone)


def m_dragon(t):
    r, rD, rL = (204, 52, 56), (138, 34, 44), (236, 104, 90)
    belly, horn, yel, gold = (246, 208, 122), (246, 232, 180), (255, 234, 70), (252, 210, 72)
    fl = math.sin(t * 3.2)
    jaw = 0.5 + 0.5 * math.sin(t * 2.2)
    P = _P()
    for (lx, ly) in [(-0.46, -0.30), (-0.46, 0.30), (0.32, -0.28), (0.32, 0.28)]:
        P.b(lx, ly, 0, 0.28, 0.22, 0.08, rD)
        P.b(lx, ly, 0.08, 0.20, 0.18, 0.20, r)
        P.b(lx, ly, 0.28, 0.26, 0.22, 0.16, rD)
        for k in (-1, 0, 1):
            P.b(lx + 0.15, ly + 0.07 * k, 0.0, 0.07, 0.04, 0.06, horn)
    P.b(-0.05, 0, 0.32, 1.20, 0.66, 0.44, r)
    P.b(-0.05, 0, 0.64, 1.04, 0.54, 0.10, rL)
    P.b(-0.05, 0.345, 0.34, 1.06, 0.02, 0.34, belly)
    for i in range(7):
        P.b(-0.50 + 0.17 * i, 0.355, 0.34, 0.02, 0.01, 0.34, (214, 160, 84))
    P.b(0.57, 0, 0.36, 0.02, 0.44, 0.30, belly)
    for i in range(8):
        P.b(-0.56 + 0.16 * i, 0, 0.74, 0.07, 0.07, 0.12 + 0.04 * (i % 2), horn)
    for i in range(5):
        u = i / 4
        P.b(0.56 + 0.12 * i, 0.03 * math.sin(t * 2 + i), 0.52 + 0.17 * i, 0.36 - 0.03 * i, 0.34 - 0.03 * i, 0.22, r if i % 2 else rL)
        P.b(0.56 + 0.12 * i + 0.12, 0, 0.52 + 0.17 * i, 0.02, 0.24, 0.20, belly)
    hz = 1.32
    P.b(1.12, 0, hz, 0.38, 0.34, 0.26, rL)
    P.b(1.30, 0, hz + 0.03, 0.24, 0.26, 0.12, rL)
    P.b(1.30, 0, hz - 0.10 * jaw - 0.02, 0.22, 0.24, 0.06, rD)
    P.b(1.44, 0.09, hz + 0.11, 0.03, 0.04, 0.03, DARK)
    P.b(1.44, -0.09, hz + 0.11, 0.03, 0.04, 0.03, DARK)
    for k in range(4):
        P.b(1.24 + 0.06 * k, 0.12, hz + 0.0, 0.03, 0.025, 0.05, WHITE)
        P.b(1.24 + 0.06 * k, 0.12, hz - 0.06 * jaw, 0.03, 0.025, 0.05, WHITE)
    P.b(1.12, 0, hz + 0.24, 0.24, 0.36, 0.04, rD)
    for s_ in (-1, 1):
        P.b(1.02, s_ * 0.13, hz + 0.24, 0.06, 0.06, 0.18, horn)
        P.b(0.94, s_ * 0.13, hz + 0.40, 0.05, 0.05, 0.12, horn)
        P.b(1.14, s_ * 0.19, hz + 0.10, 0.10, 0.04, 0.16, rD)
    m_eyes(P, 1.28, 0.175, hz + 0.16, yel, DARK, 0.065)
    if jaw > 0.55:
        for i in range(5):
            f = 0.5 + 0.5 * math.sin(t * 10 + i * 1.5)
            P.b(1.52 + 0.17 * i, 0.02 * math.sin(t * 8 + i), hz + 0.0 - 0.01 * i, 0.12 + 0.05 * i, 0.10 + 0.05 * i, 0.07 + 0.03 * i,
                ((255, 235, 120), (255, 180, 50), (255, 100, 30), (230, 60, 30), (200, 50, 40))[i] if f > 0.3 else (255, 120, 40))
    for i in range(9):
        u = i / 8
        P.b(-0.68 - 0.15 * i, 0.12 * math.sin(t * 2 + i * 0.6) * u, 0.44 - 0.03 * i, 0.42 - 0.04 * i, 0.34 - 0.03 * i, 0.30 - 0.025 * i, r if i % 2 else rD)
        if i % 2 == 0:
            P.b(-0.68 - 0.15 * i, 0.12 * math.sin(t * 2 + i * 0.6) * u, 0.74 - 0.05 * i, 0.05, 0.05, 0.08, horn)
    P.b(-2.14, 0.12 * math.sin(t * 2 + 9 * 0.6), 0.40, 0.14, 0.26, 0.10, horn)
    for s_ in (-1, 1):
        m_wingy(P, s_, 0.20, 0.80, 7, 0.15, fl * 0.34 + 0.20, (160, 40, 66), (190, 52, 76), horn, 0.20, 0.04, 0.14, 0.10)
    for (x, y) in ((0.7, 0.55), (0.9, 0.40), (0.55, 0.62), (0.2, 0.62), (1.0, 0.55)):
        P.b(x, y, 0.0, 0.08, 0.08, 0.03, gold)
    return P


def m_goblin_chief(t):
    sk, skD, armor, armorL = (96, 170, 92), (66, 126, 66), (126, 94, 66), (176, 140, 96)
    metal, metalL, red, gold, leath = (150, 156, 170), (210, 216, 228), (176, 40, 44), (240, 200, 80), (110, 76, 46)
    sw, arm = math.sin(t * 4), math.sin(t * 3) * 0.04
    P = _P()
    m_legs2(P, sw, 0.13, 0.15, 0.17, 0.07, 0.14, 0.10, (74, 54, 42), armor, (52, 40, 30))
    P.b(0, 0, 0.30, 0.60, 0.42, 0.10, armor)
    P.b(0, 0.225, 0.18, 0.40, 0.02, 0.14, armorL)
    P.b(0.315, 0, 0.18, 0.02, 0.30, 0.14, armorL)
    P.b(0, 0, 0.40, 0.64, 0.44, 0.30, armor)
    P.b(0, 0.23, 0.42, 0.44, 0.02, 0.24, metal)
    P.b(0.325, 0, 0.42, 0.02, 0.28, 0.24, metal)
    for i in range(3):
        P.b(0, 0.24, 0.46 + 0.07 * i, 0.36, 0.01, 0.025, metalL)
    P.b(0.06, 0.245, 0.50, 0.10, 0.01, 0.22, red)
    P.b(0, 0.24, 0.36, 0.60, 0.01, 0.04, gold)
    for s_ in (-1, 1):
        P.b(s_ * 0.42, 0, 0.66, 0.22, 0.34, 0.10, metal)
        P.b(s_ * 0.42, 0, 0.76, 0.06, 0.06, 0.15, metalL)
        P.b(s_ * 0.42, -0.01, 0.36 - s_ * arm, 0.13, 0.17, 0.30, sk)
        P.b(s_ * 0.42, 0, 0.30 - s_ * arm, 0.15, 0.19, 0.08, metal)
    P.b(-0.46, 0.20, 0.30 + arm, 0.30, 0.05, 0.42, metal)
    P.b(-0.46, 0.235, 0.34 + arm, 0.20, 0.02, 0.34, armorL)
    P.b(-0.46, 0.255, 0.46 + arm, 0.10, 0.02, 0.10, gold)
    P.b(0.52, 0.14, 0.10 - arm, 0.05, 0.05, 0.64, leath)
    P.b(0.52, 0.14, 0.74 - arm, 0.20, 0.20, 0.20, metal)
    for (dx, dy, dz) in ((0.14, 0, 0.10), (-0.14, 0, 0.10), (0, 0.14, 0.10), (0, -0.14, 0.10), (0, 0, 0.22)):
        P.b(0.52 + dx, 0.14 + dy, 0.74 + dz - arm, 0.05, 0.05, 0.06, metalL)
    P.b(0, 0, 0.70, 0.42, 0.36, 0.24, sk)
    P.b(0.12, 0.12, 0.70, 0.20, 0.20, 0.09, skD)
    P.b(0.30, 0.04, 0.80, 0.16, 0.05, 0.07, sk)
    P.b(0.04, 0.30, 0.80, 0.05, 0.16, 0.07, sk)
    P.b(0.14, 0.22, 0.73, 0.04, 0.03, 0.06, WHITE)
    P.b(0.22, 0.14, 0.73, 0.03, 0.04, 0.06, WHITE)
    P.b(0, 0, 0.90, 0.46, 0.40, 0.08, metal)
    P.b(0, 0, 0.98, 0.10, 0.36, 0.12, red)
    P.b(-0.03, 0, 1.10, 0.08, 0.30, 0.06, red)
    m_eyes(P, 0.215, 0.185, 0.80, gold, (180, 30, 30), 0.06)
    return P


def m_werewolf(t):
    fur, furD, furL, claw = (126, 114, 110), (84, 74, 72), (182, 160, 146), (232, 222, 198)
    pants = (92, 78, 62)
    sw, arm = math.sin(t * 5), math.sin(t * 4) * 0.05
    how = 0.5 + 0.5 * math.sin(t * 1.6)
    P = _P()
    for s_, off in ((-1, sw), (1, -sw)):
        l = max(0, off) * 0.06
        P.b(s_ * 0.14, 0.03, l, 0.18, 0.28, 0.07, furD)
        P.b(s_ * 0.14, 0, 0.07 + l, 0.15, 0.15, 0.15, fur)
        P.b(s_ * 0.14, 0, 0.22 + l, 0.20, 0.20, 0.14, pants)
        for k in (-1, 0, 1):
            P.b(s_ * 0.14 + 0.05 * k, 0.18, l, 0.025, 0.07, 0.03, claw)
    P.b(0.04, 0.04, 0.36, 0.52, 0.40, 0.18, pants)
    P.b(0.06, 0.06, 0.52, 0.62, 0.46, 0.26, fur)
    P.b(0.10, 0.10, 0.76, 0.66, 0.46, 0.14, furL)
    P.b(0.20, 0.24, 0.56, 0.20, 0.03, 0.26, furL)
    for i in range(6):
        P.b(-0.20 - 0.02 * i, -0.20 - 0.02 * i, 0.60 + 0.07 * i, 0.12, 0.12, 0.09, furD)
    for s_ in (-1, 1):
        P.b(s_ * 0.44 + 0.05, 0.12, 0.40 + s_ * arm, 0.14, 0.16, 0.40, fur)
        P.b(s_ * 0.44 + 0.05, 0.16, 0.30 + s_ * arm, 0.16, 0.20, 0.10, furD)
        for k in (-1, 0, 1):
            P.b(s_ * 0.44 + 0.05 + 0.05 * k, 0.28, 0.28 + s_ * arm, 0.03, 0.09, 0.04, claw)
        P.b(s_ * 0.44 + 0.05, 0.10, 0.80, 0.18, 0.28, 0.08, furD)
    for i in range(6):
        P.b(-0.34 - 0.10 * i, -0.34 - 0.10 * i, 0.46 + 0.05 * i + math.sin(t * 3 + i) * 0.04, 0.14 - 0.012 * i, 0.14 - 0.012 * i, 0.12, furD if i % 2 else fur)
    hz = 0.92 + 0.04 * how
    P.b(0.18, 0.18, hz, 0.32, 0.30, 0.24, furL)
    P.b(0.34, 0.34, hz - 0.01, 0.20, 0.20, 0.12, furL)
    P.b(0.34, 0.34, hz - 0.10 * (0.4 + how * 0.6), 0.18, 0.18, 0.05, (96, 30, 36))
    P.b(0.44, 0.44, hz + 0.08, 0.05, 0.05, 0.05, DARK)
    for k in range(3):
        P.b(0.30 + 0.05 * k, 0.45, hz + 0.0, 0.025, 0.02, 0.06, WHITE)
        P.b(0.45, 0.30 + 0.05 * k, hz + 0.0, 0.02, 0.025, 0.06, WHITE)
    for s_ in (-1, 1):
        P.b(0.18 + s_ * 0.13, 0.12, hz + 0.24, 0.06, 0.06, 0.14, furD)
    P.b(0.18, 0.18, hz + 0.22, 0.28, 0.26, 0.06, furD)
    m_eyes(P, 0.34, 0.33, hz + 0.14, (255, 150, 90), (120, 20, 20), 0.06)
    return P


def m_bat_queen(t):
    wing, wingD, skin, cape, gold = (176, 146, 255), (96, 66, 176), (226, 206, 236), (96, 52, 140), (252, 210, 90)
    fl = math.sin(t * 5)
    z0 = 0.30 + 0.07 * math.sin(t * 2.5)
    P = _P()
    for i in range(6):
        P.b(0, 0, z0 - 0.04 - 0.05 * i + 0.0, 0.26 - 0.03 * i, 0.22 - 0.025 * i, 0.07, cape if i % 2 else (70, 36, 108))
    P.b(0, 0, z0 + 0.20, 0.34, 0.26, 0.30, cape)
    P.b(0, 0.14, z0 + 0.24, 0.20, 0.02, 0.22, (50, 24, 80))
    P.b(0.18, 0, z0 + 0.24, 0.02, 0.16, 0.22, (50, 24, 80))
    P.b(0.02, 0.15, z0 + 0.36, 0.06, 0.02, 0.06, gold)
    P.b(0, 0, z0 + 0.50, 0.30, 0.24, 0.08, (60, 30, 90))
    for s_ in (-1, 1):
        P.b(s_ * 0.24, 0.04, z0 + 0.22 + 0.03 * math.sin(t * 3 + s_), 0.09, 0.12, 0.26, skin)
        for k in (-1, 0, 1):
            P.b(s_ * 0.24 + 0.03 * k, 0.12, z0 + 0.18, 0.02, 0.06, 0.04, (60, 30, 90))
    P.b(0, 0, z0 + 0.58, 0.28, 0.24, 0.22, skin)
    P.b(0, 0, z0 + 0.74, 0.30, 0.26, 0.08, (60, 40, 110))
    P.b(0.10, 0.10, z0 + 0.60, 0.12, 0.12, 0.07, mix(skin, 0, ))
    for s_ in (-1, 1):
        P.b(s_ * 0.11, -0.02, z0 + 0.80, 0.07, 0.06, 0.20, (60, 40, 110))
        P.b(s_ * 0.11, -0.02, z0 + 0.84, 0.04, 0.04, 0.12, (230, 170, 220))
    P.b(0, 0, z0 + 0.82, 0.26, 0.22, 0.04, gold)
    for k in range(4):
        P.b(-0.10 + 0.067 * k, 0, z0 + 0.86, 0.04, 0.04, 0.08 + 0.03 * (k % 2), gold)
    P.b(0.05, 0.13, z0 + 0.60, 0.02, 0.01, 0.06, WHITE)
    P.b(0.12, 0.07, z0 + 0.60, 0.01, 0.02, 0.06, WHITE)
    m_eyes(P, 0.14, 0.125, z0 + 0.68, (255, 120, 150), DARK, 0.05)
    for s_ in (1, -1):
        m_wing(P, s_, 0, -0.02, z0 + 0.34, 9, 0.14, fl * 0.26 + 0.10, wing, wingD, (60, 30, 110), 0.11, 0.04, 0.16)
    m_ring(P, 0, 0, z0 + 0.50, 0.70, 0.70, 4, 0.08, (255, 160, 220), t, 1.6, 0.07)
    return P


def m_orc_chief(t):
    skin, skinD, plate, plateL = (116, 176, 98), (80, 132, 66), (86, 90, 104), (150, 156, 172)
    leath, bone, red, gold = (104, 72, 44), (242, 240, 226), (176, 40, 40), (240, 200, 80)
    sw, arm = math.sin(t * 3.5), math.sin(t * 3) * 0.04
    P = _P()
    m_legs2(P, sw, 0.14, 0.17, 0.19, 0.08, 0.14, 0.10, plate, plateL, (50, 44, 40))
    P.b(0, 0, 0.32, 0.66, 0.46, 0.10, leath)
    for i in range(4):
        P.b(-0.24 + 0.16 * i, 0.245, 0.30, 0.07, 0.04, 0.09, bone)
    P.b(0.345, 0.0, 0.30, 0.05, 0.07, 0.09, bone)
    P.b(0, 0, 0.42, 0.72, 0.50, 0.34, plate)
    P.b(0, 0.26, 0.46, 0.50, 0.02, 0.26, plateL)
    P.b(0.37, 0, 0.46, 0.02, 0.30, 0.26, plateL)
    P.b(0.0, 0.27, 0.58, 0.14, 0.02, 0.14, red)
    for i in range(3):
        P.b(0, 0.28, 0.46 + 0.08 * i, 0.46, 0.01, 0.02, plate)
    for s_ in (-1, 1):
        P.b(s_ * 0.48, 0, 0.74, 0.26, 0.38, 0.12, plateL)
        for k in range(3):
            P.b(s_ * 0.48, -0.10 + 0.10 * k, 0.86, 0.06, 0.06, 0.12, bone)
        P.b(s_ * 0.50, 0, 0.40 - s_ * arm, 0.16, 0.20, 0.36, skin)
        P.b(s_ * 0.50, 0, 0.32 - s_ * arm, 0.20, 0.24, 0.10, plate)
    P.b(0, 0, 0.78, 0.40, 0.34, 0.22, skin)
    P.b(0.12, 0.12, 0.78, 0.22, 0.22, 0.09, skinD)
    P.b(0.20, 0.26, 0.82, 0.04, 0.04, 0.12, bone)
    P.b(0.26, 0.20, 0.82, 0.04, 0.04, 0.12, bone)
    P.b(0.0, 0.18, 0.88, 0.26, 0.01, 0.03, red)
    P.b(0, 0, 0.98, 0.44, 0.38, 0.08, plate)
    P.b(0, 0, 1.06, 0.20, 0.20, 0.06, plateL)
    for s_ in (-1, 1):
        P.b(s_ * 0.26, 0, 0.98, 0.06, 0.06, 0.14, bone)
        P.b(s_ * 0.31, 0, 1.12, 0.05, 0.05, 0.10, bone)
    P.b(-0.30, -0.30, 0.50, 0.04, 0.04, 0.80, leath)
    P.b(-0.30, -0.30, 1.28, 0.16, 0.12, 0.14, bone)
    P.b(-0.30, -0.30, 1.40, 0.06, 0.06, 0.08, red)
    P.b(0.58, 0.22, 0.10 - arm, 0.06, 0.06, 1.00, leath)
    P.b(0.58, 0.22, 0.90 - arm, 0.08, 0.40, 0.30, (186, 192, 208))
    P.b(0.58, 0.46, 0.94 - arm, 0.08, 0.10, 0.22, (230, 236, 246))
    P.b(0.58, -0.02, 1.00 - arm, 0.10, 0.10, 0.10, plate)
    m_eyes(P, 0.215, 0.185, 0.88, (255, 232, 60), (200, 30, 30), 0.065)
    return P


def m_goblin_king(t):
    sk, skD, gold, red, fur = (118, 204, 106), (84, 150, 72), (246, 206, 72), (160, 30, 44), (236, 232, 222)
    leath = (116, 80, 48)
    sw, arm = math.sin(t * 3.5), math.sin(t * 3) * 0.04
    P = _P()
    m_legs2(P, sw * 0.7, 0.13, 0.15, 0.17, 0.07, 0.12, 0.08, skD, (96, 70, 48), (60, 44, 34))
    P.b(0, 0, 0.26, 0.62, 0.46, 0.34, sk)
    P.b(0, 0.245, 0.30, 0.42, 0.02, 0.26, mix(sk, 0.2))
    P.b(0, 0, 0.58, 0.66, 0.48, 0.14, red)
    P.b(0, 0.255, 0.60, 0.66, 0.02, 0.04, gold)
    for i in range(5):
        a = math.pi * (0.15 + 0.7 * i / 4)
        P.b(0.33 * math.cos(a) * 0.9, 0.255, 0.58 - 0.09 * math.sin(a) + 0.04, 0.05, 0.03, 0.05, gold)
    P.b(-0.10, 0.28, 0.46, 0.10, 0.02, 0.10, gold)
    P.b(0, 0, 0.72, 0.84, 0.50, 0.12, fur)
    for i in range(7):
        P.b(-0.34 + 0.115 * i, 0.26, 0.72, 0.06, 0.03, 0.06, (60, 30, 36))
    for s_ in (-1, 1):
        P.b(s_ * 0.44, 0, 0.30 - s_ * arm, 0.14, 0.18, 0.46, sk)
        P.b(s_ * 0.44, 0, 0.30 - s_ * arm, 0.17, 0.21, 0.06, gold)
        P.b(s_ * 0.44, 0, 0.22 - s_ * arm, 0.16, 0.20, 0.08, skD)
    P.b(0.50, 0.14, 0.08 - arm, 0.06, 0.06, 0.86, gold)
    P.b(0.50, 0.14, 0.92 - arm, 0.20, 0.20, 0.20, (180, 40, 60))
    for (dx, dy, dz) in ((0.12, 0, 0.08), (-0.12, 0, 0.08), (0, 0.12, 0.08), (0, -0.12, 0.08), (0, 0, 0.20)):
        P.b(0.50 + dx, 0.14 + dy, 0.92 + dz - arm, 0.06, 0.06, 0.06, gold)
    P.b(0, 0, 0.84, 0.46, 0.38, 0.28, sk)
    P.b(0.13, 0.13, 0.84, 0.22, 0.22, 0.10, skD)
    P.b(0.32, 0.04, 0.96, 0.18, 0.05, 0.07, sk)
    P.b(0.04, 0.32, 0.96, 0.05, 0.18, 0.07, sk)
    P.b(0.16, 0.24, 0.87, 0.04, 0.03, 0.07, WHITE)
    P.b(0.24, 0.16, 0.87, 0.03, 0.04, 0.07, WHITE)
    P.b(0.12, 0.24, 0.96, 0.08, 0.03, 0.08, mix(sk, 0.3))
    P.b(0, 0, 1.12, 0.40, 0.34, 0.06, gold)
    for (dx, dy) in ((-0.15, -0.12), (0.15, -0.12), (-0.15, 0.12), (0.15, 0.12), (0, 0)):
        P.b(dx, dy, 1.18, 0.07, 0.07, 0.14, gold)
    P.b(0.0, 0.18, 1.14, 0.08, 0.03, 0.05, (230, 50, 60))
    m_eyes(P, 0.235, 0.195, 0.98, (255, 220, 60), (180, 30, 30), 0.065)
    return P


def m_beholder(t):
    col, colD, colL = (166, 70, 126), (118, 46, 92), (200, 100, 160)
    z0 = 0.62 + 0.06 * math.sin(t * 2)
    P = _P()
    prof = [0.40, 0.58, 0.72, 0.80, 0.84, 0.80, 0.72, 0.58, 0.40]
    z = z0
    for i, wd in enumerate(prof):
        P.b(0, 0, z, wd, wd, 0.085, colL if i == len(prof) - 1 else (col if i % 2 else colD))
        z += 0.085
    zc = z0 + 0.30
    P.b(0, 0.44, zc, 0.40, 0.02, 0.36, WHITE)
    P.b(0.44, 0, zc, 0.02, 0.40, 0.36, WHITE)
    pu = 0.5 + 0.5 * math.sin(t * 2.5)
    iris = mix((70, 220, 90), pu * 0.4)
    P.b(0, 0.455, zc + 0.04, 0.26, 0.02, 0.26, iris)
    P.b(0.455, 0, zc + 0.04, 0.02, 0.26, 0.26, iris)
    P.b(0, 0.47, zc + 0.10, 0.10, 0.02, 0.14, DARK)
    P.b(0.47, 0, zc + 0.10, 0.02, 0.10, 0.14, DARK)
    P.b(0.06, 0.475, zc + 0.20, 0.03, 0.01, 0.03, WHITE)
    P.b(0.475, 0.06, zc + 0.20, 0.01, 0.03, 0.03, WHITE)
    P.b(0, 0.40, z0 + 0.04, 0.58, 0.04, 0.14, (70, 10, 36))
    P.b(0.40, 0, z0 + 0.04, 0.04, 0.58, 0.14, (70, 10, 36))
    for i in range(8):
        P.b(-0.26 + 0.075 * i, 0.425, z0 + 0.12, 0.045, 0.03, 0.06, WHITE)
        P.b(-0.26 + 0.075 * i, 0.425, z0 + 0.02, 0.045, 0.03, 0.05, WHITE)
        P.b(0.425, -0.26 + 0.075 * i, z0 + 0.12, 0.03, 0.045, 0.06, WHITE)
    cols = [(255, 70, 70), (70, 140, 255), (255, 220, 60), (120, 255, 120), (255, 120, 255), (120, 255, 255), (255, 160, 60), (190, 120, 255), (255, 255, 255), (60, 255, 190)]
    ztop = z0 + 0.76
    for i in range(10):
        a = i / 10 * math.tau
        wob = math.sin(t * 3 + i * 1.3) * 0.05
        ca, sa = math.cos(a), math.sin(a)
        for k in range(4):
            r_ = 0.12 + 0.09 * k
            P.b(ca * r_ + wob * k * 0.6, sa * r_ + wob * k * 0.4, ztop - 0.04 + k * 0.10, 0.07 - 0.005 * k, 0.07 - 0.005 * k, 0.12, colD if k % 2 else col)
        ex, ey, ez = ca * 0.46 + wob * 2.4, sa * 0.46 + wob * 1.6, ztop + 0.34
        P.b(ex, ey, ez, 0.14, 0.14, 0.14, WHITE)
        P.b(ex + 0.04, ey + 0.07, ez + 0.03, 0.07, 0.02, 0.07, cols[i])
        P.b(ex + 0.07, ey + 0.04, ez + 0.03, 0.02, 0.07, 0.07, cols[i])
    return P


def m_minotaur(t):
    fur, dk, sk, bone = (116, 74, 52), (70, 46, 34), (156, 100, 70), (242, 234, 210)
    gold, steel = (226, 186, 72), (206, 212, 224)
    sw, arm = math.sin(t * 3), math.sin(t * 3) * 0.04
    P = _P()
    m_legs2(P, sw * 0.8, 0.13, 0.16, 0.19, 0.08, 0.20, 0.12, fur, fur, (40, 30, 30))
    P.b(0, 0, 0.40, 0.58, 0.40, 0.10, (150, 40, 40))
    P.b(0, 0.215, 0.24, 0.30, 0.02, 0.20, (130, 30, 34))
    P.b(0, 0, 0.50, 0.72, 0.46, 0.36, sk)
    P.b(0, 0.24, 0.54, 0.46, 0.02, 0.22, fur)
    for i in range(3):
        P.b(-0.10 + 0.10 * i, 0.26, 0.60 + 0.03 * (i % 2), 0.04, 0.02, 0.10, dk)
    P.b(0, 0, 0.84, 0.82, 0.50, 0.14, sk)
    for s_ in (-1, 1):
        P.b(s_ * 0.50, 0, 0.88, 0.20, 0.34, 0.14, sk)
        P.b(s_ * 0.50, 0, 0.44 - s_ * arm, 0.18, 0.22, 0.46, sk)
        P.b(s_ * 0.50, 0, 0.44 - s_ * arm, 0.20, 0.24, 0.08, gold)
        P.b(s_ * 0.50, 0, 0.36 - s_ * arm, 0.22, 0.26, 0.10, dk)
    P.b(0.0, 0.20, 0.96, 0.50, 0.02, 0.06, gold)
    for i in range(5):
        P.b(-0.20 + 0.10 * i, 0.22, 0.92 - 0.03 * math.sin(i), 0.06, 0.03, 0.06, steel)
    P.b(0, 0.02, 0.98, 0.40, 0.34, 0.30, fur)
    P.b(0.12, 0.17, 0.98, 0.22, 0.20, 0.16, (196, 146, 126))
    P.b(0.24, 0.27, 1.02, 0.05, 0.05, 0.05, DARK)
    P.b(0.14, 0.31, 1.02, 0.05, 0.03, 0.05, DARK)
    P.b(0.17, 0.30, 0.96, 0.10, 0.04, 0.03, gold)
    P.b(0.17, 0.30, 0.90, 0.07, 0.03, 0.07, gold)
    for s_ in (-1, 1):
        P.b(s_ * 0.24, 0.0, 1.14, 0.14, 0.07, 0.07, bone)
        P.b(s_ * 0.34, 0.0, 1.18, 0.12, 0.07, 0.07, bone)
        P.b(s_ * 0.42, 0.0, 1.24, 0.07, 0.07, 0.12, bone)
        P.b(s_ * 0.40, 0.0, 1.34, 0.05, 0.05, 0.08, (212, 204, 180))
        P.b(s_ * 0.36, 0.0, 0.98, 0.12, 0.05, 0.10, fur)
    m_eyes(P, 0.20, 0.18, 1.08, (255, 80, 40), DARK, 0.065)
    P.b(0.62, 0.20, 0.10 - arm, 0.07, 0.07, 1.00, (122, 86, 52))
    P.b(0.62, 0.20, 1.06 - arm, 0.10, 0.18, 0.04, steel)
    for s_ in (-1, 1):
        P.b(0.62, 0.20 + s_ * 0.24, 0.94 - arm, 0.10, 0.28, 0.34, steel)
        P.b(0.62, 0.20 + s_ * 0.34, 0.98 - arm, 0.08, 0.06, 0.26, (244, 248, 252))
    return P


def m_lich(t):
    z0 = 0.14 + 0.05 * math.sin(t * 2)
    robe, robeD, bone, boneD = (86, 52, 130), (50, 30, 82), (240, 236, 216), (192, 188, 172)
    gold, glow = (246, 206, 72), (130, 255, 140)
    arm = math.sin(t * 2.5) * 0.04
    P = _P()
    for i in range(7):
        a = i * math.tau / 7
        P.b(math.cos(a) * 0.22, math.sin(a) * 0.20, z0 - 0.12 - 0.04 * math.sin(t * 4 + i), 0.12, 0.12, 0.14, robeD if i % 2 else robe)
    for i, (wd, h) in enumerate([(0.56, 0.14), (0.52, 0.16), (0.46, 0.18), (0.40, 0.16), (0.36, 0.12)]):
        P.b(0, 0, z0 + sum(x[1] for x in [(0.56, 0.14), (0.52, 0.16), (0.46, 0.18), (0.40, 0.16), (0.36, 0.12)][:i]), wd, wd * 0.82, h, robe if i % 2 == 0 else robeD)
    P.b(0, 0.17, z0 + 0.34, 0.20, 0.02, 0.26, (20, 10, 30))
    for i in range(5):
        P.b(0, 0.185, z0 + 0.36 + i * 0.05, 0.18 - 0.01 * i, 0.01, 0.025, bone)
    P.b(0, 0, z0 + 0.76, 0.56, 0.38, 0.08, robeD)
    P.b(0, 0.20, z0 + 0.40, 0.30, 0.02, 0.05, gold)
    for s_ in (-1, 1):
        P.b(s_ * 0.34, 0.04, z0 + 0.34 + s_ * arm, 0.10, 0.16, 0.34, robe)
        P.b(s_ * 0.34, 0.06, z0 + 0.26 + s_ * arm, 0.10, 0.12, 0.08, bone)
        for k in (-1, 0, 1):
            P.b(s_ * 0.34 + 0.03 * k, 0.14, z0 + 0.24 + s_ * arm, 0.02, 0.06, 0.03, bone)
        m_flame(P, s_ * 0.34, 0.18, z0 + 0.30 + s_ * arm, t, 0.08, 2, s_)
    P.b(0, 0, z0 + 0.84, 0.30, 0.24, 0.24, bone)
    P.b(0.05, 0.05, z0 + 0.80, 0.22, 0.18, 0.06, boneD)
    P.b(0, 0.125, z0 + 0.84, 0.18, 0.02, 0.05, DARK)
    for k in range(4):
        P.b(-0.06 + 0.04 * k, 0.13, z0 + 0.82, 0.025, 0.02, 0.03, WHITE if k % 2 else boneD)
    m_eyes(P, 0.15, 0.125, z0 + 0.92, glow, (200, 255, 210), 0.065)
    P.b(0, 0, z0 + 1.08, 0.34, 0.28, 0.04, gold)
    for (dx, dy) in ((-0.15, -0.12), (0.15, -0.12), (-0.15, 0.12), (0.15, 0.12), (0, 0.13), (0.14, 0)):
        P.b(dx, dy, z0 + 1.12, 0.05, 0.05, 0.10, gold)
    P.b(0.0, 0.14, z0 + 1.10, 0.05, 0.03, 0.05, glow)
    P.b(0.40, 0.14, z0 - 0.04, 0.05, 0.05, 1.10, (66, 52, 64))
    P.b(0.40, 0.14, z0 + 1.06, 0.14, 0.14, 0.14, bone)
    P.b(0.40, 0.22, z0 + 1.10, 0.04, 0.02, 0.05, glow)
    P.b(0.46, 0.14, z0 + 1.10, 0.02, 0.04, 0.05, glow)
    m_flame(P, 0.40, 0.14, z0 + 1.20, t, 0.10, 3, 1.0)
    m_ring(P, 0, 0, z0 + 0.60, 0.52, 0.52, 3, 0.09, glow, t, 1.5, 0.08)
    ph = 0.5 + 0.5 * math.sin(t * 3)
    P.b(-0.44, 0.34, z0 + 0.70 + 0.06 * math.sin(t * 2), 0.12, 0.12, 0.12, mix((60, 220, 90), ph * 0.4))
    for i in range(8):
        a = i * math.tau / 8 + t * 0.4
        P.b(math.cos(a) * 0.62, math.sin(a) * 0.62, 0.0, 0.07, 0.07, 0.02, glow)
    return P


def m_mind_flayer(t):
    sk, skD = (160, 112, 202), (112, 78, 154)
    robe, robeD, gold = (68, 34, 104), (42, 22, 70), (246, 206, 72)
    arm = math.sin(t * 2.5) * 0.04
    P = _P()
    for i in range(6):
        a = i * math.tau / 6
        P.b(math.cos(a) * 0.22, math.sin(a) * 0.20, -0.02 + 0.03 * math.sin(t * 3 + i), 0.14, 0.14, 0.10, robeD if i % 2 else robe)
    for i, (wd, h) in enumerate([(0.54, 0.14), (0.50, 0.16), (0.44, 0.18), (0.40, 0.16)]):
        P.b(0, 0, 0.08 + sum(x[1] for x in [(0.54, 0.14), (0.50, 0.16), (0.44, 0.18), (0.40, 0.16)][:i]), wd, wd * 0.8, h, robe if i % 2 == 0 else robeD)
    P.b(0, 0.18, 0.28, 0.08, 0.02, 0.18, gold)
    P.b(0, 0.18, 0.54, 0.40, 0.02, 0.03, gold)
    P.b(0, 0, 0.72, 0.52, 0.34, 0.08, robeD)
    P.b(0, -0.12, 0.76, 0.62, 0.10, 0.50, robeD)
    P.b(-0.30, 0.0, 0.76, 0.10, 0.34, 0.40, robeD)
    P.b(0.30, -0.02, 0.76, 0.06, 0.30, 0.34, robeD)
    P.b(0, -0.14, 1.10, 0.70, 0.08, 0.16, robe)
    for s_ in (-1, 1):
        P.b(s_ * 0.34, 0.04, 0.32 + s_ * arm, 0.10, 0.16, 0.34, robe)
        P.b(s_ * 0.34, 0.06, 0.24 + s_ * arm, 0.10, 0.12, 0.09, sk)
        for k in (-1, 0, 1):
            P.b(s_ * 0.34 + 0.03 * k, 0.14, 0.22 + s_ * arm, 0.02, 0.07, 0.03, skD)
    P.b(0, 0, 0.82, 0.30, 0.24, 0.26, sk)
    P.b(0, 0, 1.06, 0.26, 0.22, 0.06, skD)
    P.b(0, 0.125, 0.88, 0.22, 0.02, 0.05, (60, 20, 70))
    P.b(0.145, 0, 0.88, 0.02, 0.18, 0.05, (60, 20, 70))
    m_eyes(P, 0.16, 0.13, 0.96, (255, 255, 255), (200, 200, 255), 0.07)
    for i in range(4):
        sw_ = math.sin(t * 3 + i * 1.1) * 0.03
        for k in range(5):
            P.b(-0.11 + 0.073 * i + sw_ * k * 0.6, 0.14 + 0.03 * k + sw_ * k * 0.4, 0.80 - k * 0.075, 0.06 - 0.004 * k, 0.06 - 0.004 * k, 0.09, skD if k % 2 else sk)
    P.b(0.42, 0.14, 0.00, 0.05, 0.05, 1.04, (80, 60, 100))
    ph = 0.5 + 0.5 * math.sin(t * 3)
    P.b(0.42, 0.14, 1.04, 0.16, 0.16, 0.16, mix((255, 130, 255), ph * 0.4))
    P.b(0.42, 0.14, 1.20, 0.07, 0.07, 0.07, gold)
    m_ring(P, 0.42, 0.14, 1.12, 0.22, 0.22, 3, 0.05, (255, 170, 255), t, 3.0, 0.03)
    m_ring(P, 0, 0, 0.9, 0.56, 0.56, 4, 0.05, (200, 150, 255), t, -1.5, 0.05)
    return P


# ------------------------------------------------------------------ registro dos monstros v3
MONSTERS_V3 = {
    "slime": m_ooze, "kobold": m_kobold, "goblin": m_goblin, "bat": m_bat, "stirge": m_stirge,
    "skeleton": m_skeleton, "zombie": m_zombie, "gnoll": m_gnoll, "wolfman": m_wolfman,
    "orc": m_orc, "ghost": m_ghost, "mimic": m_mimic, "gelatinous_cube": m_cube, "rust_monster": m_rust,
    "harpy": m_harpy, "displacer_beast": m_displacer, "ogre": m_ogre, "owlbear": m_owlbear, "troll": m_troll,
    "golem": m_golem, "gargoyle": m_gargoyle, "basilisk": m_basilisk, "hell_hound": m_hellhound,
    "dragon": m_dragon, "goblin_chief": m_goblin_chief, "werewolf": m_werewolf, "bat_queen": m_bat_queen,
    "orc_chief": m_orc_chief, "goblin_king": m_goblin_king, "beholder": m_beholder, "minotaur": m_minotaur,
    "lich": m_lich, "mind_flayer": m_mind_flayer}
NEW_PARTS.update(MONSTERS_V3)
ENEMY_NAMES.update({"slime": "Gosma Ácida", "stirge": "Estirge", "rust_monster": "Monstro da Ferrugem", "harpy": "Harpia",
                    "displacer_beast": "Fera Deslocadora", "gargoyle": "Gárgula", "basilisk": "Basilisco", "hell_hound": "Cão Infernal"})
ENEMY_COLOR.update({"stirge": (178, 84, 62), "rust_monster": (196, 116, 64), "harpy": (150, 100, 70), "displacer_beast": (46, 70, 104),
                    "gargoyle": (122, 126, 140), "basilisk": (112, 126, 60), "hell_hound": (255, 110, 40)})
ENEMY_SCALE.update({"wolfman": 1.75, "zombie": HERO_SCALE, "skeleton": HERO_SCALE, "goblin": 1.12})   # zumbi/esqueleto = tamanho do herói
ENEMY_SCALE.update({"stirge": 0.95, "rust_monster": 1.1, "harpy": 1.1, "displacer_beast": 1.2, "gargoyle": 1.1, "basilisk": 1.2,
                    "hell_hound": 1.2, "goblin_chief": 1.5, "werewolf": 1.5, "bat_queen": 1.4, "orc_chief": 1.4})
# --- tamanhos visuais v4: os bichos pequenos eram ~50% do herói e sumiam no cenário.
# STOP_SCALE guarda a escala ANTIGA só para calcular a distância de parada do herói (combate igual ao de antes).
STOP_SCALE = {k: ENEMY_SCALE.get(k, 1.0) for k in
              ("slime", "kobold", "goblin", "bat", "stirge", "gnoll", "ghost", "mimic", "rust_monster",
               "displacer_beast", "basilisk", "gargoyle")}
ENEMY_SCALE.update({"slime": 1.45, "kobold": 1.45, "goblin": 1.25, "bat": 1.3, "stirge": 1.3, "gnoll": 1.4,
                    "ghost": 1.15, "mimic": 1.15, "rust_monster": 1.2, "displacer_beast": 1.3,
                    "basilisk": 1.35, "gargoyle": 1.2})
# --- os GRANDES precisam ser claramente maiores que o herói (altura final dele = 1.38):
# orc 1.65 | wolfman 1.9 | ogro 2.2 | urso-coruja 1.9 | troll 2.1 | golem 2.2 | cubo 1.5 | cão infernal (comprido) 1.45
ENEMY_SCALE.update({"orc": 1.7, "wolfman": 1.9, "ogre": 1.8, "owlbear": 1.6, "troll": 1.95, "golem": 1.65,
                    "gelatinous_cube": 1.55, "hell_hound": 1.45, "gargoyle": 1.3,
                    "goblin_chief": 1.75, "werewolf": 1.75, "bat_queen": 1.5, "orc_chief": 1.5,
                    "minotaur": 1.6, "lich": 1.5, "mind_flayer": 1.6})
TIERS[:] = [["slime", "kobold", "goblin", "bat", "stirge"],
            ["skeleton", "zombie", "gnoll", "wolfman"],
            ["orc", "ghost", "mimic", "gelatinous_cube", "rust_monster", "harpy", "displacer_beast"],
            ["ogre", "owlbear", "troll", "golem", "gargoyle", "basilisk", "hell_hound"]]
REG_KINDS[:] = [k for tier_ in TIERS for k in tier_]


def regular_pool(f):
    pool = list(TIERS[0])
    for i, start in ((1, 3), (2, 6), (3, 9)):
        if f >= start:
            pool += TIERS[i]
    return pool


HEROES = [
    # hp = vidas iniciais | crit = chance de crítico | damage = bônus de dano base
    {"id": "knight", "name": "Cavaleiro", "title": "Equilíbrio de ferro", "hp": 4, "crit": 0.15, "damage": 1, "color": (132, 140, 168)},
    {"id": "ranger", "name": "Arquera", "title": "Flecha certeira", "hp": 3, "crit": 0.40, "damage": 0, "color": (104, 150, 110)},
    {"id": "mage", "name": "Maga", "title": "Luz arcana", "hp": 3, "crit": 0.08, "damage": 3, "color": (160, 92, 190)},
    {"id": "guardian", "name": "Guardião", "title": "Vigor da muralha", "hp": 5, "crit": 0.06, "damage": 0, "color": (196, 118, 76)},
    # Ladino: a MENOR vida (2), dano médio (2) e o MAIOR crítico (60%) -> canhão de vidro
    {"id": "rogue", "name": "Ladino", "title": "Golpe nas sombras", "hp": 2, "crit": 0.60, "damage": 2, "color": (196, 48, 68)},
]

# ------------------------------------------------------------------ atributos
ATTR_KEYS = ("des", "for", "int", "con", "sab", "car")
ATTR_NAMES = {"des": "Destreza", "for": "Força", "int": "Inteligência", "con": "Constituição", "sab": "Sabedoria", "car": "Carisma"}
ATTR_INFO = {"des": "+1% de crítico por ponto",
             "for": "+1 de dano a cada 2 pontos",
             "int": "-3% de recarga das habilidades",
             "con": "+1 vida a cada 4 pontos",
             "sab": "+3% de recuperação de fôlego",
             "car": "+4% de ouro por ponto"}
ATTR_BASE, ATTR_MAX, ATTR_POINTS = 8, 18, 10     # valor inicial, teto e pontos livres na criação
# bônus que cada classe dá (somado ao valor inicial)
CLASS_ATTRS = {
    "knight":   {"for": 2, "con": 1, "car": 1},
    "ranger":   {"des": 3, "sab": 1},
    "mage":     {"int": 3, "sab": 2},
    "guardian": {"con": 3, "for": 1, "sab": 1},
    "rogue":    {"des": 3, "car": 2},
}


RACES = [
    {"id": "human",    "name": "Humano",   "bonus": {"for": 1, "sab": 1, "car": 1}},
    {"id": "elf",      "name": "Elfo",     "bonus": {"des": 2, "int": 1}},
    {"id": "dwarf",    "name": "Anão",     "bonus": {"con": 2, "for": 1}},
    {"id": "orc",      "name": "Orc",      "bonus": {"for": 3, "con": 1}},
    {"id": "halfling", "name": "Halfling", "bonus": {"des": 1, "sab": 1, "car": 2}},
    {"id": "tiefling", "name": "Tiefling", "bonus": {"int": 2, "car": 1}},
]
RACE_IDS = [r["id"] for r in RACES]
RACE_DESC = {
    "human":    ("Versáteis e adaptáveis,", "sobrevivem em qualquer", "canto do mundo."),
    "elf":      ("Ágeis e de mente afiada,", "dominam o arco e a", "magia."),
    "dwarf":    ("Robustos e teimosos,", "feitos para aguentar", "qualquer pancada."),
    "orc":      ("Força bruta pura,", "temidos em todo campo", "de batalha."),
    "halfling": ("Pequenos e sortudos,", "ótimos em negócios", "e em achar ouro."),
    "tiefling": ("Sangue infernal com", "carisma e talento", "arcano."),
}


def class_attrs(hero_id, race_id="human"):
    """Atributos iniciais: valor base + bônus da classe + bônus da raça."""
    b = CLASS_ATTRS.get(hero_id, {})
    rb = next((r["bonus"] for r in RACES if r["id"] == race_id), {})
    return {k: ATTR_BASE + b.get(k, 0) + rb.get(k, 0) for k in ATTR_KEYS}


# ------------------------------------------------------------------ habilidades
# 3 por herói. "cd" = recarga (em rodadas de combate; ajuste à unidade do combate novo).
# "fx" descreve o efeito de forma neutra, para o combate novo interpretar:
#   dmg      multiplicador sobre dmg_value()          aoe       atinge todos os inimigos da sala
#   crit     True = crítico garantido                  crit_up   (+chance, rodadas) de crítico extra
#   stun     rodadas que o inimigo perde               dot       (fração do dano por rodada, rodadas)
#   shield   golpes que o herói ignora                 evade     ataques inimigos que erram
#   reflect  multiplicador devolvido no próximo golpe recebido
#   heal     corações recuperados (respeita maxhp)
ABILITIES = {
    "knight": [
        {"id": "golpe_firme", "name": "Golpe Firme", "cd": 2,
         "desc": "Ataque pesado com a espada: 150% do dano.",
         "fx": {"dmg": 1.5}},
        {"id": "postura_escudo", "name": "Postura de Escudo", "cd": 4,
         "desc": "Ergue o escudo e ignora o próximo golpe recebido.",
         "fx": {"shield": 1}},
        {"id": "investida_heroica", "name": "Investida Heroica", "cd": 5,
         "desc": "Avança com tudo: 220% do dano e atordoa o inimigo por 1 rodada.",
         "fx": {"dmg": 2.2, "stun": 1}},
    ],
    "ranger": [
        {"id": "tiro_preciso", "name": "Tiro Preciso", "cd": 3,
         "desc": "Flecha mirada no ponto fraco: 120% do dano e crítico garantido.",
         "fx": {"dmg": 1.2, "crit": True}},
        {"id": "chuva_flechas", "name": "Chuva de Flechas", "cd": 4,
         "desc": "Saraivada que atinge todos os inimigos da sala com 80% do dano.",
         "fx": {"dmg": 0.8, "aoe": True}},
        {"id": "passo_agil", "name": "Passo Ágil", "cd": 4,
         "desc": "Esquiva o próximo ataque e ganha +20% de crítico por 2 rodadas.",
         "fx": {"evade": 1, "crit_up": (0.20, 2)}},
    ],
    "mage": [
        {"id": "raio_arcano", "name": "Raio Arcano", "cd": 2,
         "desc": "Descarga de energia pura: 180% do dano.",
         "fx": {"dmg": 1.8}},
        {"id": "bola_fogo", "name": "Bola de Fogo", "cd": 4,
         "desc": "Explosão em todos os inimigos: 140% do dano e queimadura (30% por rodada, 3 rodadas).",
         "fx": {"dmg": 1.4, "aoe": True, "dot": (0.30, 3)}},
        {"id": "luz_restauradora", "name": "Luz Restauradora", "cd": 6,
         "desc": "Magia de cura: recupera 1 coração.",
         "fx": {"heal": 1}},
    ],
    "guardian": [
        {"id": "muralha", "name": "Muralha", "cd": 5,
         "desc": "Postura inabalável: ignora os próximos 2 golpes recebidos.",
         "fx": {"shield": 2}},
        {"id": "contragolpe", "name": "Contragolpe", "cd": 3,
         "desc": "Devolve 200% do dano ao inimigo no próximo golpe que receber.",
         "fx": {"reflect": 2.0}},
        {"id": "pancada_sismica", "name": "Pancada Sísmica", "cd": 4,
         "desc": "Martelada no chão: 130% do dano e atordoa o inimigo por 1 rodada.",
         "fx": {"dmg": 1.3, "stun": 1}},
    ],
    "rogue": [
        {"id": "golpe_furtivo", "name": "Golpe Furtivo", "cd": 4,
         "desc": "Ataque pelas costas: 250% do dano.",
         "fx": {"dmg": 2.5}},
        {"id": "veneno", "name": "Lâmina Envenenada", "cd": 3,
         "desc": "Aplica veneno: 60% do dano e 25% por rodada durante 3 rodadas.",
         "fx": {"dmg": 0.6, "dot": (0.25, 3)}},
        {"id": "sumir_sombras", "name": "Sumir nas Sombras", "cd": 5,
         "desc": "Desaparece: esquiva os próximos 2 ataques e o próximo golpe é crítico.",
         "fx": {"evade": 2, "crit": True}},
    ],
}
for _h in HEROES:
    _h["abilities"] = ABILITIES[_h["id"]]      # acesso: self.hero["abilities"]

# ------------------------------------------------- habilidades de combate (tempo real)
# cd = recarga em segundos | cast = (duração total, instante do efeito) | key = tecla
SKILLS = {
    "knight": [{"id": "investida", "name": "Investida", "key": "Q", "cd": 7.0, "cast": (0.55, 0.22), "color": (190, 70, 50)}],
    "ranger": [{"id": "tiro_preciso", "name": "Tiro Preciso", "key": "Q", "cd": 6.0, "cast": (0.95, 0.70), "color": (190, 150, 40)}],
    "mage": [
        {"id": "bola_fogo", "name": "Bola de Fogo", "key": "Q", "cd": 7.0, "cast": (0.80, 0.50), "color": (210, 80, 30)},
        {"id": "cristais_gelo", "name": "Cristais de Gelo", "key": "R", "cd": 10.0, "cast": (0.75, 0.45), "color": (50, 120, 200)},
    ],
    "guardian": [{"id": "pancada_sismica", "name": "Pancada Sísmica", "key": "Q", "cd": 8.0, "cast": (0.85, 0.50), "color": (150, 100, 60)}],
    "rogue": [{"id": "golpe_furtivo", "name": "Golpe Furtivo", "key": "Q", "cd": 6.0, "cast": (0.45, 0.18), "color": (120, 60, 160)}],
}
SKILL_FX = {"bola_fogo": (255, 150, 40), "cristais_gelo": (170, 225, 255), "tiro_preciso": (255, 226, 120),
            "investida": (255, 255, 255), "pancada_sismica": (190, 150, 100), "golpe_furtivo": (150, 90, 200)}


def kind_for(f):
    if f % 5 == 0:
        return BOSS_KINDS[(f // 5 - 1) % len(BOSS_KINDS)]
    return REG_KINDS[(f - 1) % len(REG_KINDS)]


def is_duplo(f):
    return f >= 3 and f % 5 != 0 and f % 3 == 0


# ------------------------------------------------- geração procedural de andares
# ------------------------------------------------ cenário: cavernas, rios e decoração nova
CAVE_PALS = [  # chão A, chão B, parede A, parede B, fundo, brilho (cristais / musgo / poeira)
    ((78, 72, 70), (64, 60, 60), (52, 50, 58), (40, 38, 48), (3, 3, 7), (80, 170, 220)),
    ((60, 72, 64), (50, 60, 56), (46, 58, 56), (36, 46, 46), (2, 7, 7), (96, 214, 140)),
    ((98, 70, 54), (82, 58, 46), (72, 52, 46), (58, 42, 38), (9, 3, 2), (240, 120, 66)),
    ((74, 66, 92), (60, 53, 76), (54, 48, 74), (42, 37, 60), (5, 3, 11), (184, 112, 240)),
]
LIQUIDS = {
    "agua": dict(deep=(14, 40, 70), light=(70, 120, 150), glow=None, nome="RIO SOMBRIO",
                 ponte=((150, 108, 60), (110, 76, 44))),
    "gelo": dict(deep=(52, 86, 116), light=(150, 192, 214), glow=None, nome="RIO GELADO",
                 ponte=((150, 108, 60), (110, 76, 44))),
    "lava": dict(deep=(138, 26, 8), light=(255, 136, 40), glow=(255, 96, 24), nome="RIO DE LAVA",
                 ponte=((96, 92, 106), (66, 64, 78))),
}
CRYSTAL_COL = {"crystal_c": (90, 200, 255), "crystal_g": (110, 255, 160),
               "crystal_o": (255, 140, 90), "crystal_p": (200, 130, 255)}
CRYSTAL_KINDS = tuple(CRYSTAL_COL)          # mesma ordem de CAVE_PALS
NEW_SOLID = ("boulder", "rock_pile", "stalagmite", "mushroom", "statue", "brazier") + CRYSTAL_KINDS
NEW_SOFT = ("pebbles", "grass", "shrooms", "puddle", "glowmoss", "skull")
EXTRA_DECOR = set(NEW_SOLID) | set(NEW_SOFT)
FLAT_KINDS = {"puddle", "glowmoss", "pebbles"}            # desenhadas no cenário em cache
NO_SHADOW = FLAT_KINDS | {"grass", "shrooms", "skull"}
GLOW_KINDS = {"shrooms": (60, 220, 170), "mushroom": (70, 230, 180), "glowmoss": (80, 230, 120),
              "brazier": (255, 150, 50)}
GLOW_KINDS.update(CRYSTAL_COL)
GLOW_R = {"glowmoss": 55, "shrooms": 50, "mushroom": 75, "brazier": 95}


def decor_parts2(kind, t=0.0):
    """Voxels (dx, dy, dz, w, d, h, cor) das decorações novas."""
    if kind in CRYSTAL_COL:
        col = CRYSTAL_COL[kind]
        d, l = shade(col, 0.6), mix(col, 0.4)
        return [(0.0, 0.05, 0, 0.5, 0.42, 0.10, (86, 84, 98)),
                (0.08, 0.10, 0.10, 0.14, 0.14, 0.62, col), (0.09, 0.11, 0.72, 0.12, 0.12, 0.14, l),
                (0.28, 0.12, 0.10, 0.16, 0.16, 0.42, d), (0.29, 0.13, 0.52, 0.14, 0.14, 0.10, col),
                (0.16, 0.26, 0.10, 0.14, 0.14, 0.82, col), (0.17, 0.27, 0.92, 0.12, 0.12, 0.16, l),
                (0.32, 0.28, 0.10, 0.10, 0.10, 0.28, l)]
    if kind == "boulder":
        return [(0.0, 0.05, 0, 0.8, 0.62, 0.34, (112, 108, 120)), (0.06, 0.10, 0.34, 0.66, 0.50, 0.28, (128, 124, 138)),
                (0.20, 0.18, 0.62, 0.38, 0.30, 0.14, (142, 138, 152)), (0.62, 0.50, 0, 0.18, 0.18, 0.14, (100, 97, 110))]
    if kind == "rock_pile":
        return [(0.0, 0.0, 0, 0.38, 0.34, 0.22, (110, 108, 120)), (0.40, 0.10, 0, 0.30, 0.30, 0.16, (100, 98, 112)),
                (0.12, 0.40, 0, 0.34, 0.30, 0.18, (122, 120, 132)), (0.08, 0.06, 0.22, 0.22, 0.20, 0.10, (136, 134, 146))]
    if kind == "stalagmite":
        return [(0.0, 0.0, 0, 0.5, 0.5, 0.28, (96, 90, 100)), (0.07, 0.07, 0.28, 0.36, 0.36, 0.30, (108, 102, 114)),
                (0.14, 0.14, 0.58, 0.22, 0.22, 0.30, (120, 114, 126)), (0.20, 0.20, 0.88, 0.10, 0.10, 0.26, (134, 128, 140))]
    if kind == "mushroom":
        cap = (70, 200, 176)
        return [(0.22, 0.22, 0, 0.20, 0.20, 0.46, (226, 214, 190)), (0.0, 0.0, 0.46, 0.64, 0.64, 0.12, shade(cap, 0.85)),
                (0.10, 0.10, 0.58, 0.44, 0.44, 0.10, cap), (0.20, 0.20, 0.68, 0.24, 0.24, 0.06, mix(cap, 0.3)),
                (0.12, 0.50, 0.55, 0.08, 0.08, 0.04, (250, 240, 200)), (0.46, 0.14, 0.55, 0.08, 0.08, 0.04, (250, 240, 200))]
    if kind == "statue":
        return [(0.0, 0.0, 0, 0.56, 0.56, 0.14, (112, 110, 124)), (0.08, 0.08, 0.14, 0.40, 0.40, 0.20, (128, 126, 140)),
                (0.16, 0.16, 0.34, 0.24, 0.24, 0.50, (150, 148, 162)), (0.08, 0.20, 0.58, 0.08, 0.16, 0.26, (140, 138, 152)),
                (0.40, 0.20, 0.58, 0.08, 0.16, 0.26, (140, 138, 152)), (0.20, 0.20, 0.84, 0.16, 0.16, 0.16, (164, 162, 176)),
                (0.26, 0.04, 0.34, 0.04, 0.04, 0.70, (190, 196, 210))]
    if kind == "brazier":
        fl = 0.22 + 0.06 * math.sin(t * 9)
        return [(0.10, 0.10, 0, 0.08, 0.08, 0.36, (60, 56, 64)), (0.40, 0.10, 0, 0.08, 0.08, 0.36, (60, 56, 64)),
                (0.10, 0.40, 0, 0.08, 0.08, 0.36, (60, 56, 64)), (0.40, 0.40, 0, 0.08, 0.08, 0.36, (60, 56, 64)),
                (0.04, 0.04, 0.36, 0.50, 0.50, 0.14, (86, 82, 94)), (0.0, 0.0, 0.50, 0.58, 0.58, 0.06, (110, 104, 120)),
                (0.08, 0.08, 0.54, 0.42, 0.42, 0.06, (255, 110, 30)), (0.18, 0.18, 0.60, 0.22, 0.22, fl, (255, 170, 40)),
                (0.24, 0.24, 0.60 + fl, 0.10, 0.10, 0.14, (255, 230, 120))]
    if kind == "pebbles":
        return [(0.0, 0.10, 0, 0.14, 0.12, 0.04, (150, 146, 156)), (0.22, 0.0, 0, 0.10, 0.10, 0.03, (120, 116, 128)),
                (0.30, 0.26, 0, 0.16, 0.14, 0.05, (136, 132, 144)), (0.08, 0.34, 0, 0.10, 0.09, 0.03, (120, 116, 128))]
    if kind == "grass":
        g1, g2 = (70, 150, 70), (96, 184, 90)
        return [(0.0, 0.0, 0, 0.05, 0.05, 0.22, g1), (0.08, 0.04, 0, 0.05, 0.05, 0.30, g2), (0.16, 0.0, 0, 0.05, 0.05, 0.20, g1),
                (0.04, 0.12, 0, 0.05, 0.05, 0.26, g2), (0.14, 0.14, 0, 0.05, 0.05, 0.32, g1), (0.24, 0.08, 0, 0.05, 0.05, 0.20, g2),
                (0.22, 0.20, 0, 0.05, 0.05, 0.26, g1)]
    if kind == "shrooms":
        st, cp = (230, 220, 200), (70, 220, 190)
        return [(0.04, 0.04, 0, 0.07, 0.07, 0.16, st), (0.0, 0.0, 0.16, 0.15, 0.15, 0.08, cp),
                (0.28, 0.10, 0, 0.06, 0.06, 0.11, st), (0.25, 0.07, 0.11, 0.12, 0.12, 0.07, shade(cp, 0.9)),
                (0.14, 0.30, 0, 0.06, 0.06, 0.13, st), (0.11, 0.27, 0.13, 0.12, 0.12, 0.07, mix(cp, 0.2))]
    if kind == "puddle":
        return [(0.0, 0.0, 0, 0.5, 0.4, 0.02, (40, 70, 120)), (0.06, 0.04, 0.015, 0.3, 0.24, 0.012, (90, 150, 210))]
    if kind == "glowmoss":
        return [(0.0, 0.0, 0, 0.36, 0.30, 0.025, (40, 120, 80)), (0.10, 0.18, 0.02, 0.34, 0.28, 0.02, (70, 200, 120)),
                (0.20, 0.04, 0.02, 0.10, 0.10, 0.03, (150, 255, 190))]
    return [(0.0, 0.0, 0, 0.16, 0.14, 0.14, (230, 230, 215)), (0.03, 0.14, 0.02, 0.10, 0.04, 0.06, (210, 210, 196)),
            (0.02, 0.0, 0.07, 0.04, 0.02, 0.05, DARK)]          # caveira


def gen_river(rng, keys, sc, targets, liquid):
    """Rio de uma borda à outra da sala (1 a 2 células, com curvas). Devolve (água, pontes, vaus, eixo)
    ou None. Sempre deixa pelo menos uma travessia ligando o herói a todos os alvos."""
    keyset = set(keys)
    for _ in range(30):
        axis = rng.choice(("x", "y"))
        cur, wide = rng.randint(2, N - 3), rng.random() < 0.3
        rows = []
        for u in range(N):
            row = [cur]
            if u < N - 1 and rng.random() < 0.35:
                nxt = max(2, min(N - 3, cur + rng.choice((-1, 1))))
                if nxt != cur:
                    row.append(nxt)
                    cur = nxt
            if wide:
                row.append(max(row) + 1)
            rows.append(row)
        cell = (lambda v, u: (v, u)) if axis == "y" else (lambda v, u: (u, v))
        cells = {cell(v, u) for u, row in enumerate(rows) for v in row}
        if cells & keyset:
            continue

        def crossing(u):
            return {cell(v, u) for v in rows[u]}
        order = list(range(1, N - 1))
        rng.shuffle(order)
        chosen = None
        for u in order:
            if all(find_cells(sc, t, False, cells - crossing(u)) for t in targets):
                chosen = [u]
                break
        if chosen is None:
            continue
        if rng.random() < 0.45:
            for u in order:
                if all(abs(u - c) >= 3 for c in chosen):
                    chosen.append(u)
                    break
        bridges, fords = set(), set()
        for u in chosen:
            if liquid != "lava" and rng.random() < 0.3:
                fords |= crossing(u)
            else:
                bridges |= crossing(u)
        return cells - bridges - fords, bridges, fords, axis
    return None


DIRS8 = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
BLOCK_OFF = {"crate": (0.2, 0.2), "barrel": (0.22, 0.22), "pillar": (0.25, 0.25), "rock": (0.2, 0.25)}
SOFT_OFF = {"bones": (0.25, 0.3), "chest": (0.19, 0.29)}
BLOCK_OFF.update({"boulder": (0.10, 0.15), "rock_pile": (0.15, 0.15), "stalagmite": (0.25, 0.25),
                  "statue": (0.22, 0.22), "brazier": (0.20, 0.20), "mushroom": (0.17, 0.17)})
BLOCK_OFF.update({k: (0.25, 0.25) for k in CRYSTAL_KINDS})
SOFT_OFF.update({"pebbles": (0.2, 0.2), "grass": (0.3, 0.3), "shrooms": (0.25, 0.25), "puddle": (0.2, 0.3),
                 "glowmoss": (0.3, 0.3), "skull": (0.35, 0.35)})


def cell_of(x, y):
    return int(math.floor(x)), int(math.floor(y))


def walkable(c, duplo, blocked):
    i, j = c
    if not (0 <= i < N and 0 <= j < N) or c in blocked:
        return False
    if duplo and i == 4 and not (3 <= j <= 4):   # só a rampa liga os dois andares
        return False
    return True


def find_cells(a, b, duplo, blocked):
    """A* na grade N x N (8 direções, sem cortar quina). Devolve lista de células ou None."""
    if not walkable(a, duplo, blocked) or not walkable(b, duplo, blocked):
        return None

    def h(c):
        dx, dy = abs(c[0] - b[0]), abs(c[1] - b[1])
        return max(dx, dy) + 0.414 * min(dx, dy)

    heap = [(h(a), 0.0, a)]
    g, came = {a: 0.0}, {a: None}
    while heap:
        _, cg, cur = heapq.heappop(heap)
        if cur == b:
            break
        if cg > g.get(cur, 1e9):
            continue
        for di, dj in DIRS8:
            n = (cur[0] + di, cur[1] + dj)
            if not walkable(n, duplo, blocked):
                continue
            if di and dj and not (walkable((cur[0] + di, cur[1]), duplo, blocked)
                                  and walkable((cur[0], cur[1] + dj), duplo, blocked)):
                continue
            ng = cg + (1.414 if di and dj else 1.0)
            if ng < g.get(n, 1e9):
                g[n], came[n] = ng, cur
                heapq.heappush(heap, (ng + h(n), ng, n))
    if b not in came:
        return None
    out, c = [], b
    while c is not None:
        out.append(c)
        c = came[c]
    return out[::-1]


def clear_line(p, q, duplo, blocked, r=0.22):
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = max(1, int(math.hypot(dx, dy) / 0.1))
    for k in range(n + 1):
        x, y = p[0] + dx * k / n, p[1] + dy * k / n
        for ox in (-r, r):
            for oy in (-r, r):
                if not walkable(cell_of(x + ox, y + oy), duplo, blocked):
                    return False
    return True


HERO_R = 0.34                  # raio de colisão do herói (círculo no chão)
HERO_FRONT = math.pi / 4       # os modelos dos heróis são construídos olhando para (+1, +1)
# frente de cada monstro no modelo: bípedes olham para (+1,+1); quadrúpedes e dragão, para +x.
# Mímico, cubo, urso-coruja e beholder não giram.
QUAD_FRONT = {"rust_monster", "displacer_beast", "gargoyle", "basilisk", "hell_hound", "dragon"}
NO_TURN = {"mimic", "gelatinous_cube", "owlbear", "beholder"}
# combate estilo Souls: velocidade de perseguição (casas/s) de cada monstro; chefes usam 2.1
FOE_SPEED = {"slime": 1.3, "kobold": 2.3, "goblin": 2.2, "bat": 2.9, "stirge": 3.0, "skeleton": 1.9, "zombie": 1.2,
             "gnoll": 2.1, "wolfman": 2.5, "orc": 1.9, "ghost": 1.6, "mimic": 1.8, "gelatinous_cube": 1.1,
             "rust_monster": 1.9, "harpy": 2.7, "displacer_beast": 2.5, "ogre": 1.5, "owlbear": 1.9, "troll": 1.7,
             "golem": 1.1, "gargoyle": 2.1, "basilisk": 1.9, "hell_hound": 3.0}


def foe_front(kind):
    return 0.0 if kind in QUAD_FRONT else HERO_FRONT
SOLID_KINDS = ("crate", "barrel", "pillar", "rock", "chest") + NEW_SOLID   # decorações que não dá pra atravessar


def angle_diff(a, b):
    """Diferença angular a - b normalizada em [-pi, pi)."""
    return (a - b + math.pi) % math.tau - math.pi


def circle_hits(x, y, r, solids):
    for x0, y0, x1, y1 in solids:
        qx = x0 if x < x0 else (x1 if x > x1 else x)
        qy = y0 if y < y0 else (y1 if y > y1 else y)
        if (x - qx) * (x - qx) + (y - qy) * (y - qy) < r * r - 1e-9:
            return True
    return False


def push_out(x, y, r, solids, rounds=3):
    """Empurra o círculo (x, y, r) para fora das caixas sólidas e das bordas da sala.
    Como só remove a parte do movimento que entra no objeto, o herói DESLIZA pelas quinas."""
    for _ in range(rounds):
        x = min(max(x, r), N - r)
        y = min(max(y, r), N - r)
        moved = False
        for x0, y0, x1, y1 in solids:
            if not (x0 - r < x < x1 + r and y0 - r < y < y1 + r):
                continue
            qx = x0 if x < x0 else (x1 if x > x1 else x)
            qy = y0 if y < y0 else (y1 if y > y1 else y)
            dx, dy = x - qx, y - qy
            d2 = dx * dx + dy * dy
            if d2 >= r * r - 1e-9:
                continue
            if d2 > 1e-9:
                d = math.sqrt(d2)
                x, y = qx + dx / d * r, qy + dy / d * r
            else:   # centro dentro da caixa: sai pelo lado mais próximo
                l, rt, tp, bt = x - x0, x1 - x, y - y0, y1 - y
                m = min(l, rt, tp, bt)
                if m == l:
                    x = x0 - r
                elif m == rt:
                    x = x1 + r
                elif m == tp:
                    y = y0 - r
                else:
                    y = y1 + r
            moved = True
        if not moved:
            break
    return min(max(x, r), N - r), min(max(y, r), N - r)


def segment_clear(p, q, solids, r=HERO_R, step=0.07):
    """True se um círculo de raio r consegue ir de p até q sem encostar em nada sólido nem sair da sala."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = max(1, int(math.hypot(dx, dy) / step))
    lo, hi = r - 1e-6, N - r + 1e-6
    for k in range(n + 1):
        x, y = p[0] + dx * k / n, p[1] + dy * k / n
        if x < lo or y < lo or x > hi or y > hi or circle_hits(x, y, r, solids):
            return False
    return True


def smooth_path(pts, duplo, blocked, solids=None):
    """Puxa o caminho esticado: o herói anda em linha reta sempre que dá.
    Com `solids`, o atalho só vale se o herói inteiro (círculo) passa sem encostar em nada."""
    if solids is None:
        ok = lambda p, q: clear_line(p, q, duplo, blocked)
    else:
        ok = lambda p, q: segment_clear(p, q, solids)
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not ok(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return out


def wchoice(rng, weights):
    r = rng.uniform(0, sum(weights.values()))
    k = None
    for k, w in weights.items():
        r -= w
        if r <= 0:
            break
    return k


def jitter_pal(pal, rng):
    d = [rng.randint(-12, 12) for _ in range(3)]
    f = rng.uniform(0.92, 1.1)
    out = []
    for idx, c in enumerate(pal):
        if idx < 4:
            out.append(tuple(max(0, min(255, int(c[k] * f + d[k]))) for k in range(3)))
        else:
            out.append(c)
    return tuple(out)


def pick_kind(rng, f, avoid=(), bonus=0):
    """Inimigo comum sorteado; o tier mais novo tem peso dobrado. bonus=1 -> um tier acima (elite)."""
    idx = 0
    for i, start in ((1, 3), (2, 6), (3, 9)):
        if f >= start:
            idx = i
    pool = regular_pool(f + 3 * bonus) + TIERS[min(3, idx + bonus)]
    pool2 = [k for k in pool if k not in avoid] or pool
    return rng.choice(pool2)


def gen_floor(f, rng, prev=None, boss_bag=None):
    """Gera um andar inteiro (função pura: só depende de f, rng e do andar anterior)."""
    prev = prev or {}
    boss_bag = boss_bag if boss_bag is not None else []
    avoid = set(prev.get("kinds", ()))

    # ---- tipo de sala
    if f % 5 == 0:
        room = "boss"
    elif f == 1:
        room = "normal"
    else:
        w = {"normal": 50, "swarm": 14, "tesouro": 8}
        if f >= 3:
            w["duplo"] = 16
        if f >= 4:
            w["elite"] = 11
        if prev.get("room") == "boss":
            w["tesouro"] = 30            # respiro depois do chefe
        if prev.get("room") == "tesouro":
            del w["tesouro"]
        if prev.get("room") == "duplo":
            w.pop("duplo", None)
        room = wchoice(rng, w)
    duplo = room == "duplo"
    # ---- andar de caverna (nunca dois seguidos, nunca no 1º andar nem nas salas de 2 andares)
    cave = (not duplo and f >= 2 and not prev.get("cave")
            and rng.random() < (0.38 if room == "boss" else 0.30))

    # ---- bioma
    ci = -1
    if cave:
        ci = rng.randrange(len(CAVE_PALS))
        pi = 100 + ci
        pal = jitter_pal(CAVE_PALS[ci], rng)
    else:
        pi = rng.choice([i for i in range(len(PALS)) if i != prev.get("pal")])
        pal = jitter_pal(PALS[pi], rng)
    liquid = "lava" if (pi == 2 or ci == 2) else ("gelo" if pi == 3 else "agua")

    def cc(c, jit=0.0):
        return (c[0] + 0.5 + rng.uniform(-jit, jit), c[1] + 0.5 + rng.uniform(-jit, jit))

    def far_cells(cells, taken, mind):
        cells = list(cells)
        rng.shuffle(cells)
        best, bd = cells[0], -1.0
        for c in cells:
            d = min((math.hypot(c[0] - t[0], c[1] - t[1]) for t in taken), default=99.0)
            if d >= mind:
                return c
            if d > bd:
                best, bd = c, d
        return best

    # ---- entrada do herói (perto das paredes do fundo)
    if duplo:
        sc = (rng.choice([1, 2]), rng.randint(1, 7))
    elif rng.random() < 0.5:
        sc = (rng.randint(1, 2), rng.randint(1, 7))
    else:
        sc = (rng.randint(1, 7), rng.randint(1, 2))

    # ---- inimigos
    foes, foe_cells = [], []
    allc = [(i, j) for i in range(2, N) for j in range(2, N)]
    if room == "duplo":
        k1 = pick_kind(rng, f, avoid)
        k2 = pick_kind(rng, f, avoid | {k1})
        c1 = far_cells([(i, j) for i in (1, 2) for j in range(1, 9)], [sc], 3.5)
        c2 = far_cells([(i, j) for i in (6, 7, 8) for j in range(1, 9)], [], 0)
        foe_cells = [c1, c2]
        foes = [dict(kind=k1, hpmul=0.75, elite=False), dict(kind=k2, hpmul=0.75, elite=False)]
    elif room == "swarm":
        n = 2 if (f < 8 or rng.random() < 0.6) else 3
        for _ in range(n):
            foes.append(dict(kind=pick_kind(rng, f, set()), hpmul=0.55, elite=False))
    elif room == "elite":
        foes = [dict(kind=pick_kind(rng, f, avoid, bonus=1), hpmul=1.5, elite=True)]
    elif room == "boss":
        if not boss_bag:
            boss_bag.extend(rng.sample(BOSS_KINDS, len(BOSS_KINDS)))
        foes = [dict(kind=boss_bag.pop(), hpmul=1.0, elite=False)]
    elif room == "normal":
        foes = [dict(kind=pick_kind(rng, f, avoid), hpmul=1.0, elite=False)]
    if not duplo:
        for k in range(len(foes)):
            foe_cells.append(far_cells(allc, [sc] + foe_cells, 4.0 if k == 0 else 2.8))

    # ---- escada de descida
    if duplo:
        stc = far_cells([(i, j) for i in (6, 7, 8) for j in range(1, 9)], [foe_cells[1]], 2.6)
    else:
        stc = far_cells([(i, j) for i in range(1, N) for j in range(1, N)], [sc] + foe_cells, 3.2)

    # ---- baú do tesouro (colado no herói)
    chest = None
    if room == "tesouro":
        chest = (min(N - 1, sc[0] + 1), sc[1]) if sc[0] <= sc[1] else (sc[0], min(N - 1, sc[1] + 1))

    # ---- rio (água, gelo ou lava) de borda a borda, com ponte ou vau
    water, bridges, fords, river_axis = set(), set(), set(), "y"
    if not duplo and f >= 2 and rng.random() < (0.55 if cave else 0.28):
        keys = [sc, stc] + foe_cells + ([chest] if chest else [])
        res = gen_river(rng, keys, sc, foe_cells + [stc], liquid)
        if res:
            water, bridges, fords, river_axis = res

    # ---- obstáculos (sempre deixando caminho livre até tudo)
    reserve = set()
    for c in [sc, stc] + foe_cells + ([chest] if chest else []):
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                reserve.add((c[0] + di, c[1] + dj))
    reserve |= bridges | fords
    if cave:
        arche = "caverna"
    elif room == "boss":
        arche = rng.choice(["aberta", "pilares", "ruinas"])
    else:
        arche = rng.choice(["aberta", "pilares", "entulho", "caixas", "caixas", "ruinas", "jardim", "pedras"])
    cand = [(i, j) for i in range(N) for j in range(N)]
    rng.shuffle(cand)
    if arche == "pilares":
        oi, oj = rng.randint(0, 2), rng.randint(0, 2)
        cand = [c for c in cand if (c[0] + oi) % 3 == 0 and (c[1] + oj) % 3 == 0]
        kinds, want = ["pillar"], rng.randint(3, 6)
    elif arche == "entulho":
        kinds, want = ["rock", "rock", "pillar"], rng.randint(4, 7)
    elif arche == "caixas":
        mid = rng.choice(cand)
        cand.sort(key=lambda c: math.hypot(c[0] - mid[0], c[1] - mid[1]) + rng.uniform(0, 1.6))
        kinds, want = ["crate", "barrel"], rng.randint(4, 8)
    elif arche == "caverna":
        kinds, want = ["stalagmite", "stalagmite", "boulder", "boulder", CRYSTAL_KINDS[ci], "mushroom"], rng.randint(5, 9)
    elif arche == "ruinas":
        kinds, want = ["statue", "pillar", "pillar", "rock_pile", "brazier", "boulder"], rng.randint(3, 6)
    elif arche == "jardim":
        kinds, want = ["mushroom", "mushroom", "boulder", "rock_pile"], rng.randint(3, 6)
    elif arche == "pedras":
        mid = rng.choice(cand)
        cand.sort(key=lambda c: math.hypot(c[0] - mid[0], c[1] - mid[1]) + rng.uniform(0, 2.2))
        kinds, want = ["boulder", "boulder", "rock", "rock_pile"], rng.randint(4, 8)
    else:
        kinds, want = ["rock", "crate", "barrel", "pillar", "boulder"], rng.randint(1, 3)
    targets = foe_cells + [stc]
    blocked, decor = set(water), []
    placed = 0
    for c in cand:
        if placed >= want:
            break
        if c in water:
            continue
        if c in reserve or (duplo and 3 <= c[0] <= 5):
            continue
        trial = blocked | {c}
        if all(find_cells(sc, t, duplo, trial) for t in targets):
            blocked = trial
            placed += 1
            kd = rng.choice(kinds)
            ox, oy = BLOCK_OFF[kd]
            decor.append((c[0] + ox, c[1] + oy, kd))

    # ---- decoração solta (fora do caminho)
    pcells, last = set(), sc
    for t in targets:
        pcells.update(find_cells(last, t, duplo, blocked) or [])
        last = t
    free = [c for c in cand if c not in blocked and c not in pcells and c not in reserve
            and not (duplo and 3 <= c[0] <= 5)]
    rng.shuffle(free)
    soft_kinds = (["pebbles", "shrooms", "glowmoss", "glowmoss", "puddle", "bones", "pebbles", "skull"] if cave
                  else ["bones", "bones", "pebbles", "grass", "grass", "skull"])
    bank = [c for c in free if any((c[0] + d[0], c[1] + d[1]) in water for d in DIRS8[:4])]
    for c in bank[:3]:                                  # margem do rio: pedrinhas e capim
        free.remove(c)
        kd = rng.choice(["pebbles", "grass", "pebbles"])
        ox, oy = SOFT_OFF[kd]
        decor.append((c[0] + ox, c[1] + oy, kd))
    for c in free[:rng.randint(2, 5) + (3 if cave else 0)]:
        kd = "chest" if rng.random() < 0.2 else rng.choice(soft_kinds)
        ox, oy = SOFT_OFF[kd]
        decor.append((c[0] + ox, c[1] + oy, kd))
    if chest:
        ox, oy = SOFT_OFF["chest"]
        decor.append((chest[0] + ox, chest[1] + oy, "chest"))

    # ---- bandeiras e tochas nas paredes
    def spread(count, lo, hi, gap, avoid_iv=()):
        out = []
        for _ in range(80):
            if len(out) >= count:
                break
            v = round(rng.uniform(lo, hi) * 2) / 2
            if all(abs(v - o) >= gap for o in out) and not any(a <= v <= b for a, b in avoid_iv):
                out.append(v)
        return out

    banners, torches = [], []
    for ax in ("x", "y"):
        bv = spread(rng.choice([0, 1, 1, 2]), 0.8, 6.8, 2.6)
        banners += [(ax, v) for v in bv]
        torches += [(ax, v) for v in spread(rng.choice([2, 2, 3]), 1.2, 7.6, 2.2, [(b - 0.4, b + 1.4) for b in bv])]

    wall_crystals, tunnel, motes = [], None, []
    if cave:
        banners, torches = [], []
        riv = []
        for (i, j) in water | bridges | fords:
            if i == 0:
                riv.append(("x", j))
            if j == 0:
                riv.append(("y", i))
        tax = rng.choice(("x", "y"))
        tv = spread(1, 1.0, 5.5, 1.0, [(v - 0.6, v + 1.6) for (a, v) in riv if a == tax])
        if tv:
            tunnel = (tax, tv[0])
        for ax in ("x", "y"):
            ivs = [(v - 0.4, v + 1.4) for (a, v) in riv if a == ax]
            if tunnel and tunnel[0] == ax:
                ivs.append((tunnel[1] - 0.6, tunnel[1] + 2.6))
            for v in spread(rng.choice([1, 2, 2, 3]), 0.9, 7.4, 2.0, ivs):
                wall_crystals.append((ax, v, round(rng.uniform(0.7, 1.7), 2), pal[5]))
        for _ in range(16):
            motes.append((rng.uniform(1, N - 1), rng.uniform(1, N - 1), rng.uniform(0.5, 2.2), rng.uniform(0, 6.3)))

    names = {"boss": None, "elite": "INIMIGO ELITE! (recompensa extra)", "tesouro": "SALA DO TESOURO!",
             "duplo": "MASMORRA DE 2 ANDARES!", "swarm": f"EMBOSCADA! {len(foes)} INIMIGOS!", "normal": ""}
    if room == "boss":
        k = foes[0]["kind"]
        banner = "CUIDADO! UM DRAGÃO!" if k == "dragon" else f"CHEFE: {ENEMY_NAMES.get(k, k)}!"
    else:
        banner = names[room]
        if cave:
            banner = {"normal": "CAVERNA ESCURA!", "swarm": "EMBOSCADA NA CAVERNA!", "tesouro": "TESOURO NA CAVERNA!",
                      "elite": "ELITE NA CAVERNA!"}.get(room, banner)
        elif water and room == "normal":
            banner = LIQUIDS[liquid]["nome"] + " CORTA A SALA!"

    sp = cc(sc)
    for fo, c in zip(foes, foe_cells):
        fo["x"], fo["y"] = cc(c, 0.15)
    return dict(room=room, duplo=duplo, pal_idx=pi, pal=pal, spawn=sp, foes=foes, stairs=cc(stc),
                decor=decor, blocked=blocked, torches=torches, banners=banners, banner=banner,
                arche=arche, cave=cave, water=water, bridges=bridges, fords=fords, river_axis=river_axis,
                liquid=liquid, wall_crystals=wall_crystals, tunnel=tunnel, motes=motes)


# ------------------------------------------------------------ VILAREJO (cenário inicial)
# Toda partida começa no VILAREJO PENUMBRA, ao entardecer: casas, poço, feira, árvores, lampiões e uma
# trilha de terra até o poço que desce para a masmorra (o mesmo poço de escada de sempre).
# Sem inimigos: no modo AUTO o herói segue a trilha sozinho; no MANUAL você anda à vontade e entra no poço quando quiser.
VILLAGE_NAME = "VILAREJO PENUMBRA"
# ---- FERREIRO: custos e efeitos dos upgrades (5 níveis cada)
FORGE_MAX = 5
FORGE_COST = ((40, 90, 160, 260, 400),        # arma
              (50, 110, 190, 300, 450))       # armadura
FORGE_TIER = ("Comum", "de Ferro", "de Aço", "de Prata", "de Runas", "de Dragão")
FORGE_WEAPON = {"knight": "Espada", "ranger": "Arco", "mage": "Cajado", "guardian": "Martelo", "rogue": "Adaga"}
FORGE_ARMOR = {"knight": "Armadura", "ranger": "Gibão", "mage": "Manto", "guardian": "Couraça", "rogue": "Veste"}


# ------------------------------------------------------------------ LOOT (raridades)
# Só cai em SALA DO TESOURO ou depois de derrotar um CHEFE. Quanto mais fundo, mais fácil vir item raro.
# ÉPICO só a partir do andar 50 e LENDÁRIO só a partir do andar 75.
RARITY_NAMES = ("Comum", "Incomum", "Raro", "Épico", "Lendário")
RARITY_COLORS = ((200, 200, 204), (110, 220, 120), (90, 160, 255), (190, 100, 255), (255, 170, 40))
EPIC_FLOOR, LEGEND_FLOOR = 50, 75
LOOT_SLOTS = ("arma", "armadura", "anel", "amuleto")
LOOT_LETTER = {"arma": "A", "armadura": "P", "anel": "N", "amuleto": "M"}
LOOT_BASE = {"arma": "Lâmina", "armadura": "Peitoral", "anel": "Anel", "amuleto": "Amuleto"}
LOOT_SUFFIX = ("de Ferro Velho", "de Prata", "de Runas", "do Abismo", "do Dragão Ancião")
# bônus por raridade (comum .. lendário)
LOOT_BONUS = {"arma": (1, 2, 3, 5, 8),              # + dano
              "armadura": (2, 4, 6, 9, 14),          # + % de chance de bloquear golpe
              "anel": (2, 4, 6, 9, 14),              # + % de crítico
              "amuleto": (10, 20, 30, 45, 70)}       # + % de recuperação de fôlego
LOOT_UNIT = {"arma": "dano", "armadura": "% bloqueio", "anel": "% crítico", "amuleto": "% fôlego"}


def loot_weights(floor):
    """Peso de cada raridade no andar dado. Raros ficam mais comuns conforme desce; épico >= 50, lendário >= 75."""
    f = max(1, floor)
    w = [max(10.0, 60.0 - 0.55 * f),                  # comum (diminui)
         28.0 + 0.10 * f,                             # incomum
         8.0 + 0.45 * f,                              # raro (cresce)
         (4.0 + 0.50 * (f - EPIC_FLOOR)) if f >= EPIC_FLOOR else 0.0,
         (1.0 + 0.35 * (f - LEGEND_FLOOR)) if f >= LEGEND_FLOOR else 0.0]
    return w


def roll_rarity(floor, boss=False, rng=random):
    """Sorteia a raridade. Chefe rola duas vezes e fica com a melhor (recompensa maior)."""
    w = loot_weights(floor)
    picks = [rng.choices(range(5), weights=w)[0] for _ in range(2 if boss else 1)]
    return max(picks)


def make_loot(floor, boss=False, rng=random):
    r = roll_rarity(floor, boss, rng)
    slot = rng.choice(LOOT_SLOTS)
    return {"slot": slot, "rarity": r, "bonus": LOOT_BONUS[slot][r],
            "name": f"{LOOT_BASE[slot]} {LOOT_SUFFIX[r]}"}


BAG_MAX = 24                                          # tamanho da mochila (6 x 4)
LOOT_LABEL = {"arma": "ARMA", "armadura": "ARMADURA", "anel": "ANEL", "amuleto": "AMULETO"}


def clean_bag(v):
    """Lê a mochila gravada no save (descarta o que estiver inválido; o bônus é recalculado pela tabela)."""
    out = []
    if isinstance(v, list):
        for it in v[:BAG_MAX]:
            if (isinstance(it, dict) and it.get("slot") in LOOT_SLOTS and isinstance(it.get("rarity"), int)
                    and not isinstance(it.get("rarity"), bool) and 0 <= it["rarity"] <= 4 and isinstance(it.get("name"), str)):
                out.append({"slot": it["slot"], "rarity": it["rarity"], "bonus": LOOT_BONUS[it["slot"]][it["rarity"]],
                            "name": it["name"][:40]})
    return out


# ------------------------------------------------------------------ MERCADO
MARKET_PRICE = (30, 70, 150)        # preço de compra: comum, incomum, raro (vender rende bem menos que isso)
MARKET_SLOTS = 12


def make_market_stock(rng):
    """Mercadorias da partida (as mesmas até você morrer): 12 peças, 3 de cada tipo de equipamento."""
    out = []
    for i in range(MARKET_SLOTS):
        slot = LOOT_SLOTS[i % len(LOOT_SLOTS)]
        r = rng.choices(range(3), weights=(50, 34, 16))[0]
        out.append({"slot": slot, "rarity": r, "bonus": LOOT_BONUS[slot][r], "price": MARKET_PRICE[r], "sold": False,
                    "name": f"{LOOT_BASE[slot]} {LOOT_SUFFIX[r]}"})
    return out


def loot_value(it, floor, car=0):
    """Ouro que o item rende quando vendido."""
    return int(round((4 * (it["rarity"] + 1) + floor // 2) * (1.0 + 0.04 * car)))


def forge_hearts(lv):
    """Corações extras da armadura: nos níveis 2 e 4."""
    return (1 if lv >= 2 else 0) + (1 if lv >= 4 else 0)


def forge_stats(kind, lv):
    if kind == 0:
        return f"Dano +{lv}   Crítico +{2 * lv}%"
    return f"Bloqueio {4 * lv}%   Vida +{forge_hearts(lv)}"


VILLAGE_HERO_K = 0.72                    # no vilarejo o herói é desenhado menor, para ficar proporcional às casas altas
VILLAGE_N, VILLAGE_OY = 11, 140          # vila 11x11 (a masmorra é 9x9); OY sobe para a vila toda caber acima do painel
DEF_N, DEF_OY = N, OY                     # valores normais, restaurados ao entrar na masmorra
VILLAGE_PAL = ((104, 142, 78), (92, 128, 68), (122, 118, 126), (98, 94, 104), (14, 12, 40), (170, 58, 52))
VILLAGE_BLOCK = ("house_r", "house_b", "house_t", "tree", "pine", "well", "stall", "hay", "lamppost",
                 "signpost", "villager_0", "villager_1", "villager_2", "fence_x", "fence_y",
                 "smithy", "smith_npc", "anvil", "merchant_npc")
VILLAGE_KINDS = VILLAGE_BLOCK + ("flowers",)
EXTRA_DECOR |= set(VILLAGE_KINDS)
SOLID_KINDS = SOLID_KINDS + VILLAGE_BLOCK
NO_SHADOW |= set(VILLAGE_KINDS)                   # as sombras do vilarejo já vêm desenhadas no cenário em cache
GLOW_KINDS["lamppost"] = (255, 190, 96)
GLOW_R["lamppost"] = 90
GLOW_KINDS["anvil"] = (255, 140, 60)           # a peça em brasa ilumina em volta
GLOW_R["anvil"] = 85

VW_WOOD, VW_WOOD_D, VW_STONE = (126, 88, 54), (88, 60, 38), (116, 112, 122)
VW_ROOFS = {"house_r": (158, 56, 50), "house_b": (62, 92, 138), "house_t": (202, 166, 90)}
VW_FOLK = (((84, 130, 178), (74, 62, 54), (96, 62, 38)),        # camponês: túnica, calça, cabelo
           ((164, 72, 122), (112, 62, 92), (214, 176, 84)),     # moça de vestido
           ((200, 154, 72), (60, 54, 64), (70, 64, 66)))        # velho andarilho


def _vw_house(kind):
    """Casa de 1,8 x 1,7: paredes de gesso com vigas, porta e janelas acesas, telhado em degraus e chaminé.
    Camadas empilhadas e concêntricas, para o algoritmo do pintor desenhar na ordem certa."""
    roof = VW_ROOFS[kind]
    wall = (214, 198, 164)
    r, rl, rd = roof, mix(roof, 0.14), shade(roof, 0.78)
    glass = (255, 208, 112)
    P = [(0.0, 0.0, 0.0, 1.8, 1.7, 0.12, VW_STONE),                           # alicerce
         (0.05, 0.05, 0.12, 1.7, 1.6, 1.0, wall)]                              # paredes
    for (px_, py_) in ((0.0, 0.0), (1.7, 0.0), (0.0, 1.6), (1.7, 1.6)):        # vigas de canto
        P.append((px_, py_, 0.12, 0.1, 0.1, 1.04, VW_WOOD))
    P += [(0.05, 1.65, 0.90, 1.7, 0.05, 0.07, VW_WOOD),                        # viga da face da frente
          (1.75, 0.05, 0.90, 0.05, 1.6, 0.07, VW_WOOD),                        # viga da face da direita
          (0.60, 1.65, 0.12, 0.46, 0.06, 0.74, VW_WOOD_D),                     # moldura da porta
          (0.66, 1.67, 0.12, 0.34, 0.06, 0.66, (92, 58, 36)),                  # porta
          (0.90, 1.72, 0.40, 0.05, 0.03, 0.05, (240, 205, 80)),                # maçaneta
          (0.56, 1.66, 0.0, 0.54, 0.16, 0.10, VW_STONE),                       # degrau
          (0.17, 1.65, 0.50, 0.32, 0.05, 0.34, VW_WOOD), (0.20, 1.69, 0.53, 0.26, 0.03, 0.28, glass),     # janela da frente
          (1.75, 0.30, 0.50, 0.05, 0.34, 0.34, VW_WOOD), (1.79, 0.33, 0.53, 0.03, 0.28, 0.28, glass),     # janelas da direita
          (1.75, 1.00, 0.50, 0.05, 0.34, 0.34, VW_WOOD), (1.79, 1.03, 0.53, 0.03, 0.28, 0.28, glass),
          (-0.12, -0.12, 1.12, 2.04, 1.94, 0.14, rd),                          # telhado (beiral)
          (0.04, 0.04, 1.26, 1.72, 1.62, 0.14, r),
          (0.20, 0.20, 1.40, 1.40, 1.30, 0.14, rl),
          (0.36, 0.36, 1.54, 1.08, 0.98, 0.14, r),
          (0.52, 0.52, 1.68, 0.76, 0.66, 0.14, rl),
          (0.68, 0.68, 1.82, 0.44, 0.34, 0.12, r),
          (1.30, 0.30, 1.20, 0.24, 0.24, 0.62, VW_STONE),                      # chaminé
          (1.28, 0.28, 1.82, 0.28, 0.28, 0.06, shade(VW_STONE, 0.7))]
    return P


def _vw_tree(pine):
    trunk = (104, 70, 44)
    if pine:
        P = [(0.34, 0.34, 0.0, 0.20, 0.20, 0.5, trunk)]
        cols = ((38, 92, 60), (46, 106, 66), (54, 118, 72), (62, 130, 78), (74, 144, 86))
        for k, c in enumerate(cols):
            w = 0.90 - 0.17 * k
            P.append(((0.9 - w) / 2, (0.9 - w) / 2, 0.40 + 0.30 * k, w, w, 0.30, c))
        P.append((0.41, 0.41, 1.90, 0.08, 0.08, 0.22, (74, 144, 86)))
        return P
    return [(0.30, 0.30, 0.0, 0.24, 0.24, 0.9, trunk),
            (0.0, 0.0, 0.80, 0.84, 0.84, 0.30, (46, 98, 54)),
            (0.08, 0.08, 1.10, 0.68, 0.68, 0.30, (62, 122, 64)),
            (0.18, 0.18, 1.40, 0.48, 0.48, 0.26, (88, 150, 78)),
            (0.28, 0.28, 1.66, 0.28, 0.28, 0.16, (110, 168, 90))]


def _vw_well():
    st, stl, roof = (118, 114, 124), (140, 136, 148), (150, 56, 50)
    return [(0.0, 0.0, 0.0, 0.9, 0.14, 0.46, st),                      # anel de pedra (4 peças; os cantos têm dono)
            (0.0, 0.14, 0.0, 0.14, 0.62, 0.46, st),
            (0.14, 0.14, 0.0, 0.62, 0.62, 0.30, (36, 82, 132)),        # água
            (0.0, 0.76, 0.0, 0.14, 0.14, 0.46, st),
            (0.14, 0.76, 0.0, 0.76, 0.14, 0.46, st),
            (0.76, 0.14, 0.0, 0.14, 0.62, 0.46, st),
            (0.0, 0.76, 0.46, 0.14, 0.14, 0.06, stl),
            (0.02, 0.78, 0.52, 0.10, 0.10, 0.80, VW_WOOD_D),           # poste da frente-esquerda
            (0.78, 0.02, 0.46, 0.10, 0.10, 0.86, VW_WOOD_D),           # poste de trás-direita
            (0.43, 0.43, 0.80, 0.03, 0.03, 0.60, (190, 170, 120)),     # corda
            (0.37, 0.37, 0.52, 0.16, 0.16, 0.14, VW_WOOD),             # balde
            (-0.10, 0.18, 1.40, 1.10, 0.54, 0.08, shade(roof, 0.8)),   # telhadinho
            (0.0, 0.26, 1.48, 0.90, 0.38, 0.08, roof),
            (0.15, 0.32, 1.56, 0.60, 0.26, 0.07, mix(roof, 0.15))]


def _vw_stall():
    P = [(0.0, 0.2, 0.0, 1.2, 0.5, 0.5, VW_WOOD), (-0.02, 0.18, 0.5, 1.24, 0.54, 0.06, VW_WOOD_D),
         (0.12, 0.32, 0.56, 0.22, 0.2, 0.12, (196, 48, 44)),           # maçãs
         (0.50, 0.34, 0.56, 0.22, 0.2, 0.10, (226, 170, 60)),          # queijo
         (0.86, 0.30, 0.56, 0.24, 0.22, 0.12, (150, 200, 90)),         # repolhos
         (0.0, 0.0, 0.0, 0.1, 0.1, 1.35, VW_WOOD_D), (1.1, 0.0, 0.0, 0.1, 0.1, 1.35, VW_WOOD_D)]
    for k in range(6):                                                  # toldo listrado
        c = (196, 56, 50) if k % 2 == 0 else (236, 226, 196)
        P.append((k * 0.2, -0.1, 1.35, 0.2, 1.1, 0.08, c))
        P.append((k * 0.2, 0.96, 1.26, 0.2, 0.04, 0.09, c))
    return P


def _vw_smithy(t):
    """Forja do ferreiro: pedra escura, telhado de ardósia, chaminé com fumaça e a fornalha acesa na frente (à direita)."""
    wall, wallD = (118, 106, 104), (92, 82, 84)
    rd, r, rl = (56, 60, 78), (72, 76, 98), (90, 94, 118)
    fire = (255, 120, 36)
    fl = [0.13 + 0.09 * math.sin(t * 9.0 + i * 2.1) for i in range(3)]
    P = [(0.0, 0.0, 0.0, 2.1, 1.8, 0.12, VW_STONE),                              # alicerce
         (0.05, 0.05, 0.12, 2.0, 1.7, 1.0, wall)]                                 # paredes
    for (px_, py_) in ((0.0, 0.0), (2.0, 0.0), (0.0, 1.7), (2.0, 1.7)):          # vigas de canto
        P.append((px_, py_, 0.12, 0.1, 0.1, 1.04, VW_WOOD_D))
    P += [(0.05, 1.75, 0.90, 2.0, 0.06, 0.07, VW_WOOD_D),                        # viga da frente
          (2.05, 0.05, 0.90, 0.06, 1.7, 0.07, VW_WOOD_D),                        # viga da direita
          (0.18, 1.65, 0.12, 0.52, 0.06, 0.76, VW_WOOD_D),                       # moldura da porta (esquerda)
          (0.24, 1.67, 0.12, 0.40, 0.06, 0.68, (84, 54, 34)),                    # porta
          (0.54, 1.72, 0.40, 0.04, 0.03, 0.05, (240, 205, 80)),
          (0.12, 1.66, 0.0, 0.64, 0.16, 0.10, VW_STONE),                         # degrau
          (1.12, 1.75, 0.12, 0.08, 0.06, 0.78, VW_WOOD_D),                       # moldura da fornalha
          (1.92, 1.75, 0.12, 0.08, 0.06, 0.78, VW_WOOD_D),
          (1.12, 1.75, 0.86, 0.88, 0.06, 0.08, VW_WOOD_D),
          (1.20, 1.75, 0.12, 0.72, 0.04, 0.74, (26, 20, 22)),                    # boca escura
          (1.24, 1.78, 0.40, 0.64, 0.02, 0.38, (170, 62, 28)),                   # brilho do fogo
          (1.20, 1.76, 0.12, 0.72, 0.16, 0.28, (100, 96, 106)),                  # bancada de pedra
          (1.26, 1.80, 0.40, 0.60, 0.10, 0.05, fire)]                            # brasas
    for i in range(3):                                                           # chamas tremulando
        P.append((1.32 + 0.20 * i, 1.82, 0.45, 0.12, 0.08, fl[i] + 0.06, (255, 190, 70)))
    P += [(2.05, 0.20, 0.50, 0.05, 0.34, 0.34, VW_WOOD), (2.09, 0.23, 0.53, 0.03, 0.28, 0.28, (255, 150, 60)),   # janela
          (2.05, 0.80, 0.42, 0.05, 0.56, 0.44, VW_WOOD),                         # placa com bigorna
          (2.09, 0.98, 0.72, 0.03, 0.30, 0.07, DARK), (2.09, 1.08, 0.60, 0.03, 0.10, 0.12, DARK),
          (2.09, 1.02, 0.52, 0.03, 0.22, 0.08, DARK),
          (-0.12, -0.12, 1.12, 2.34, 2.04, 0.14, rd),                            # telhado em degraus
          (0.04, 0.04, 1.26, 2.02, 1.72, 0.14, r),
          (0.20, 0.20, 1.40, 1.70, 1.40, 0.14, rl),
          (0.36, 0.36, 1.54, 1.38, 1.08, 0.14, r),
          (0.52, 0.52, 1.68, 1.06, 0.76, 0.14, rl),
          (0.68, 0.68, 1.82, 0.74, 0.44, 0.12, r),
          (1.50, 0.45, 1.15, 0.34, 0.34, 1.15, VW_STONE),                        # chaminé
          (1.46, 0.41, 2.30, 0.42, 0.42, 0.07, (70, 66, 76))]
    for i in range(3):                                                           # fumaça subindo
        ph = (t * 0.45 + i / 3.0) % 1.0
        s = 0.12 + 0.16 * ph
        P.append((1.67 - s / 2 + 0.10 * math.sin(t * 1.3 + i * 2.0) * ph, 0.62 - s / 2 + 0.05 * ph, 2.42 + ph * 0.9,
                  s, s, s, mix((176, 174, 184), ph * 0.65, (96, 90, 118))))
    return P


def _vw_anvil():
    st, stl = (74, 74, 88), (112, 114, 130)
    return [(0.10, 0.05, 0.0, 0.36, 0.22, 0.12, st), (0.17, 0.09, 0.12, 0.22, 0.14, 0.14, (88, 88, 104)),
            (0.04, 0.05, 0.26, 0.50, 0.22, 0.12, stl), (0.54, 0.09, 0.28, 0.12, 0.12, 0.07, stl),
            (0.18, 0.12, 0.38, 0.14, 0.08, 0.03, (255, 140, 50))]                # peça em brasa


# ---- NPCs do vilarejo no ESTILO DOS HERÓIS: mesmo construtor (_P), mesma cabeça grande, olhos/bochechas, braços com
#      manga + mão, respiração e piscada; desenhados como os heróis (sombreamento macio, ordem exata das peças).
#      Pele com tons naturais (nada de pálido).
NPC_KINDS = ("villager_0", "villager_1", "villager_2", "smith_npc", "merchant_npc")
NPC_K = {"villager_0": 1.2, "villager_1": 1.15, "villager_2": 1.15, "smith_npc": 1.3, "merchant_npc": 1.2}        # escala visual (herói na vila ~0,97)
NPC_CENTER = {"villager_0": (0.36, 0.34), "villager_1": (0.36, 0.34), "villager_2": (0.36, 0.34),
              "smith_npc": (0.34, 0.30), "merchant_npc": (0.36, 0.34)}                                                      # centro do corpo em relação ao ponto da decoração
NPC_SKIN = {"villager_0": (232, 184, 142), "villager_1": (192, 134, 96), "villager_2": (150, 104, 72),
            "smith_npc": (204, 150, 108), "merchant_npc": (214, 166, 120)}


def _npc_head(P, g, hz, skin, hair, eye=(44, 34, 32), mouth=(168, 78, 76), long_hair=False, cap=True, mouth_on=True):
    """Cabeça de herói: cubo grande, cabelo no topo/lados, franja e rosto com olhos, bochechas e boca."""
    sx, sy = g["sway"]
    hx, hy = sx * 1.4, sy * 1.4
    P.b(hx, hy, hz, 0.46, 0.46, 0.31, skin)
    if cap:
        P.b(hx, hy, hz + 0.31, 0.50, 0.50, 0.11, hair)
        P.b(hx + 0.235, hy + 0.13, hz + 0.285, 0.026, 0.12, 0.05, hair)        # franja
        P.b(hx + 0.13, hy + 0.235, hz + 0.285, 0.12, 0.026, 0.05, hair)
    if long_hair:
        P.b(hx + 0.235, hy - 0.14, hz - 0.06, 0.026, 0.12, 0.37, hair)
        P.b(hx - 0.14, hy + 0.235, hz - 0.06, 0.12, 0.026, 0.37, hair)
    else:
        P.b(hx + 0.235, hy - 0.16, hz + 0.02, 0.026, 0.07, 0.26, hair)
        P.b(hx - 0.16, hy + 0.235, hz + 0.02, 0.07, 0.026, 0.26, hair)
    _face3(P, hx, hy, 0.23, hz, g, eye=eye, cheek=mix(skin, 0.30, (236, 110, 100)), mouth=mouth,
           with_cheeks=True, with_mouth=mouth_on)
    return hx, hy


def _npc_beard(P, hx, hy, hz, col, long=0.0):
    P.b(hx + 0.235, hy, hz - 0.01, 0.026, 0.46, 0.13, col)
    P.b(hx, hy + 0.235, hz - 0.01, 0.46, 0.026, 0.13, col)
    P.b(hx + 0.08, hy + 0.08, hz - 0.08 - long, 0.30, 0.30, 0.10 + long, col)


def _npc_villager_0(t, moving=False, key="npc_v0"):
    """Camponês: túnica azul, cinto, chapéu de palha e cesta de maçãs."""
    g = _gait(t, moving, None, key)
    b, hb = g["bob"], g["bob"] + g["head"]
    skin, tunic, pants, hair = NPC_SKIN["villager_0"], (84, 130, 178), (74, 62, 54), (96, 62, 38)
    P = _P()
    _legs(P, g, (62, 46, 36), pants)
    P.b(0, 0, 0.12 + b, 0.34, 0.32, 0.30, tunic)
    P.wrap(0, 0, 0.34, 0.32, 0.17 + b, 0.04, (58, 40, 30))
    P.b(0.18, 0.02, 0.172 + b, 0.012, 0.05, 0.035, (232, 200, 90))
    P.b(0.02, 0.17, 0.172 + b, 0.05, 0.012, 0.035, (232, 200, 90))
    P.wrap(0, 0, 0.34, 0.32, 0.38 + b, 0.04, (232, 222, 200))                  # gola da camisa
    hB = _arm(P, g, -1, 0.215, tunic, skin)
    _arm(P, g, 1, 0.215, tunic, skin)
    P.b(hB[0] - 0.01, hB[1] + 0.07, hB[2] - 0.02, 0.15, 0.13, 0.09, (150, 104, 60))   # cesta com maçãs
    P.b(hB[0] - 0.04, hB[1] + 0.07, hB[2] + 0.07, 0.05, 0.05, 0.05, (214, 52, 52))
    P.b(hB[0] + 0.02, hB[1] + 0.08, hB[2] + 0.07, 0.05, 0.05, 0.05, (232, 96, 60))
    hz = 0.45 + hb
    hx, hy = _npc_head(P, g, hz, skin, hair, cap=False)
    P.b(hx, hy, hz + 0.30, 0.64, 0.64, 0.035, (214, 180, 96))                  # chapéu de palha
    P.b(hx, hy, hz + 0.335, 0.44, 0.44, 0.11, (228, 194, 108))
    P.wrap(hx, hy, 0.44, 0.44, hz + 0.335, 0.03, (150, 70, 50))
    return P


def _npc_villager_1(t, moving=False, key="npc_v1"):
    """Moça de vestido: vestido rosa com avental, cabelo loiro comprido, laço vermelho e buquê de flores."""
    g = _gait(t, moving, None, key)
    fx, fy = g["f"]
    b, hb = g["bob"], g["bob"] + g["head"]
    skin, dress, dressD, hair = NPC_SKIN["villager_1"], (164, 72, 122), (118, 50, 92), (214, 176, 84)
    white, trim = (240, 236, 226), (240, 214, 140)
    P = _P()
    for side, o in ((1, g["lA"]), (-1, g["lB"])):                               # sapatos sob a barra do vestido
        P.b(0.10 * side + o[0] + fx * 0.04, -0.10 * side + o[1] + fy * 0.04, o[2] * 0.8, 0.13, 0.13, 0.075, (96, 64, 52))
    P.b(0, 0, 0.075, 0.44, 0.42, 0.17, dressD)
    P.wrap(0, 0, 0.44, 0.42, 0.075, 0.035, trim)
    P.b(0, 0, 0.24 + b, 0.34, 0.32, 0.20, dress)
    P.b(0.222, 0.0, 0.10, 0.014, 0.22, 0.20, white)                             # avental
    P.b(0.0, 0.212, 0.10, 0.22, 0.014, 0.20, white)
    P.wrap(0, 0, 0.34, 0.32, 0.40 + b, 0.04, white)
    hB = _arm(P, g, -1, 0.215, dress, skin, w=0.105)
    _arm(P, g, 1, 0.215, dress, skin, w=0.105)
    for i, col in enumerate(((240, 120, 170), (248, 214, 90), (240, 240, 236))):   # buquê
        P.b(hB[0] - 0.03 + 0.04 * i, hB[1] + 0.07, hB[2] + 0.03, 0.02, 0.02, 0.12, (70, 150, 70))
        P.b(hB[0] - 0.03 + 0.04 * i, hB[1] + 0.07, hB[2] + 0.14, 0.06, 0.06, 0.05, col)
    hz = 0.45 + hb
    hx, hy = _npc_head(P, g, hz, skin, hair, eye=(60, 40, 40), mouth=(190, 80, 90), long_hair=True)
    P.b(hx + 0.14, hy + 0.02, hz + 0.43, 0.09, 0.09, 0.07, (214, 60, 84))      # laço
    P.b(hx + 0.02, hy + 0.14, hz + 0.43, 0.09, 0.09, 0.07, (214, 60, 84))
    P.b(hx + 0.08, hy + 0.08, hz + 0.435, 0.05, 0.05, 0.05, (160, 30, 54))
    return P


def _npc_villager_2(t, moving=False, key="npc_v2"):
    """Velho andarilho: túnica ocre, capa curta, chapéu de couro, barba branca comprida e cajado."""
    g = _gait(t, moving, None, key)
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    skin, robe, pants = NPC_SKIN["villager_2"], (200, 154, 72), (60, 54, 64)
    grey, wood, cape = (186, 184, 188), (130, 92, 58), (96, 70, 52)
    P = _P()
    _legs(P, g, (54, 42, 36), pants)
    P.b(sx, sy, 0.12 + b, 0.34, 0.32, 0.30, robe)
    P.wrap(sx, sy, 0.34, 0.32, 0.17 + b, 0.04, (110, 78, 46))
    for i in range(4):                                                            # capa curta nas costas
        P.b(sx - 0.14 - 0.02 * i, sy - 0.14 - 0.02 * i, 0.36 + b - i * 0.065, 0.26, 0.26, 0.07, shade(cape, 1.0 - i * 0.07))
    _arm(P, g, -1, 0.215, robe, skin)
    hA = _arm(P, g, 1, 0.215, robe, skin)
    for i in range(7):                                                            # cajado
        P.b(hA[0], hA[1] + 0.04, hA[2] - 0.18 + i * 0.13, 0.045, 0.045, 0.14, wood)
    P.b(hA[0], hA[1] + 0.04, hA[2] + 0.72, 0.09, 0.09, 0.09, (110, 78, 46))
    hz = 0.45 + hb
    hx, hy = _npc_head(P, g, hz, skin, grey, eye=(40, 30, 28), cap=False, mouth_on=False)
    _npc_beard(P, hx, hy, hz, (226, 224, 220), long=0.05)
    P.b(hx + 0.235, hy + 0.04, hz + 0.255, 0.03, 0.30, 0.03, (226, 224, 220))     # sobrancelhas brancas
    P.b(hx + 0.04, hy + 0.235, hz + 0.255, 0.30, 0.03, 0.03, (226, 224, 220))
    P.b(hx, hy, hz + 0.30, 0.62, 0.62, 0.035, (96, 72, 52))                       # chapéu de couro
    P.b(hx, hy, hz + 0.335, 0.42, 0.42, 0.12, (110, 84, 60))
    P.wrap(hx, hy, 0.42, 0.42, hz + 0.335, 0.03, (170, 60, 50))
    return P


def _npc_smith(t, moving=False, key="npc_smith"):
    """O ferreiro: careca de bandana vermelha, barba, avental de couro; martela a peça na bigorna (à direita dele)."""
    g = _gait(t, False, None, "npc_smith")
    b, hb = g["bob"], g["bob"] + g["head"]
    sx, sy = g["sway"]
    skin, beard = NPC_SKIN["smith_npc"], (84, 52, 34)
    tunic, apron, pants, boot = (150, 66, 50), (74, 54, 40), (58, 52, 62), (48, 38, 34)
    steel, wood, band = (156, 158, 172), (110, 76, 46), (190, 50, 44)
    u = (t * 1.4) % 1.0
    L = math.sin(math.pi * u / 0.6) if u < 0.6 else 0.0                          # 0 = martelo na bigorna, 1 = no alto
    P = _P()
    _legs(P, g, boot, pants, w=0.15)
    P.b(sx, sy, 0.12 + b, 0.40, 0.36, 0.30, tunic)
    P.wrap(sx, sy, 0.40, 0.36, 0.17 + b, 0.04, (58, 42, 32))
    P.b(sx + 0.208, sy, 0.10 + b, 0.016, 0.17, 0.24, apron)                       # avental de couro
    P.b(sx, sy + 0.188, 0.10 + b, 0.19, 0.016, 0.24, apron)
    for side in (1, -1):                                                           # ombreiras de aço
        P.b(sx + side * 0.225, sy - side * 0.225, 0.37 + b, 0.14, 0.14, 0.06, steel)
    hB = _arm(P, g, -1, 0.225, tunic, skin, w=0.11)
    P.b(hB[0], hB[1] + 0.09, hB[2] - 0.01, 0.03, 0.15, 0.03, steel)                # pinça na mão esquerda

    def seg(a, c, n, w, col):
        for i in range(n + 1):
            k = i / float(n)
            P.b(a[0] + (c[0] - a[0]) * k, a[1] + (c[1] - a[1]) * k, a[2] + (c[2] - a[2]) * k - w / 2, w, w, w, col)

    shoulder = (0.225, -0.225, 0.34 + b)
    hand = (0.33, -0.03, 0.46 + 0.10 * L)
    head = (0.52 - 0.06 * L, -0.03, 0.31 + 0.42 * L)
    seg(shoulder, hand, 3, 0.10, tunic)                                           # braço do martelo
    seg(hand, (head[0], head[1], head[2] + 0.07), 4, 0.045, wood)                 # cabo
    P.b(head[0], head[1], head[2], 0.15, 0.12, 0.12, steel)                       # cabeça do martelo
    P.b(hand[0], hand[1], hand[2] - 0.045, 0.10, 0.10, 0.09, skin)                # mão
    if 0.6 <= u < 0.78:                                                            # faíscas no impacto
        for i in range(4):
            a = t * 40 + i * 1.7
            P.b(0.54 + 0.10 * math.sin(a), -0.03 + 0.08 * math.cos(a * 1.3), 0.32 + 0.12 * abs(math.sin(a * 0.9)),
                0.035, 0.035, 0.035, (255, 206, 90))
    hz = 0.45 + hb
    hx, hy = sx * 1.4, sy * 1.4
    P.b(hx, hy, hz, 0.46, 0.46, 0.31, skin)
    P.b(hx, hy, hz + 0.31, 0.48, 0.48, 0.03, mix(skin, 0.14))                      # careca
    P.wrap(hx, hy, 0.46, 0.46, hz + 0.265, 0.05, band)                             # bandana
    _npc_beard(P, hx, hy, hz, beard, long=0.04)
    _face3(P, hx, hy, 0.23, hz, g, eye=(34, 26, 24))
    return P


def _npc_merchant(t, moving=False, key="npc_merchant"):
    """Mercador: chapéu roxo de aba larga com pena, bigode, colete de couro, mochila enorme e uma moeda de ouro
    que ele joga para o alto."""
    g = _gait(t, moving, None, key)
    b, hb = g["bob"], g["bob"] + g["head"]
    skin = NPC_SKIN["merchant_npc"]
    tunic, vest, pants, boot = (58, 108, 86), (132, 84, 48), (60, 50, 56), (52, 40, 34)
    gold, hat, hatD, hair = (240, 204, 80), (110, 56, 92), (78, 38, 66), (92, 58, 36)
    P = _P()
    _legs(P, g, boot, pants)
    P.b(-0.24, -0.22, 0.12 + b, 0.20, 0.20, 0.34, (120, 84, 52))                  # mochila grande nas costas
    P.b(-0.24, -0.22, 0.46 + b, 0.26, 0.16, 0.10, (162, 70, 62))                  # esteira enrolada
    P.b(-0.24, -0.22, 0.20 + b, 0.22, 0.22, 0.03, gold)
    P.b(0, 0, 0.12 + b, 0.34, 0.32, 0.30, tunic)
    P.b(0.176, 0.0, 0.13 + b, 0.014, 0.24, 0.26, vest)                            # colete
    P.b(0.0, 0.166, 0.13 + b, 0.24, 0.014, 0.26, vest)
    P.wrap(0, 0, 0.34, 0.32, 0.17 + b, 0.04, (58, 40, 30))
    P.b(0.19, 0.02, 0.172 + b, 0.012, 0.06, 0.04, gold)                           # fivela
    P.b(0.02, 0.18, 0.172 + b, 0.06, 0.012, 0.04, gold)
    P.b(0.19, -0.13, 0.12 + b, 0.07, 0.10, 0.11, (110, 76, 46))                   # bolsa de moedas no cinto
    P.b(0.19, -0.13, 0.23 + b, 0.05, 0.07, 0.025, gold)
    P.wrap(0, 0, 0.36, 0.34, 0.38 + b, 0.05, (206, 154, 60))                      # lenço
    hB = _arm(P, g, -1, 0.215, tunic, skin)
    hA = _arm(P, g, 1, 0.215, tunic, skin, extra=(0.0, 0.0, 0.07 + 0.03 * math.sin(t * 3.0)))
    cz = 0.10 + 0.20 * abs(math.sin(t * 3.0))                                      # moeda jogada para o alto
    P.b(hA[0], hA[1], hA[2] + cz, 0.075, 0.075, 0.03, gold)
    P.b(hA[0], hA[1], hA[2] + cz + 0.03, 0.03, 0.03, 0.03, (255, 244, 190))
    hz = 0.45 + hb
    hx, hy = _npc_head(P, g, hz, skin, hair, eye=(40, 30, 28), cap=False)
    P.b(hx + 0.236, hy + 0.10, hz + 0.075, 0.026, 0.22, 0.045, hair)               # bigode
    P.b(hx + 0.10, hy + 0.236, hz + 0.075, 0.22, 0.026, 0.045, hair)
    P.b(hx, hy, hz + 0.29, 0.68, 0.68, 0.035, hat)                                 # chapéu de aba larga
    P.b(hx, hy, hz + 0.325, 0.44, 0.44, 0.15, hat)
    P.wrap(hx, hy, 0.44, 0.44, hz + 0.325, 0.035, gold)
    P.b(hx, hy, hz + 0.475, 0.36, 0.36, 0.045, hatD)
    P.b(hx + 0.20, hy + 0.14, hz + 0.37, 0.04, 0.04, 0.20, (214, 60, 70))          # pena
    P.b(hx + 0.22, hy + 0.14, hz + 0.53, 0.04, 0.04, 0.07, (240, 110, 110))
    return P


_NPC_BUILDERS = {"villager_0": _npc_villager_0, "villager_1": _npc_villager_1,
                 "villager_2": _npc_villager_2, "smith_npc": _npc_smith, "merchant_npc": _npc_merchant}


def npc_parts(kind, t, local=False, moving=False, key=None):
    """Peças (x, y, z, w, d, h, cor) do NPC já na escala. local=True: relativas ao ponto da decoração (colisão e sombra);
    local=False: centradas no corpo (para desenhar girado, como o herói)."""
    k = NPC_K[kind]
    cx, cy = NPC_CENTER[kind] if local else (0.0, 0.0)
    fn = _NPC_BUILDERS[kind]
    P = fn(t, moving, key) if key else fn(t)
    return [(a * k + cx, b * k + cy, c * k, d * k, e * k, f * k, col) for (a, b, c, d, e, f, col) in P]


# ---- aldeões que ANDAM pelo vilarejo (o mercador e o ferreiro ficam no posto)
WANDER_KINDS = ("villager_0", "villager_1", "villager_2")
NPC_SPEED, NPC_RAD = 0.62, 0.26


def npc_new(i, kind, x, y):
    cx, cy = NPC_CENTER[kind]
    wx, wy = x + cx, y + cy
    return {"id": i, "kind": kind, "x": wx, "y": wy, "home": (wx, wy), "wp": [], "wait": 0.6 + 0.9 * (i % 5),
            "moving": False, "ang": 0.0, "halt": 0.0, "stuck": 0.0}


def npc_step(n, dt, hero, others, blocked, solids, rng, size):
    """IA do aldeão: espera um pouco, escolhe um ponto livre perto de casa, anda até lá sem atravessar obstáculos,
    o herói ou outros aldeões, e para de novo. Perto do herói ele para e vira o corpo para ele."""
    hx, hy = hero
    n["moving"] = False
    if n["wp"]:
        tx, ty = n["wp"][0]
        dx, dy = tx - n["x"], ty - n["y"]
        d = math.hypot(dx, dy)
        if d < 0.09:
            n["wp"].pop(0)
            if not n["wp"]:
                n["wait"] = rng.uniform(2.0, 6.0)
            return
        ux, uy = dx / d, dy / d
        for ox, oy in [(hx, hy)] + list(others):
            rx, ry = ox - n["x"], oy - n["y"]
            ahead, side = rx * ux + ry * uy, abs(-rx * uy + ry * ux)
            if 0.0 < ahead < 0.9 and side < 0.5:              # alguém na frente: espera; se demorar, desiste
                n["halt"] += dt
                n["face"] = math.atan2(ry, rx)
                if n["halt"] > 2.5:
                    n["wp"], n["wait"], n["halt"] = [], rng.uniform(0.8, 2.0), 0.0
                return
        n["halt"] = 0.0
        step = min(d, NPC_SPEED * dt)
        nx, ny = push_out(n["x"] + ux * step, n["y"] + uy * step, NPC_RAD, solids)
        moved = math.hypot(nx - n["x"], ny - n["y"])
        n["x"], n["y"] = nx, ny
        n["moving"] = True
        n["face"] = math.atan2(uy, ux)
        n["stuck"] = n["stuck"] + dt if moved < step * 0.3 else 0.0
        if n["stuck"] > 0.8:                                    # encalhou numa quina: escolhe outro destino
            n["wp"], n["wait"], n["stuck"] = [], rng.uniform(0.5, 1.5), 0.0
        return
    n["wait"] -= dt
    dh = math.hypot(hx - n["x"], hy - n["y"])
    if dh < 3.0:                                                 # perto do herói: vira para ele
        n["face"] = math.atan2(hy - n["y"], hx - n["x"])
    if n["wait"] > 0.0 or dh < 1.1:
        return
    cur = cell_of(n["x"], n["y"])
    for _ in range(10):
        goal = (int(math.floor(n["home"][0] + rng.uniform(-4.5, 4.5))), int(math.floor(n["home"][1] + rng.uniform(-4.5, 4.5))))
        if goal == cur or not (0 <= goal[0] < size - 1 and 0 <= goal[1] < size - 1) or goal in blocked:
            continue
        cells = find_cells(cur, goal, False, blocked)
        if cells and len(cells) >= 2:
            n["wp"] = [(i + 0.5 + rng.uniform(-0.12, 0.12), j + 0.5 + rng.uniform(-0.12, 0.12)) for i, j in cells[1:]]
            n["halt"] = n["stuck"] = 0.0
            return
    n["wait"] = rng.uniform(1.0, 3.0)


VW_Z = {"house_r": 2.0, "house_b": 2.0, "house_t": 2.0,      # fator de altura: a vila fica mais alta, a pegada (x, y) não muda
        "smithy": 2.0, "tree": 1.55, "pine": 1.5, "well": 1.3, "stall": 1.3, "lamppost": 1.45, "signpost": 1.25, "hay": 1.2}


def _vw_tall(P, k):
    return [(a, b, c * k, d, e, f * k, col) for (a, b, c, d, e, f, col) in P]


def village_parts(kind, t=0.0):
    """Voxels (dx, dy, dz, w, d, h, cor) da decoração do vilarejo."""
    return _vw_tall(_village_parts_base(kind, t), VW_Z.get(kind, 1.0))


def _village_parts_base(kind, t=0.0):
    if kind in VW_ROOFS:
        return _vw_house(kind)
    if kind == "smithy":
        return _vw_smithy(t)
    if kind == "anvil":
        return _vw_anvil()
    if kind in NPC_KINDS:
        return npc_parts(kind, t, local=True)
    if kind == "tree":
        return _vw_tree(False)
    if kind == "pine":
        return _vw_tree(True)
    if kind == "well":
        return _vw_well()
    if kind == "stall":
        return _vw_stall()
    if kind == "hay":
        return [(0.0, 0.0, 0.0, 0.7, 0.7, 0.35, (206, 170, 80)), (0.08, 0.08, 0.35, 0.54, 0.54, 0.25, (220, 184, 92)),
                (0.2, 0.2, 0.60, 0.30, 0.30, 0.15, (232, 198, 104))]
    if kind == "lamppost":
        return [(0.08, 0.08, 0.0, 0.16, 0.16, 0.14, VW_STONE), (0.12, 0.12, 0.14, 0.08, 0.08, 1.10, (60, 52, 58)),
                (0.06, 0.06, 1.24, 0.20, 0.20, 0.26, (255, 206, 110)), (0.04, 0.04, 1.50, 0.24, 0.24, 0.06, (60, 52, 58)),
                (0.13, 0.13, 1.56, 0.06, 0.06, 0.08, (60, 52, 58))]
    if kind == "signpost":
        return [(0.20, 0.20, 0.0, 0.10, 0.10, 1.0, VW_WOOD_D),
                (0.0, 0.30, 0.70, 0.55, 0.07, 0.24, (176, 134, 82)), (0.55, 0.30, 0.74, 0.10, 0.07, 0.16, (176, 134, 82)),
                (0.06, 0.37, 0.78, 0.06, 0.02, 0.12, DARK), (0.18, 0.37, 0.78, 0.06, 0.02, 0.12, DARK),
                (0.30, 0.37, 0.80, 0.06, 0.02, 0.08, DARK), (0.42, 0.37, 0.78, 0.10, 0.02, 0.10, (240, 240, 230))]
    if kind == "fence_x":          # corre ao longo de x
        return [(0.0, 0.0, 0.0, 0.1, 0.1, 0.55, VW_WOOD_D), (0.9, 0.0, 0.0, 0.1, 0.1, 0.55, VW_WOOD_D),
                (0.0, 0.02, 0.20, 1.0, 0.06, 0.07, VW_WOOD), (0.0, 0.02, 0.40, 1.0, 0.06, 0.07, VW_WOOD)]
    if kind == "fence_y":          # corre ao longo de y
        return [(0.0, 0.0, 0.0, 0.1, 0.1, 0.55, VW_WOOD_D), (0.0, 0.9, 0.0, 0.1, 0.1, 0.55, VW_WOOD_D),
                (0.02, 0.0, 0.20, 0.06, 1.0, 0.07, VW_WOOD), (0.02, 0.0, 0.40, 0.06, 1.0, 0.07, VW_WOOD)]
    g = (70, 150, 70)              # flowers
    return [(0.0, 0.0, 0.0, 0.04, 0.04, 0.14, g), (0.0, 0.0, 0.14, 0.07, 0.07, 0.06, (240, 120, 170)),
            (0.20, 0.06, 0.0, 0.04, 0.04, 0.18, g), (0.19, 0.05, 0.18, 0.07, 0.07, 0.06, (248, 214, 90)),
            (0.10, 0.22, 0.0, 0.04, 0.04, 0.12, g), (0.09, 0.21, 0.12, 0.07, 0.07, 0.06, (240, 240, 236)),
            (0.30, 0.24, 0.0, 0.04, 0.04, 0.15, g), (0.29, 0.23, 0.15, 0.07, 0.07, 0.06, (240, 120, 170))]


_decor_parts2_base = decor_parts2


def decor_parts2(kind, t=0.0):                      # noqa: F811  (estende a função original com o vilarejo)
    if kind in VILLAGE_KINDS:
        return village_parts(kind, t)
    return _decor_parts2_base(kind, t)


def village_rect(x, y, kind):
    ps = village_parts(kind)
    return (x + min(p[0] for p in ps), y + min(p[1] for p in ps),
            x + max(p[0] + p[3] for p in ps), y + max(p[1] + p[4] for p in ps))


def gen_village(rng):
    """Cenário inicial: o vilarejo (sem inimigos), numa grade VILLAGE_N x VILLAGE_N (maior que as salas da masmorra).
    Devolve um 'lay' no mesmo formato de gen_floor. N já deve valer VILLAGE_N (Game.new_floor troca)."""
    houses = ["house_r", "house_b", "house_t"]
    rng.shuffle(houses)
    houses += [rng.choice(("house_r", "house_b", "house_t")) for _ in range(2)]
    decor = [(1.1, 0.2, houses[0]), (5.1, 0.2, houses[1]), (8.7, 0.2, houses[2]),          # fileira dos fundos
             (0.2, 4.2, houses[3]), (0.2, 8.4, houses[4]),                                   # coluna da esquerda
             (5.05, 5.05, "well"), (8.2, 4.0, "stall"), (9.6, 2.7, "crate"), (8.45, 5.45, "barrel"),
             (8.8, 6.2, "hay"), (6.3, 7.2, "signpost"),
             (9.9, 5.4, "tree"), (0.3, 6.6, "tree"), (2.4, 9.4, "pine"), (7.1, 9.7, "pine"),
             (3.2, 1.0, "pine"), (9.9, 6.6, "tree"),
             (3.35, 2.65, "lamppost"), (3.6, 6.5, "lamppost"), (8.2, 8.2, "lamppost"), (10.1, 8.0, "lamppost"),
             (6.3, 4.4, "lamppost"),
             (2.5, 5.0, "villager_%d" % rng.choice((0, 1, 2))), (8.6, 3.0, "merchant_npc"), (2.1, 6.6, "villager_2"),
             (5.4, 3.2, "villager_1"), (7.5, 7.6, "villager_0"),
             (3.0, 7.3, "smithy"), (4.0, 9.4, "smith_npc"), (4.8, 9.52, "anvil"),                 # forja do ferreiro
             (0.4, 2.7, "flowers"), (4.1, 1.2, "flowers"), (2.0, 6.8, "flowers"), (5.7, 8.3, "flowers"),
             (7.3, 1.2, "flowers"), (8.3, 9.9, "flowers"), (3.0, 9.8, "flowers"),
             (4.5, 2.0, "grass"), (10.2, 9.4, "grass"), (2.2, 8.2, "grass"), (6.9, 10.0, "grass"),
             (0.5, 10.0, "grass"), (7.9, 2.3, "grass"), (9.9, 4.2, "grass")]
    for i in range(N):                                  # cerca na beirada da frente (com um portão aberto)
        if i not in (4, 5, 6):
            decor.append((i, N - 0.22, "fence_x"))
        if i < N - 1:
            decor.append((N - 0.22, i, "fence_y"))
    # células bloqueadas para o A*: onde a pegada do objeto cobre pelo menos 0,4 da célula nos dois eixos
    blocked = set()
    for (x, y, kind) in decor:
        if kind not in SOLID_KINDS or kind.startswith("fence") or kind in WANDER_KINDS:     # aldeões andam: não bloqueiam células
            continue
        r = village_rect(x, y, kind) if kind in VILLAGE_KINDS else None
        if r is None:
            r = (x, y, x + 0.62, y + 0.62)               # caixa/barril: pegada pequena
        for i in range(N):
            for j in range(N):
                if min(r[2], i + 1) - max(r[0], i) >= 0.4 and min(r[3], j + 1) - max(r[1], j) >= 0.4:
                    blocked.add((i, j))
    trail = [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7),
             (8, 7), (9, 7), (9, 8), (9, 9)]
    ring = {(4, 4), (5, 4), (6, 4), (4, 5), (6, 5), (4, 6), (5, 6), (6, 6)}               # praça em volta do poço
    dirt = set(trail) | ring | {(1, 2), (5, 2), (9, 2), (1, 6), (2, 6), (2, 5), (3, 6), (1, 10), (2, 10),
                                (3, 5), (3, 4), (5, 7), (5, 8), (3, 9), (4, 9), (5, 9), (8, 4), (8, 5)}
    spawn, stairs = (1.5, 3.5), (9.5, 9.5)
    smith, smith_npc = (5.8, 9.5), (4.9, 9.6)          # onde o herói para para falar com o ferreiro / centro da forja
    return dict(room="vila", duplo=False, pal_idx=50, pal=VILLAGE_PAL, spawn=spawn, foes=[], stairs=stairs,
                decor=decor, blocked=blocked, torches=[], banners=[], banner=VILLAGE_NAME,
                arche="vila", cave=False, water=set(), bridges=set(), fords=set(), river_axis="y",
                liquid="agua", wall_crystals=[], tunnel=None, motes=[], village=True, trail=trail, dirt=dirt, smith=smith, smith_npc=smith_npc,
                market=(7.6, 3.4), market_npc=(8.96, 3.34))


def build_village(seed, lay):
    """Cenário em cache do vilarejo: céu de entardecer, serras ao fundo, ilha de grama e terra, muro baixo com sebe."""
    rng = random.Random(seed)
    fa, fb, wa, wb, _, ban = VILLAGE_PAL
    s = pygame.Surface((W, H))

    def sky(y):
        c = mix((10, 10, 34), min(1.0, y / (H * 0.42)), (58, 40, 96))        # azul-noite -> violeta
        return mix(c, 0.85 * math.exp(-((y - 330) / 105.0) ** 2), (236, 134, 92))   # brilho do poente

    for y in range(H):
        pygame.draw.line(s, sky(y), (0, y), (W, y))
    for _ in range(90):                                                      # estrelas
        x, y = rng.randrange(W), rng.randrange(0, 300)
        b = int(rng.randint(150, 255) * (1 - y / 360.0))
        s.set_at((x, y), (b, b, min(255, b + 20)))
        if rng.random() < 0.15:
            s.fill((b, b, min(255, b + 20)), (x, y, 2, 2))
    s.blit(make_glow(90, (60, 56, 80)), (150 - 90, 92 - 90), special_flags=pygame.BLEND_RGB_ADD)   # lua com halo
    pygame.draw.circle(s, (238, 232, 206), (150, 92), 30)
    pygame.draw.circle(s, sky(86), (163, 86), 27)
    cl = pygame.Surface((W, H), pygame.SRCALPHA)                             # nuvens compridas
    for _ in range(6):
        cx, cy = rng.randrange(40, W - 200), rng.randrange(90, 250)
        for k in range(3):
            pygame.draw.ellipse(cl, (92, 58, 118, 70), (cx + k * 34, cy + k % 2 * 8, rng.randint(120, 220), rng.randint(14, 24)))
    s.blit(cl, (0, 0))

    def ridge(base, amp, col, tips):
        ph1, ph2 = rng.uniform(0, 6), rng.uniform(0, 6)
        pts = [(x, base + amp * (math.sin(x * 0.011 + ph1) + 0.5 * math.sin(x * 0.029 + ph2))) for x in range(0, W + 8, 8)]
        pygame.draw.polygon(s, col, [(0, H)] + pts + [(W, H)])
        if tips:                                                             # silhueta de pinheiros
            for x in range(0, W, 13):
                ry = base + amp * (math.sin(x * 0.011 + ph1) + 0.5 * math.sin(x * 0.029 + ph2))
                hh = rng.randint(16, 32)
                pygame.draw.polygon(s, shade(col, 0.9), [(x - 7, ry + 2), (x + 7, ry + 2), (x, ry - hh)])

    ridge(300, 26, (52, 36, 86), False)
    ridge(345, 18, (34, 26, 62), True)

    # ilha: camadas de terra sob o piso
    rock = (74, 56, 44)
    for layer, (z0, lo, hi, keep) in enumerate(((-1.25, -1, N, 0.80), (-1.9, 1, N - 1, 0.72), (-2.5, 2, N - 2, 0.65))):
        for x in range(lo, hi):
            for y in range(lo, hi):
                if rng.random() > keep and layer > 0:
                    continue
                if layer == 0 and (x == N - 1 or y == N - 1) and rng.random() < 0.3:
                    continue
                draw_box(s, x, y, z0, 1, 1, 0.65, shade(rock, 0.92 - 0.1 * layer + rng.uniform(-0.04, 0.04)), g=0.34, tex=0.07)

    # piso: grama e terra batida (nas bordas da frente, um beiral de grama sobre a terra)
    dirt = lay["dirt"]
    soil = (96, 72, 52)
    for x in range(N):
        for y in range(N):
            if (x, y) in dirt:
                c = shade((150, 118, 80) if (x + y) % 2 == 0 else (138, 106, 72), rng.uniform(0.95, 1.05))
            else:
                c = shade(fa if (x + y) % 2 == 0 else fb, rng.uniform(0.95, 1.05))
            if x == N - 1 or y == N - 1:
                draw_box(s, x, y, -0.6, 1, 1, 0.42, shade(soil, rng.uniform(0.9, 1.1)), g=0.2, tex=0.06)
                draw_box(s, x, y, -0.18, 1, 1, 0.13, c, g=0.2, tex=0.05, bevel=True)
            else:
                draw_box(s, x, y, -0.6, 1, 1, 0.55, c, g=0.2, tex=0.05, bevel=True)
    specks = []
    for _ in range(70):                                                      # tufos de grama e pedrinhas soltas
        x, y = rng.uniform(0.2, N - 0.3), rng.uniform(0.2, N - 0.3)
        specks.append((x + y, x, y, (int(x), int(y)) in dirt))
    specks.sort()
    for _, x, y, on_dirt in specks:
        if on_dirt:
            sz = rng.uniform(0.07, 0.14)
            draw_box(s, x, y, -0.05, sz, sz, sz * 0.7, shade((140, 134, 130), rng.uniform(0.7, 1.0)), outline=False)
        else:
            for _ in range(rng.randint(2, 4)):
                gx, gy = x + rng.uniform(-0.12, 0.12), y + rng.uniform(-0.12, 0.12)
                draw_box(s, gx, gy, -0.05, 0.05, 0.05, rng.uniform(0.08, 0.20), shade((74, 156, 72), rng.uniform(0.8, 1.2)), outline=False)

    # sombras dos objetos grandes (camada translúcida mesclada no cenário)
    sh = pygame.Surface((W, H), pygame.SRCALPHA)
    for (x, y, kind) in lay["decor"]:
        if kind in VILLAGE_BLOCK and not kind.startswith("fence") and kind not in WANDER_KINDS:
            x0, y0, x1, y1 = village_rect(x, y, kind)
            ext = 0.15 if kind.startswith(("villager", "lamppost", "signpost")) else 0.35
            P = lambda a, b: proj(a, b, 0.0)
            pygame.draw.polygon(sh, (6, 8, 24, 70), [P(x0 - 0.05, y0 - 0.05), P(x1 + ext, y0 - 0.05), P(x1 + ext, y1 + ext), P(x0 - 0.05, y1 + ext)])
    s.blit(sh, (0, 0))

    # muro baixo de pedra com sebe, nas duas bordas do fundo, e dois mastros com bandeira
    for i in range(-1, N):
        c = shade(wa if i % 2 == 0 else wb, rng.uniform(0.94, 1.06))
        draw_box(s, -0.45, i, -0.6, 0.45, 1, 1.4, c, g=0.2, tex=0.06, bevel=True)
        draw_box(s, -0.41, i + 0.04, 0.8, 0.37, 0.92, 0.28, shade((58, 122, 62), rng.uniform(0.8, 1.2)), g=0.15, tex=0.08)
    for i in range(0, N):
        c = shade(wb if i % 2 == 0 else wa, rng.uniform(0.94, 1.06))
        draw_box(s, i, -0.45, -0.6, 1, 0.45, 1.4, c, g=0.2, tex=0.06, bevel=True)
        draw_box(s, i + 0.04, -0.41, 0.8, 0.92, 0.37, 0.28, shade((58, 122, 62), rng.uniform(0.8, 1.2)), g=0.15, tex=0.08)
    gold = (240, 205, 80)
    for ax, v in (("x", 2.8), ("y", 4.5), ("x", 7.0), ("y", 8.6)):
        wbox(s, ax, v, 0.0, 0.1, 0.9, 1.4, 0.1, VW_WOOD_D, off=-0.30)
        wbox(s, ax, v, 0.1, 0.6, 1.95, 0.32, 0.05, ban, off=-0.28, g=0.1)
        wbox(s, ax, v, -0.02, 0.14, 2.30, 0.14, 0.14, gold, off=-0.32, outline=False)
    try:
        s = s.convert()
    except Exception:
        pass
    return s


# ------------------------------------------------------------------ cartas
# arte pixel 12x12 dos ícones das cartas
ICON_ART = {
    "coracao": ([
        "............",
        ".kkk....kkk.",
        "kRRRk..kRRRk",
        "kRwRRkkRRRRk",
        "kRwRRRRRRRRk",
        "kRRRRRRRRRRk",
        ".kRRRRRRRRk.",
        "..kRRRRRRk..",
        "...kRRRRk...",
        "....kRRk....",
        ".....kk.....",
        "............"],
        {"k": (80, 15, 35), "R": (236, 70, 100), "w": (255, 205, 215)}),
}


# ------------------------------------------------------ fonte do título (estilo D&D)
# 1) arquivo .ttf/.otf na pasta do jogo (ou em ./fonts) cujo nome contenha uma destas palavras;
# 2) fonte instalada no sistema, na ordem abaixo (as primeiras são as mais parecidas com a do D&D);
# 3) fonte padrão do pygame.
TITLE_FONT_FILES = ("mookmania", "modesto", "dungeon", "dnd", "titulo", "title")
TITLE_FONT_SYS = ("mookmania", "modestocondensed", "modestocaps", "modesto", "cinzeldecorative", "cinzel", "trajanpro",
                  "trajan", "optimustitling", "papyrus", "palatinolinotype", "bookantiqua", "georgia")


def find_title_font():
    base = os.path.dirname(os.path.abspath(__file__))
    for folder in (base, os.path.join(base, "fonts")):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for key in TITLE_FONT_FILES:
            for n in names:
                if n.lower().endswith((".ttf", ".otf")) and key in n.lower():
                    return os.path.join(folder, n)
    for name in TITLE_FONT_SYS:
        try:
            p = pygame.font.match_font(name, bold=True) or pygame.font.match_font(name)
        except Exception:
            p = None
        if p:
            return p
    return None


def wrap(font, text, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.size(t)[0] <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------- sons
def tone(freq, dur, vol=0.25, slide=0.0):
    n = int(22050 * dur)
    buf = bytearray()
    for i in range(n):
        t = i / 22050
        f = freq + slide * i / n
        v = int(32767 * vol * math.sin(2 * math.pi * f * t) * (1 - i / n))
        buf += struct.pack("<h", v)
    return pygame.mixer.Sound(buffer=bytes(buf))


def build_adventure_theme():
    notes = [261.63, 329.63, 392.00, 329.63, 392.00, 493.88, 523.25, 493.88, 392.00, 329.63, 293.66, 329.63]
    seq = []
    for note in notes:
        seq.append((note, 0.17))
        seq.append((0, 0.05))
    return seq


# ================================================================== TRILHA SONORA
# Trilha "Aventura Medieval" gerada por código (100% offline, sem arquivos de áudio):
# alaúde em arpejo, baixo "oom-pah", flauta com vibrato, tambor, pandeiro e zumbido de gaita-de-foles.
# Ré dórico, 132 BPM, 16 compassos (~29 s) em loop contínuo.
SR = 22050
BPM = 132
_NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi(name):
    n = name[0]
    acc = 0
    rest = name[1:]
    if rest[0] == "#":
        acc, rest = 1, rest[1:]
    elif rest[0] == "b":
        acc, rest = -1, rest[1:]
    return 12 * (int(rest) + 1) + _NOTE_BASE[n] + acc


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


MEDIEVAL_MELODY = [
    "D4 - F4 A4 A4 - G4 F4", "E4 - G4 C5 C5 - G4 E4", "D4 - F4 A4 D5 - C5 A4", "A4 - C5 A4 E4 - - .",
    "D4 - F4 A4 A4 - G4 F4", "E4 - G4 C5 E5 - D5 C5", "D5 - Bb4 G4 Bb4 - D5 -", "C#5 - E5 A4 C#5 - - .",
    "A4 - C5 F5 F5 - E5 C5", "G4 - C5 E5 G5 - E5 C5", "F5 - E5 D5 A4 - D5 F5", "E5 - C5 A4 E5 - - .",
    "A4 - C5 F5 A5 - G5 F5", "E5 - G5 E5 C5 - E5 G5", "A4 - C#5 E5 A5 - E5 C#5", "D5 - A4 - D4 - - .",
]
# (baixo, tríade) de cada compasso
_CH = {"Dm": ("D2", ("D3", "F3", "A3")), "C": ("C2", ("C3", "E3", "G3")), "Gm": ("G2", ("G3", "Bb3", "D4")),
       "Am": ("A2", ("A3", "C4", "E4")), "A": ("A2", ("A3", "C#4", "E4")), "F": ("F2", ("F3", "A3", "C4"))}
MEDIEVAL_CHORDS = ["Dm", "C", "Dm", "Am", "Dm", "C", "Gm", "A", "F", "C", "Dm", "Am", "F", "C", "A", "Dm"]


def build_medieval_track(pause=None):
    """Devolve bytes PCM 16-bit mono (22050 Hz) prontos para pygame.mixer.Sound(buffer=...)."""
    rnd = random.Random(7)
    sin, exp, tau = math.sin, math.exp, math.tau
    eighth = 60.0 / BPM / 2.0
    bars = len(MEDIEVAL_MELODY)
    N = int(bars * 8 * eighth * SR)
    TAIL = SR
    master = [0.0] * (N + TAIL)
    cache = {}

    def mix(wave, t0, gain):
        a = int(t0 * SR)
        b = min(len(master), a + len(wave))
        if b <= a:
            return
        seg = master[a:b]
        master[a:b] = [x + y * gain for x, y in zip(seg, wave)]
        if pause:
            pause()

    def wave(kind, f, d):
        key = (kind, round(f, 2), round(d, 3))
        w = cache.get(key)
        if w is not None:
            return w
        n = int(d * SR)
        out = [0.0] * n
        if kind == "pluck":          # alaúde: ataque seco, harmônicos que morrem rápido
            for i in range(n):
                t = i / SR
                e = min(1.0, t * 400) * exp(-t * 5.5)
                out[i] = e * (sin(tau * f * t) + 0.45 * exp(-t * 4) * sin(tau * f * 2 * t) + 0.2 * exp(-t * 8) * sin(tau * f * 3 * t))
        elif kind == "flute":        # flauta: vibrato suave depois do ataque + um pouco de sopro
            for i in range(n):
                t = i / SR
                att = min(1.0, t / 0.035)
                rel = min(1.0, (d - t) / 0.07)
                vib = 1 + 0.004 * sin(tau * 5.4 * t) * min(1.0, t / 0.25)
                ph = tau * f * vib * t
                out[i] = att * rel * (sin(ph) + 0.28 * sin(2 * ph) + 0.08 * sin(3 * ph) + 0.03 * (rnd.random() * 2 - 1))
        elif kind == "bass":         # baixo macio, quase triangular
            for i in range(n):
                t = i / SR
                e = min(1.0, t * 300) * exp(-t * 3.2)
                out[i] = e * (sin(tau * f * t) + 0.3 * sin(tau * f * 3 * t) / 3 + 0.12 * sin(tau * f * 2 * t))
        elif kind == "drone":        # zumbido de gaita: quinta justa bem baixinha
            for i in range(n):
                t = i / SR
                e = min(1.0, t / 0.08) * min(1.0, (d - t) / 0.2)
                out[i] = e * (sin(tau * f * t) + 0.6 * sin(tau * f * 1.5 * t) + 0.25 * sin(tau * f * 2 * t))
        elif kind == "kick":
            ph = 0.0
            for i in range(n):
                t = i / SR
                ph += tau * (48 + 90 * exp(-t * 28)) / SR
                out[i] = sin(ph) * exp(-t * 11) * min(1.0, t * 800)
        elif kind == "snare":        # tambor de mão / pandeiro
            for i in range(n):
                t = i / SR
                out[i] = (0.75 * (rnd.random() * 2 - 1) * exp(-t * 26) + 0.5 * sin(tau * 190 * t) * exp(-t * 30))
        elif kind == "shaker":
            prev = 0.0
            for i in range(n):
                t = i / SR
                r = rnd.random() * 2 - 1
                out[i] = (r - prev) * exp(-t * 70)
                prev = r
        cache[key] = out
        return out

    # drone contínuo (Ré + Lá) por compasso
    for bar in range(bars):
        t0 = bar * 8 * eighth
        mix(wave("drone", _hz(_midi("D2")), 8 * eighth + 0.1), t0, 0.05)
    for bar in range(bars):
        base = bar * 8 * eighth
        bass, tri = _CH[MEDIEVAL_CHORDS[bar]]
        bm = _midi(bass)
        for i in range(8):
            t0 = base + i * eighth
            # baixo oom-pah
            if i in (0, 4):
                mix(wave("bass", _hz(bm), eighth * 2.2), t0, 0.40)
            elif i in (2, 6):
                mix(wave("bass", _hz(bm + 7), eighth * 1.6), t0, 0.22)
            # alaúde arpejando a tríade
            order = (0, 2, 1, 2, 0, 2, 1, 2)[i]
            mix(wave("pluck", _hz(_midi(tri[order])), eighth * 3.0), t0, 0.15 if i % 2 else 0.19)
            # percussão
            if i in (0, 4):
                mix(wave("kick", 0, 0.26), t0, 0.62)
            if i in (2, 6):
                mix(wave("snare", 0, 0.13), t0, 0.22)
            mix(wave("shaker", 0, 0.06), t0 + (eighth * 0.0), 0.05 if i % 2 == 0 else 0.032)
            if bar % 4 == 3 and i >= 6:      # pequena virada no fim de cada 4 compassos
                mix(wave("snare", 0, 0.13), t0 + eighth * 0.5, 0.16)
        # melodia na flauta (o '-' prolonga a nota, o '.' é pausa)
        toks = MEDIEVAL_MELODY[bar].split()
        i = 0
        while i < 8:
            tk = toks[i]
            if tk in (".", "-"):
                i += 1
                continue
            j = i + 1
            while j < 8 and toks[j] == "-":
                j += 1
            d = (j - i) * eighth * 0.96
            m = _midi(tk)
            mix(wave("flute", _hz(m), d), base + i * eighth, 0.30 if bar < 8 else 0.33)
            if bar >= 8:     # na segunda metade entra uma segunda flauta uma oitava abaixo
                mix(wave("flute", _hz(m - 12), d), base + i * eighth, 0.10)
            i = j
    # fecha o loop: a cauda do final soa por cima do começo
    for i in range(TAIL):
        master[i] += master[N + i]
    master = master[:N]
    peak = max(max(master), -min(master)) or 1.0
    k = 0.80 * 32767 / peak
    return struct.pack("<%dh" % len(master), *[int(x * k) for x in master])


TORCHES = [("x", 2.5), ("x", 6.5), ("y", 2.5), ("y", 6.5)]


# -------------------------------------------------------------------- jogo
# ------------------------------------------------------------ HUD em pixel art
# Estilo "RPG HUD": molduras bege/aço de contorno escuro, barras de vida (vermelha) e fôlego (azul),
# placa de madeira pendurada por correntes, bolsa de ouro e placa vermelha com chifres para o inimigo.
# Tudo é desenhado numa grade pequena e ampliada sem suavização (cada "pixel" da HUD = PXS pixels da tela).
PXS = 3
PX_OL = (10, 6, 12)                                   # contorno escuro
PX_TAN = ((190, 160, 108), (122, 94, 64), (70, 52, 42))      # claro, médio, escuro
PX_STEEL = ((142, 146, 160), (88, 92, 106), (50, 52, 64))
PX_WARM = ((212, 146, 76), (146, 84, 46), (84, 42, 32))
PX_WOOD = ((118, 82, 58), (78, 52, 40), (46, 30, 28))
PX_CRIM = ((156, 44, 60), (100, 20, 40), (56, 10, 30))
PX_RED = ((255, 164, 132), (230, 64, 60), (140, 28, 46))         # barra de vida
_PXC = {}


def px_get(key, build):
    im = _PXC.get(key)
    if im is None:
        if len(_PXC) > 700:
            _PXC.clear()
        im = _PXC[key] = build()
    return im


def px_up(im, k=PXS):
    return pygame.transform.scale(im, (im.get_width() * k, im.get_height() * k))


def px_grid(rows, pal):
    s = pygame.Surface((max(len(r) for r in rows), len(rows)), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            c = pal.get(ch)
            if c:
                s.set_at((x, y), c)
    return s


def px_outline(s, col=PX_OL):
    w, h = s.get_size()
    o = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
    for y in range(h):
        for x in range(w):
            if s.get_at((x, y))[3]:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                    o.set_at((x + 1 + dx, y + 1 + dy), col)
    o.blit(s, (1, 1))
    return o


def px_frame(w, h, pal, inner=None, t=1, rnd=True):
    """Moldura: contorno escuro, anel (claro em cima/esquerda, escuro embaixo/direita), contorno interno, miolo."""
    hi, mid, lo = pal
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    s.fill(PX_OL)
    s.fill(mid, (1, 1, w - 2, h - 2))
    s.fill(hi, (1, 1, w - 2, 1))
    s.fill(hi, (1, 1, 1, h - 2))
    s.fill(lo, (1, h - 2, w - 2, 1))
    s.fill(lo, (w - 2, 1, 1, h - 2))
    b = 1 + t
    s.fill(PX_OL, (b, b, w - 2 * b, h - 2 * b))
    if inner is not None:
        s.fill(inner, (b + 1, b + 1, w - 2 * b - 2, h - 2 * b - 2))
    if rnd:
        for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            s.set_at((cx, cy), (0, 0, 0, 0))
    return s


def px_chain(s, x, y0, y1):
    for y in range(y0, y1):
        c = PX_STEEL[y % 3]
        s.fill(PX_OL, (x - 1, y, 4, 1))
        s.fill(c, (x, y, 2, 1))


_PX_ICONS = {
    "heart": ([".rr.rr.", "rHrrrrr", "rrrrrrr", ".rrrrR.", "..rRR..", "...R..."],
              {"r": (238, 62, 62), "H": (255, 190, 176), "R": (170, 30, 52)}),
    "drop": (["..b..", "..b..", ".bbb.", "bHbbb", "bbbbb", "bbbbB", ".bBB."],
             {"b": (92, 196, 255), "H": (228, 247, 255), "B": (40, 108, 208)}),
    "pouch": (["....bb.bb....", ".....bbb.....", "....DDDDD....", "...bbbbbbb...", "..bhhbbbbbb..",
               ".bhhbbbbbbbb.", ".bhbbbbxbbbB.", ".bbbbbxbxbbB.", ".bbbbbbxbbbB.", ".bbbbbxbxbbB.",
               ".bbbbbbbbbBB.", "..bbbbbbBBB..", "...BBBBBBB..."],
              {"b": (192, 114, 66), "h": (234, 164, 102), "B": (130, 72, 46), "D": (92, 50, 40), "x": (72, 38, 36)}),
    "house": (["....w....", "...www...", "..wwwww..", ".wwwwwww.", "..wwwww..", "..wwdww..", "..wwdww.."],
              {"w": (255, 238, 222), "d": (130, 44, 64)}),
}
_PX_SPIKE = ["..w..", "..w..", ".wsw.", ".wsw.", "wsssw", "wsssw"]
_PX_SPIKE_S = ["wsssw", ".wsw.", "..w.."]
_PX_SPIKE_PAL = {"w": (238, 242, 246), "s": (160, 170, 188)}


def px_sword(n):
    s = pygame.Surface((n, n), pygame.SRCALPHA)
    ln = n - 5
    for i in range(ln):
        x, y = n - 1 - i, i
        s.set_at((x, y), (238, 242, 248))
        s.set_at((x - 1, y), (150, 162, 184))
    gx, gy = n - 1 - ln, ln
    gold, brown = (242, 198, 74), (150, 84, 52)
    for d in (-1, 0, 1):
        s.set_at((gx + d, gy + d), gold)
    for d in (1, 2):
        s.set_at((gx - d, gy + d), brown)
    s.set_at((gx - 3, gy + 3), gold)
    return s


def px_build_icon(name):
    if name == "sword9":
        return px_outline(px_sword(9))
    grid, pal = _PX_ICONS[name]
    return px_outline(px_grid(grid, pal))


def px_icon(name):
    return px_get(("icon", name), lambda: px_up(px_build_icon(name)))


def px_text(s, size, col, ol, k):
    """Texto em pixels: renderiza pequeno, corta o serrilhado (limiar) e amplia k vezes."""
    def build():
        f = pygame.font.Font(None, size)
        base = f.render(s if s else " ", True, (255, 255, 255))
        mask = pygame.mask.from_surface(base, 110)
        im = mask.to_surface(setcolor=(*col, 255), unsetcolor=(0, 0, 0, 0))
        r = im.get_bounding_rect()
        if r.w == 0 or r.h == 0:
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        im = im.subsurface(r).copy()
        if ol is not None:
            ink = mask.to_surface(setcolor=(*ol, 255), unsetcolor=(0, 0, 0, 0)).subsurface(r)
            out = pygame.Surface((r.w + 2, r.h + 2), pygame.SRCALPHA)
            for dx in (0, 1, 2):
                for dy in (0, 1, 2):
                    if dx != 1 or dy != 1:
                        out.blit(ink, (dx, dy))
            out.blit(im, (1, 1))
            im = out
        return px_up(im, k)
    return px_get(("t", s, size, col, ol, k), build)


def px_chip(w, h, pal, inner):
    return px_get(("chip", w, h, pal, inner), lambda: px_up(px_frame(w, h, pal, inner)))


def px_portrait(hero_col):
    s = px_frame(23, 23, PX_TAN, (36, 28, 38), t=2)
    sil = (124, 112, 122)
    ox = oy = 4
    for y in range(15):
        for x in range(15):
            if (x - 7) ** 2 + (y - 5) ** 2 <= 10:
                s.set_at((ox + x, oy + y), sil)
    for y in range(8, 15):
        hw = {8: 1, 9: 3, 10: 5, 11: 6}.get(y, 7)
        for x in range(7 - hw, 7 + hw + 1):
            s.set_at((ox + x, oy + y), sil)
    col = tuple(hero_col)[:3]
    for x in range(5, 10):
        s.set_at((ox + x, oy + 9), col)
    for x in range(4, 11):
        s.set_at((ox + x, oy + 10), mix(col, 0.25, (0, 0, 0)))
    return s


def px_bar(w, frac, cols, icon, ticks=0, warm=False, glow=0):
    """Barra de aço com ícone no canto; cada divisão (ticks) marca uma unidade (ex.: um coração)."""
    x0, x1 = 12, w - 3
    fw = int(round((x1 - x0) * max(0.0, min(1.0, frac))))
    if frac > 0:
        fw = max(2, fw)

    def build():
        s = px_frame(w, 11, PX_WARM if warm else PX_STEEL, (44, 28, 46))
        lt, ba, dk = cols
        if glow:
            lt, ba, dk = (mix(c, glow * 0.10, (255, 255, 255)) for c in (lt, ba, dk))
        if fw > 0:
            s.fill(lt, (x0, 3, fw, 1))
            s.fill(ba, (x0, 4, fw, 3))
            s.fill(dk, (x0, 7, fw, 1))
        for i in range(1, ticks):
            s.fill(PX_OL, (x0 + int(round((x1 - x0) * i / ticks)), 3, 1, 5))
        s.blit(px_build_icon(icon), (2 if icon == "heart" else 3, 1))
        return px_up(s)
    return px_get(("bar", w, fw, cols, ticks, icon, warm, glow), build)


def px_sign(boss):
    def build():
        c = 7
        s = pygame.Surface((60, c + 18), pygame.SRCALPHA)
        s.blit(px_frame(60, 18, PX_CRIM if boss else PX_WOOD, (62, 14, 26) if boss else (38, 26, 26), t=2), (0, c))
        for x in (9, 48):
            px_chain(s, x, 0, c + 2)
        return px_up(s)
    return px_get(("sign", boss), build)


def px_board():
    def build():
        c = 5
        s = pygame.Surface((36, c + 22), pygame.SRCALPHA)
        s.blit(px_frame(36, 22, PX_STEEL, (50, 68, 78), t=2), (0, c))
        for x in (6, 28):
            px_chain(s, x, 0, c + 2)
        return px_up(s)
    return px_get(("board",), build)


def px_enemy_plate(w, frac, cols):
    """Placa vermelha com chifres e espinhos (barra de vida do inimigo)."""
    x0, x1 = 3, w - 3
    fw = int(round((x1 - x0) * max(0.0, min(1.0, frac))))
    if frac > 0:
        fw = max(2, fw)

    def build():
        s = pygame.Surface((w, 21), pygame.SRCALPHA)
        s.blit(px_frame(w, 11, PX_CRIM, (58, 16, 36)), (0, 5))
        lt, ba, dk = cols
        if fw > 0:
            s.fill(lt, (x0, 8, fw, 1))
            s.fill(ba, (x0, 9, fw, 3))
            s.fill(dk, (x0, 12, fw, 1))
        up = px_outline(px_grid(_PX_SPIKE, _PX_SPIKE_PAL))
        dn = px_outline(px_grid(_PX_SPIKE_S, _PX_SPIKE_PAL))
        s.blit(up, (1, 0))
        s.blit(up, (w - 8, 0))
        for x in (18, 42, 66):
            s.blit(dn, (x, 15))
        return px_up(s)
    return px_get(("eplate", w, fw, cols), build)


def px_button(color, ready, frac):
    """Botão de luta 67x24: moldura de aço, miolo colorido, escurece conforme a recarga."""
    q = int(min(1.0, max(0.0, frac)) * 20)

    def build():
        s = px_frame(67, 24, PX_STEEL if ready else (PX_STEEL[1], PX_STEEL[2], shade(PX_STEEL[2], 0.7)), shade(color, 0.45), t=2)
        base = color if ready else shade(color, 0.55)
        s.fill(mix(base, 0.30), (4, 4, 59, 2))
        s.fill(base, (4, 6, 59, 10))
        s.fill(shade(base, 0.72), (4, 16, 59, 4))
        if q:
            ov = pygame.Surface((max(1, int(59 * q / 20)), 16), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 120))
            s.blit(ov, (4, 4))
        s.blit(px_frame(12, 12, PX_TAN, (196, 170, 120)), (6, 6))
        return px_up(s)
    return px_get(("btn", tuple(color), ready, q), build)



# ===================================================================== REDE (multiplayer)
PROTO = 2
DEFAULT_PORT = 5555
MAX_PLAYERS = 12
# --- servidores PÚBLICOS (3 salas fixas, 6 vagas cada, entrada instantânea) ---
PUBLIC_MAX = 6                                   # vagas de cada servidor público
PUBLIC_HOST = "127.0.0.1"                        # <<< TROQUE pelo DOMÍNIO/IP fixo da máquina que roda:  python rpg.py --public
# (opcional) URL de um arquivo de TEXTO com o host atual (1 linha, ex.: raw do GitHub). Assim, se o IP do servidor
# mudar, é só editar esse arquivo: quem já baixou o jogo continua entrando sem atualizar nada.
PUBLIC_HOST_URL = ""
PUBLIC_LOCAL = ("127.0.0.1", "localhost", "0.0.0.0", "")
MAX_PER_IP = 4                                   # conexões simultâneas por IP (anti-abuso no servidor aberto)
HELLO_TIMEOUT = 10.0                             # quem não se apresentar (hello/info) nesse tempo é desconectado
PUBLIC_SERVERS = (("Público 1", 5555), ("Público 2", 5556), ("Público 3", 5557))   # (nome, porta TCP)
SNAP_DT = 0.05
MP_ADDR_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-_")
HEROES_OK = ("knight", "ranger", "mage", "guardian", "rogue")
RACES_OK = ("human", "elf", "dwarf", "orc", "halfling", "tiefling")
ROOMS = ("lobby", "arena", "none")
MAX_LINE = 16384
USER_MIN, USER_MAX = 3, 12
MAX_FRIENDS, MAX_PENDING = 50, 30
try:
    SOCIAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obscurity_users.json")
except NameError:
    SOCIAL_PATH = "obscurity_users.json"


def valid_user(u):
    u = str(u or "")
    return USER_MIN <= len(u) <= USER_MAX and all((ch.isascii() and ch.isalnum()) or ch == "_" for ch in u)


class Social:
    """Contas, amigos e convites. Compartilhado pelos servidores públicos do mesmo programa; salvo em JSON."""

    def __init__(self, path=SOCIAL_PATH):
        import hashlib
        self._hash = lambda tok: hashlib.sha256(("obscurity|" + tok).encode("utf-8")).hexdigest()
        self.path, self.lock = path, threading.RLock()
        self.users = {}                    # chave(minúscula) -> {"name","h","fr":[],"in":[],"out":[]}
        self.online = {}                   # chave -> (conn, servidor)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.users = {k: v for k, v in data.items() if isinstance(v, dict) and "h" in v}
        except Exception:
            pass

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---- entrar / sair
    def login(self, user, tok, conn, srv):
        """Retorna (True, chave) ou (False, (codigo, mensagem))."""
        if not valid_user(user):
            return False, ("bad_name", "Nome de usuário inválido (3 a 12 letras, números ou _).")
        tok = str(tok or "")
        if len(tok) < 16 or len(tok) > 128:
            return False, ("bad_tok", "Conta inválida. Reabra o jogo.")
        key = user.lower()
        old = None
        with self.lock:
            u = self.users.get(key)
            if u is None:
                self.users[key] = {"name": user, "h": self._hash(tok), "fr": [], "in": [], "out": []}
                self._save()
            elif u["h"] != self._hash(tok):
                return False, ("name_taken", f"O nome '{u['name']}' já pertence a outra pessoa. Escolha outro.")
            prev = self.online.get(key)
            if prev is not None and prev[0] is not conn:
                old = prev[0]
            self.online[key] = (conn, srv)
        if old is not None:
            old.send({"t": "err", "msg": "Você entrou em outro lugar."})
            old.close()
        self.push_presence(key)
        return True, key

    def logout(self, conn, key):
        if not key:
            return
        with self.lock:
            cur = self.online.get(key)
            if cur is None or cur[0] is not conn:
                return
            del self.online[key]
        self.push_presence(key)

    # ---- dados
    def display(self, key):
        u = self.users.get(key)
        return u["name"] if u else key

    def payload(self, key):
        with self.lock:
            u = self.users.get(key)
            if not u:
                return {"t": "fl", "f": [], "in": [], "out": []}
            fl = []
            for fk in u["fr"]:
                on = self.online.get(fk)
                fl.append({"u": self.display(fk), "on": 1 if on else 0,
                           "s": on[1].name if on else "", "p": on[1].port if on else 0})
            fl.sort(key=lambda d: (-d["on"], d["u"].lower()))
            return {"t": "fl", "f": fl, "in": [self.display(k) for k in u["in"]],
                    "out": [self.display(k) for k in u["out"]]}

    def push(self, key):
        with self.lock:
            cur = self.online.get(key)
        if cur is not None:
            cur[0].send(self.payload(key))

    def push_presence(self, key):
        with self.lock:
            u = self.users.get(key)
            targets = list(u["fr"]) if u else []
        self.push(key)
        for fk in targets:
            self.push(fk)

    def note(self, key, msg):
        with self.lock:
            cur = self.online.get(key)
        if cur is not None:
            cur[0].send({"t": "note", "msg": msg})

    # ---- ações
    def handle(self, key, m):
        t = m.get("t")
        other = str(m.get("u") or "").strip().lower()
        with self.lock:
            me = self.users.get(key)
            if me is None:
                return
            if t == "fr_add":
                if not valid_user(m.get("u")):
                    return self.note(key, "Nome de usuário inválido.")
                o = self.users.get(other)
                if o is None:
                    return self.note(key, f"O usuário '{m.get('u')}' não existe.")
                if other == key:
                    return self.note(key, "Você não pode adicionar a si mesmo.")
                if other in me["fr"]:
                    return self.note(key, f"{o['name']} já é seu amigo.")
                if other in me["in"]:                         # ele já tinha pedido: vira amizade
                    return self._make_friends(key, other)
                if other in me["out"]:
                    return self.note(key, "Pedido já enviado. Aguarde a resposta.")
                if len(me["out"]) >= MAX_PENDING or len(o["in"]) >= MAX_PENDING:
                    return self.note(key, "Muitos pedidos pendentes.")
                me["out"].append(other)
                o["in"].append(key)
                self._save()
                self.note(key, f"Pedido enviado para {o['name']}.")
                self.note(other, f"{me['name']} quer ser seu amigo (aba PEDIDOS).")
            elif t == "fr_acc":
                if other in me["in"]:
                    if len(me["fr"]) >= MAX_FRIENDS:
                        return self.note(key, "Sua lista de amigos está cheia.")
                    return self._make_friends(key, other)
            elif t in ("fr_rej", "fr_del"):
                o = self.users.get(other)
                if o is None:
                    return
                for lst in ("in", "out"):
                    if other in me[lst]:
                        me[lst].remove(other)
                    if key in o[lst]:
                        o[lst].remove(key)
                if t == "fr_del":
                    if other in me["fr"]:
                        me["fr"].remove(other)
                    if key in o["fr"]:
                        o["fr"].remove(key)
                self._save()
            elif t == "inv":
                if other not in me["fr"]:
                    return self.note(key, "Só dá para convidar amigos.")
                cur = self.online.get(other)
                mine = self.online.get(key)
                if cur is None:
                    return self.note(key, f"{self.display(other)} está offline.")
                if mine is None:
                    return
                cur[0].send({"t": "inv", "from": me["name"], "s": mine[1].name or f"Servidor {mine[1].port}", "p": mine[1].port})
                return self.note(key, f"Convite enviado para {self.display(other)}.")
            else:
                return
        self.push(key)
        self.push(other)

    def _make_friends(self, a, b):
        ua, ub = self.users[a], self.users[b]
        for x, y in ((ua, b), (ub, a)):
            for lst in ("in", "out"):
                if y in x[lst]:
                    x[lst].remove(y)
        if b not in ua["fr"]:
            ua["fr"].append(b)
        if a not in ub["fr"]:
            ub["fr"].append(a)
        self._save()
        self.note(a, f"Agora você e {ub['name']} são amigos!")
        self.note(b, f"Agora você e {ua['name']} são amigos!")
        self.push(a)
        self.push(b)


_SOCIAL = None


def get_social():
    global _SOCIAL
    if _SOCIAL is None:
        _SOCIAL = Social()
    return _SOCIAL


def encode(obj):
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def parse_addr(text, default_port=DEFAULT_PORT):
    """'ip', 'ip:porta' ou 'nome.dominio:porta' -> (host, porta). Levanta ValueError se inválido."""
    t = (text or "").strip() or "127.0.0.1"
    host, port = t, default_port
    if t.count(":") == 1:
        h, p = t.split(":")
        host = h or "127.0.0.1"
        port = int(p)
    if not host or not (0 < port < 65536):
        raise ValueError("endereço inválido")
    return host, port


def upnp_open(ports, lease=3600, timeout=2.5):
    """Pede ao roteador (UPnP) para redirecionar portas TCP para este PC. Sem bibliotecas externas.
       Retorna (ok, ip_externo, mensagem)."""
    import re
    import urllib.request
    from urllib.parse import urlparse, urljoin
    try:
        ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ss.settimeout(timeout)
        found = None
        for st in ("urn:schemas-upnp-org:device:InternetGatewayDevice:1", "upnp:rootdevice"):
            req = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {st}\r\n\r\n").encode()
            try:
                ss.sendto(req, ("239.255.255.250", 1900))
                while True:
                    data, _ = ss.recvfrom(4096)
                    m = re.search(rb"(?i)location:\s*(\S+)", data)
                    if m:
                        found = m.group(1).decode()
                        break
            except socket.timeout:
                pass
            if found:
                break
        ss.close()
        if not found:
            return False, "", "roteador sem UPnP (ative UPnP no roteador ou redirecione as portas manualmente)"
        xml = urllib.request.urlopen(found, timeout=timeout).read().decode("utf-8", "ignore")
        m = re.search(r"<serviceType>(urn:schemas-upnp-org:service:WAN(?:IP|PPP)Connection:\d)</serviceType>.*?<controlURL>(.*?)</controlURL>",
                      xml, re.S)
        if not m:
            return False, "", "roteador não oferece redirecionamento de portas"
        stype, ctl = m.group(1), urljoin(found, m.group(2).strip())

        def soap(action, body):
            env = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                   's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                   f'<u:{action} xmlns:u="{stype}">{body}</u:{action}></s:Body></s:Envelope>').encode()
            rq = urllib.request.Request(ctl, env, {"Content-Type": 'text/xml; charset="utf-8"',
                                                    "SOAPAction": f'"{stype}#{action}"'})
            return urllib.request.urlopen(rq, timeout=timeout).read().decode("utf-8", "ignore")
        me = lan_ip()
        done = []
        for pt in ports:
            body = (f"<NewRemoteHost></NewRemoteHost><NewExternalPort>{pt}</NewExternalPort><NewProtocol>TCP</NewProtocol>"
                    f"<NewInternalPort>{pt}</NewInternalPort><NewInternalClient>{me}</NewInternalClient><NewEnabled>1</NewEnabled>"
                    f"<NewPortMappingDescription>Obscurity {pt}</NewPortMappingDescription><NewLeaseDuration>{lease}</NewLeaseDuration>")
            try:
                soap("AddPortMapping", body)
                done.append(pt)
            except Exception:
                pass
        ext = ""
        try:
            r = soap("GetExternalIPAddress", "")
            mm = re.search(r"<NewExternalIPAddress>(.*?)</NewExternalIPAddress>", r)
            ext = mm.group(1) if mm else ""
        except Exception:
            pass
        if not done:
            return False, ext, "o roteador recusou abrir as portas"
        UPNP_STATE.update(ctl=ctl, stype=stype, ports=done, lease=lease)
        return True, ext, f"portas {', '.join(map(str, done))} abertas no roteador"
    except Exception as e:
        return False, "", f"UPnP falhou ({e})"


UPNP_STATE = {}


def upnp_close():
    """Fecha as portas abertas por upnp_open (ao sair)."""
    if not UPNP_STATE.get("ports"):
        return
    try:
        import urllib.request
        for pt in UPNP_STATE["ports"]:
            env = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                   's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                   f'<u:DeletePortMapping xmlns:u="{UPNP_STATE["stype"]}"><NewRemoteHost></NewRemoteHost>'
                   f'<NewExternalPort>{pt}</NewExternalPort><NewProtocol>TCP</NewProtocol></u:DeletePortMapping>'
                   '</s:Body></s:Envelope>').encode()
            rq = urllib.request.Request(UPNP_STATE["ctl"], env, {"Content-Type": 'text/xml; charset="utf-8"',
                                        "SOAPAction": f'"{UPNP_STATE["stype"]}#DeletePortMapping"'})
            urllib.request.urlopen(rq, timeout=2).read()
    except Exception:
        pass
    UPNP_STATE.clear()


class AutoHost:
    """Sobe os servidores públicos em segundo plano e abre as portas no roteador, sem travar o jogo."""

    def __init__(self, log=lambda *a: None):
        self.log, self.servers, self.info, self.ext = log, {}, "Abrindo servidores públicos...", ""
        self.running = True
        import atexit
        atexit.register(self.stop)
        threading.Thread(target=self._run, daemon=True).start()

    def _start_missing(self):
        for nm, pt in PUBLIC_SERVERS:
            sv = self.servers.get(pt)
            if sv is None or not sv.running:
                try:
                    self.servers[pt] = Server(pt, max_players=PUBLIC_MAX, name=nm, log=self.log, social=get_social()).start()
                except OSError:
                    pass                                   # porta ocupada (outro servidor já está no ar)

    def _run(self):
        self._start_missing()
        ok, ext, msg = upnp_open([pt for _, pt in PUBLIC_SERVERS])
        self.ext = ext
        n = len(self.servers)
        self.info = (f"Hospedando {n} servidor(es) público(s)" + (f"  •  IP externo {ext}" if ext else "")
                     + f"  •  {msg}")
        self.log("[obscurity] " + self.info)
        last = time.time()
        while self.running:                                # renova o UPnP e reergue servidores caídos
            time.sleep(5)
            self._start_missing()
            if ok and time.time() - last > UPNP_STATE.get("lease", 3600) * 0.5:
                upnp_open([pt for _, pt in PUBLIC_SERVERS])
                last = time.time()

    def stop(self):
        if not self.running:
            return
        self.running = False
        for sv in self.servers.values():
            sv.stop()
        upnp_close()


def fetch_public_host(url, timeout=3.0):
    """Lê o host público atual de um arquivo de texto na internet. Retorna '' se falhar."""
    if not url:
        return ""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            txt = r.read(256).decode("utf-8", "ignore")
        host = txt.strip().splitlines()[0].strip() if txt.strip() else ""
        host = host.split(":")[0]
        if host and len(host) <= 100 and all(ch in MP_ADDR_CHARS for ch in host):
            return host
    except Exception:
        pass
    return ""


def _num(v, lo, hi, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (math.inf, -math.inf):
        return default
    return max(lo, min(hi, f))


def _clean_text(s, n):
    s = "".join(ch for ch in str(s) if ch.isprintable())
    return s.strip()[:n]


def query_server(host, port, timeout=1.5):
    """Pergunta a um servidor quantos jogadores ele tem. Retorna {'n','p','max'} ou None se estiver offline."""
    try:
        sk = socket.create_connection((host, port), timeout=timeout)
    except Exception:
        return None
    res = None
    try:
        sk.settimeout(timeout)
        sk.sendall(encode({"t": "info", "v": PROTO}))
        buf = b""
        while b"\n" not in buf and len(buf) < MAX_LINE:
            d = sk.recv(1024)
            if not d:
                break
            buf += d
        m = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        if isinstance(m, dict) and m.get("t") == "info":
            res = {"n": _clean_text(m.get("n"), 16), "p": int(_num(m.get("p"), 0, 999)),
                   "max": int(_num(m.get("max"), 1, 999, PUBLIC_MAX))}
    except Exception:
        res = None
    try:
        sk.close()
    except OSError:
        pass
    return res


# =================================================================== SERVIDOR
class _Conn:
    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self.out = queue.Queue(maxsize=400)
        self.id = None
        self.name, self.hero, self.race = "", "knight", "human"
        self.ukey = None
        self.st = {"room": "none", "x": 4.5, "y": 4.5, "hd": 0.0, "mv": 0, "lg": 0.0, "rl": -1.0,
                   "dead": 0, "hp": 1, "pm": 1}
        self.k = self.d = 0
        self.alive = True
        self.t_atk = 0.0
        self.t_died = 0.0

    def send(self, obj, droppable=False):
        if not self.alive:
            return
        try:
            self.out.put_nowait(encode(obj))
        except queue.Full:
            if not droppable:
                self.close()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.out.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Server:
    def __init__(self, port=DEFAULT_PORT, host="0.0.0.0", log=print, max_players=MAX_PLAYERS, name="", social=None):
        self.social = social              # com contas/amigos (servidores públicos); None = servidor privado simples
        self.port, self.host, self.log = port, host, log
        self.max_players, self.name = max_players, name
        self.lock = threading.RLock()
        self.conns = []
        self.next_id = 1
        self.running = False
        self.lsock = None

    # ---- ciclo de vida
    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))          # OSError se a porta estiver ocupada
        s.listen(16)
        self.lsock, self.running = s, True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._snap_loop, daemon=True).start()
        self.log(f"[obscurity] servidor ouvindo em {self.host}:{self.port}")
        return self

    def stop(self):
        self.running = False
        try:
            self.lsock.shutdown(socket.SHUT_RDWR)        # acorda o accept() para a porta fechar de verdade
        except Exception:
            pass
        try:
            self.lsock.close()
        except Exception:
            pass
        with self.lock:
            for c in list(self.conns):
                c.close()
            self.conns.clear()

    # ---- helpers
    def count(self):
        with self.lock:
            return sum(1 for c in self.conns if c.id is not None)

    def players(self):
        with self.lock:
            return [dict(id=c.id, n=c.name, h=c.hero, r=c.race, k=c.k, d=c.d, **c.st)
                    for c in self.conns if c.id is not None]

    def broadcast(self, obj, room=None, skip=None, droppable=False):
        with self.lock:
            targets = [c for c in self.conns if c.id is not None and c is not skip
                       and (room is None or c.st["room"] == room)]
        for c in targets:
            c.send(obj, droppable)

    def _drop(self, c):
        with self.lock:
            was = c in self.conns
            if was:
                self.conns.remove(c)
        c.close()
        if self.social is not None and c.ukey:
            self.social.logout(c, c.ukey)
        if was and c.id is not None:
            self.log(f"[obscurity] {c.name} (#{c.id}) saiu")
            self.broadcast({"t": "leave", "id": c.id, "n": c.name})

    # ---- threads
    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.lsock.accept()
            except OSError:
                break
            sock.settimeout(HELLO_TIMEOUT)               # até se apresentar; depois sobe para 30 s
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            c = _Conn(sock, addr)
            with self.lock:
                if sum(1 for o in self.conns if o.addr[0] == addr[0]) >= MAX_PER_IP:
                    refuse = True
                else:
                    refuse = False
                    self.conns.append(c)
            if refuse:                                    # IP abrindo conexões demais
                c.close()
                continue
            threading.Thread(target=self._writer, args=(c,), daemon=True).start()
            threading.Thread(target=self._reader, args=(c,), daemon=True).start()

    def _writer(self, c):
        try:
            while True:
                data = c.out.get()
                if data is None:
                    break
                c.sock.sendall(data)
        except OSError:
            pass
        self._drop(c)

    def _reader(self, c):
        buf = b""
        try:
            while c.alive:
                chunk = c.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_LINE and b"\n" not in buf:
                    break
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        m = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if isinstance(m, dict):
                        self._handle(c, m)
                        if not c.alive:
                            break
        except OSError:
            pass
        self._drop(c)

    def _snap_loop(self):
        while self.running:
            time.sleep(SNAP_DT)
            ps = self.players()
            if ps:
                self.broadcast({"t": "snap", "p": ps}, droppable=True)

    # ---- mensagens
    def _handle(self, c, m):
        t = m.get("t")
        if c.id is None and t == "info":              # consulta da lista de servidores (não ocupa vaga)
            c.send({"t": "info", "n": self.name or f"Servidor {self.port}", "p": self.count(), "max": self.max_players})
            return
        if c.id is None:
            if t != "hello":
                c.send({"t": "err", "msg": "esperava hello"})
                c.close()
                return
            if m.get("v") != PROTO:
                c.send({"t": "err", "msg": f"versão do protocolo incompatível (servidor {PROTO})"})
                c.close()
                return
            disp = None
            if self.social is not None:                  # servidor público: exige conta (nome de usuário único)
                ok, res = self.social.login(m.get("user"), m.get("tok"), c, self)
                if not ok:
                    c.send({"t": "err", "code": res[0], "msg": res[1]})
                    c.close()
                    return
                c.ukey = res
                disp = self.social.display(res)
            with self.lock:
                if sum(1 for o in self.conns if o.id is not None) >= self.max_players:
                    full = True
                else:
                    full = False
                    c.id = self.next_id
                    self.next_id += 1
            if full:
                c.send({"t": "err", "msg": "servidor cheio"})
                if c.ukey:
                    self.social.logout(c, c.ukey)
                    c.ukey = None
                c.close()
                return
            c.name = disp or _clean_text(m.get("name"), 12) or f"Jogador{c.id}"
            c.hero = m.get("hero") if m.get("hero") in HEROES_OK else "knight"
            c.race = m.get("race") if m.get("race") in RACES_OK else "human"
            c.sock.settimeout(30)
            c.send({"t": "welcome", "id": c.id, "proto": PROTO, "players": self.players()})
            if self.social is not None:
                c.send(self.social.payload(c.ukey))
            self.broadcast({"t": "join", "id": c.id, "n": c.name}, skip=c)
            self.log(f"[obscurity] {c.name} (#{c.id}) entrou de {c.addr[0]}")
            return

        if t in ("fr_add", "fr_acc", "fr_rej", "fr_del", "inv"):
            if self.social is not None and c.ukey:
                now = time.time()
                if now - getattr(c, "t_soc", 0.0) >= 0.3:       # anti-spam
                    c.t_soc = now
                    self.social.handle(c.ukey, m)
            return
        if t == "state":
            st = c.st
            room = m.get("room")
            st["room"] = room if room in ROOMS else "none"
            st["x"], st["y"] = _num(m.get("x"), -3, 25, 4.5), _num(m.get("y"), -3, 25, 4.5)
            st["hd"] = _num(m.get("hd"), -7, 7)
            st["mv"] = 1 if m.get("mv") else 0
            st["lg"] = _num(m.get("lg"), 0, 2)
            st["rl"] = _num(m.get("rl"), -1, 1.5, -1.0)
            st["dead"] = 1 if m.get("dead") else 0
            st["hp"] = int(_num(m.get("hp"), 0, 9999, 1))
            st["pm"] = int(_num(m.get("pm"), 1, 9999, 1))
        elif t in ("atk", "shot"):
            if c.st["room"] != "arena" or c.st["dead"]:
                return
            now = time.time()
            if now - c.t_atk < 0.10:                  # limite de cadência
                return
            c.t_atk = now
            out = {"t": t, "id": c.id,
                   "x": _num(m.get("x"), -3, 25), "y": _num(m.get("y"), -3, 25), "ang": _num(m.get("ang"), -7, 7),
                   "dmg": int(_num(m.get("dmg"), 0, 150)), "crit": 1 if m.get("crit") else 0}
            if t == "atk":
                out["reach"] = _num(m.get("reach"), 0, 4, 1.9)
                out["arc"] = _num(m.get("arc"), 0, 2, 1.15)
            else:
                out["kind"] = m.get("kind") if m.get("kind") in ("arrow", "bolt", "snipe", "fireball") else "arrow"
                out["spd"] = _num(m.get("spd"), 1, 30, 12)
                out["rng"] = _num(m.get("rng"), 1, 20, 10)
                out["pierce"] = 1 if m.get("pierce") else 0
            self.broadcast(out, room="arena", skip=c)
        elif t == "hurt":                              # a vítima avisa que tomou dano (feedback para todos)
            if c.st["room"] != "arena":
                return
            self.broadcast({"t": "hurt", "id": c.id, "by": int(_num(m.get("by"), 0, 10 ** 9)),
                            "dmg": int(_num(m.get("dmg"), 0, 150)), "crit": 1 if m.get("crit") else 0,
                            "x": _num(m.get("x"), -3, 25), "y": _num(m.get("y"), -3, 25)}, room="arena", skip=c)
        elif t == "died":
            if c.st["room"] != "arena":
                return
            if time.time() - c.t_died < 1.0:              # evita contar a mesma morte duas vezes
                return
            c.t_died = time.time()
            by = int(_num(m.get("by"), 0, 10 ** 9))
            c.d += 1
            killer = None
            with self.lock:
                for o in self.conns:
                    if o.id == by and o is not c:
                        o.k += 1
                        killer = o
            self.broadcast({"t": "kill", "by": by, "bn": killer.name if killer else "", "victim": c.id, "vn": c.name})
        elif t == "chat":
            txt = _clean_text(m.get("text"), 100)
            if txt:
                self.broadcast({"t": "chat", "id": c.id, "n": c.name, "text": txt})


# =================================================================== CLIENTE
class NetClient:
    """Conexão em thread. O jogo chama poll() a cada frame e send() quando quiser."""

    def __init__(self):
        self.sock = None
        self.inbox = queue.Queue()
        self.status = "idle"          # idle | connecting | connected | error | closed
        self.err = ""
        self.id = None
        self._gen = 0
        self._slock = threading.Lock()

    def connect(self, host, port, hello):
        self.close()
        self._gen += 1
        self.status, self.err, self.id = "connecting", "", None
        threading.Thread(target=self._run, args=(host, port, hello, self._gen), daemon=True).start()

    def _run(self, host, port, hello, gen):
        try:
            s = socket.create_connection((host, port), timeout=6)
        except Exception as e:
            if gen == self._gen:
                self.status, self.err = "error", f"Não foi possível conectar em {host}:{port} ({getattr(e, 'strerror', None) or e})"
            return
        s.settimeout(30)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        if gen != self._gen:
            s.close()
            return
        self.sock = s
        try:
            s.sendall(encode(hello))
            buf = b""
            while gen == self._gen:
                data = s.recv(8192)
                if not data:
                    raise ConnectionError("o servidor fechou a conexão")
                buf += data
                if len(buf) > 4 * MAX_LINE * 8:
                    raise ConnectionError("mensagem grande demais")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        m = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if not isinstance(m, dict):
                        continue
                    if m.get("t") == "welcome":
                        self.id, self.status = m.get("id"), "connected"
                    elif m.get("t") == "err":
                        self.err = str(m.get("msg", "erro do servidor"))
                    self.inbox.put(m)
        except socket.timeout:
            if gen == self._gen:
                self.err = self.err or "tempo esgotado (sem resposta do servidor)"
        except Exception as e:
            if gen == self._gen:
                self.err = self.err or str(e) or "conexão perdida"
        finally:
            if gen == self._gen:
                self.status = "closed" if self.status == "connected" else "error"
                self.err = self.err or "conexão encerrada"
            try:
                s.close()
            except OSError:
                pass

    def send(self, obj):
        s = self.sock
        if s is None or self.status not in ("connecting", "connected"):
            return False
        try:
            with self._slock:
                s.sendall(encode(obj))
            return True
        except OSError:
            self.status, self.err = "closed", self.err or "conexão perdida"
            return False

    def ping(self):
        return self.send({"t": "ping"})

    def poll(self):
        out = []
        try:
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            return out

    def close(self):
        self._gen += 1
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        self.status = "idle"
        try:
            while True:
                self.inbox.get_nowait()
        except queue.Empty:
            pass




def run_dedicated_server(argv):
    """python rpg.py --server [porta]  ->  servidor dedicado (sem abrir o jogo).
       python rpg.py --public          ->  os 3 servidores públicos 24h (é o que os jogadores acham sozinhos)."""
    def log(*a):
        print(time.strftime("[%d/%m %H:%M:%S]"), *a, flush=True)
    if "--public" in argv:
        srvs = {}
        for nm, pt in PUBLIC_SERVERS:
            try:
                srvs[pt] = Server(pt, max_players=PUBLIC_MAX, name=nm, log=log, social=get_social()).start()
            except OSError as e:
                print(f"Não foi possível abrir {nm} na porta {pt}: {e}")
        if not srvs:
            sys.exit(1)
        print(f"{len(srvs)} servidores públicos no ar ({PUBLIC_MAX} vagas cada). Libere as portas "
              + ", ".join(str(p) for p in srvs) + " TCP no firewall/roteador.")
        ok, ext, msg = upnp_open(list(srvs))
        print(f"UPnP: {msg}" + (f"  •  IP externo: {ext}" if ext else ""))
        print("Deixe este programa ligado o tempo todo. Ctrl+C para parar.")
        try:
            while True:
                time.sleep(5)
                for nm, pt in PUBLIC_SERVERS:             # se algum servidor cair, sobe de novo sozinho
                    sv = srvs.get(pt)
                    if sv is None or not sv.running:
                        try:
                            srvs[pt] = Server(pt, max_players=PUBLIC_MAX, name=nm, log=log, social=get_social()).start()
                            log(f"{nm} reiniciado")
                        except OSError:
                            pass
        except KeyboardInterrupt:
            for sv in srvs.values():
                sv.stop()
        return
    port = DEFAULT_PORT
    args = [x for x in argv[1:] if x.lstrip("-").isdigit()]
    if args:
        port = int(args[0])
    try:
        srv = Server(port, log=log).start()
    except OSError as e:
        print(f"Não foi possível abrir a porta {port}: {e}")
        sys.exit(1)
    print(f"Passe aos amigos:  {lan_ip()}:{port}   (na internet: libere/redirecione a porta {port} TCP no roteador)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


# =====================================================================================================
#  MULTIPLAYER (lobby no vilarejo + arena PvP). Usa as classes de rede acima.
#  LOBBY: todos aparecem andando no vilarejo; o poço leva à ARENA. ARENA: PvP (golpes, flechas, magias, rolagem).
#  Cada jogador calcula o próprio dano recebido (esquiva/bloqueio/vida) e o servidor só retransmite.
# =====================================================================================================
MP_SEED = 424242            # mesma semente para todos: vilarejo e arena iguais em todos os PCs
MP_RESPAWN = 3.0            # segundos até renascer na arena
MP_DMG_K = 3                # dano PvP = dmg_value() * multiplicador * MP_DMG_K
MP_SKILLS = {               # id -> ("atk", alcance, arco, mult, avanço) | ("shot", tipo, vel, alcance, mult)
    "investida": ("atk", 2.4, 0.7, 2.2, 1.6), "pancada_sismica": ("atk", 2.5, 2.0, 2.0, 0.0),
    "golpe_furtivo": ("atk", 1.7, 1.0, 2.0, 0.0), "cristais_gelo": ("atk", 2.6, 2.0, 1.7, 0.0),
    "tiro_preciso": ("shot", "snipe", 22.0, 16.0, 2.8), "bola_fogo": ("shot", "fireball", 9.0, 11.0, 2.4),
}


class MPMixin:
    # ------------------------------------------------------------------ estado
    def mp_init(self):
        self.mp_net, self.mp_server, self.mp_on = None, None, False
        self.mp_room, self.mp_arena = "lobby", False
        self.mp_players, self.mp_me = {}, None
        self.mp_chat, self.mp_feed, self.mp_typing = [], [], None
        self.mp_hp = self.mp_maxhp = 100
        self.mp_dead, self.mp_dead_t = False, 0.0
        self.mp_k = self.mp_d = 0
        self.mp_send_t, self.mp_lock = 0.0, None
        self.mp_lan = lan_ip()
        self.mp_m = dict(sel=0, slot=None, addr=self.cfg.get("mp_addr") or f"127.0.0.1:{DEFAULT_PORT}", msg="", busy=False,
                         queue=[], pub_t=0.0)
        self.mp_pub_busy = False
        self._pub_remote = ""
        self.fr = {"f": [], "in": [], "out": []}
        self.fr_open, self.fr_tab, self.fr_sel, self.fr_input = False, 0, 0, ""
        self.fr_inv, self.fr_note, self.fr_note_t = [], "", 0.0
        self.mp_cur = None
        self.us_text, self.us_msg = "", ""
        self.mp_pub = [dict(name=n, host=self.mp_pub_host(), port=pt, ok=None, p=0, max=PUBLIC_MAX) for n, pt in PUBLIC_SERVERS]

    def mp_pub_host(self):
        """Host dos servidores públicos: manual (cfg) > arquivo remoto > último que funcionou > PUBLIC_HOST."""
        if getattr(self, "auto_host", None) is not None:      # este PC é o servidor: conecta direto em si mesmo
            return "127.0.0.1"
        for h in (self.cfg.get("public_host"), self._pub_remote, self.cfg.get("public_host_last"), PUBLIC_HOST):
            if h and h.strip():
                return h.strip()
        return PUBLIC_HOST

    def mp_pub_refresh(self):
        """Atualiza (em thread) quantos jogadores há em cada servidor público."""
        if self.mp_pub_busy:
            return
        self.mp_pub_busy = True

        def work():
            try:
                if PUBLIC_HOST_URL and not self.cfg.get("public_host"):
                    self._pub_remote = fetch_public_host(PUBLIC_HOST_URL) or self._pub_remote
                host = self.mp_pub_host()
                res = [None] * len(PUBLIC_SERVERS)

                def one(i, pt):
                    res[i] = query_server(host, pt)
                ths = [threading.Thread(target=one, args=(i, pt), daemon=True) for i, (_, pt) in enumerate(PUBLIC_SERVERS)]
                for th in ths:
                    th.start()
                for th in ths:
                    th.join()
                self.mp_pub = [dict(name=n, host=host, port=pt, ok=r is not None, p=r["p"] if r else 0,
                                    max=r["max"] if r else PUBLIC_MAX)
                               for (n, pt), r in zip(PUBLIC_SERVERS, res)]
                self.mp_pub_done = True
                if any(r is not None for r in res) and host not in PUBLIC_LOCAL and self.cfg.get("public_host_last") != host:
                    self.cfg["public_host_last"] = host        # lembra o último host que respondeu
                    save_cfg(self.cfg)
            finally:
                self.mp_pub_busy = False
        threading.Thread(target=work, daemon=True).start()

    def mp_visible(self):
        return [q for q in self.mp_players.values() if q.get("room") == self.mp_room and not q.get("dead")]

    def mp_foes(self):
        return [q for q in self.mp_players.values() if q.get("room") == "arena" and not q.get("dead")]

    # ------------------------------------------------------------------ menu MULTIPLAYER
    def mp_rects(self):
        """Linhas selecionáveis (como os slots de save): 0-2 servidores públicos, 3 endereço manual, 4 hospedar."""
        return dict(char=pygame.Rect(130, 146, W - 260, 38),
                    rows=[pygame.Rect(130, 190 + i * 62, W - 260, 54) for i in range(5)],
                    back=pygame.Rect(40, 528, 150, 44), quick=pygame.Rect(W - 40 - 190, 528, 190, 44))

    def open_username(self, msg="", nxt="mp"):
        self.us_text, self.us_msg, self.us_next = "", msg, nxt
        self.phase = "username"

    def username_key(self, key, uni):
        if key == pygame.K_ESCAPE:
            self.phase = "title"
        elif key == pygame.K_BACKSPACE:
            self.us_text = self.us_text[:-1]
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.username_confirm()
        elif uni and len(self.us_text) < USER_MAX and uni.isascii() and (uni.isalnum() or uni == "_"):
            self.us_text += uni

    def username_confirm(self):
        u = self.us_text.strip()
        if not valid_user(u):
            self.us_msg = f"Use de {USER_MIN} a {USER_MAX} letras, números ou _ (sem espaço)."
            self.play("bad")
            return
        import secrets
        self.cfg["username"] = u
        if len(self.cfg.get("token", "")) < 16:
            self.cfg["token"] = secrets.token_hex(16)
        save_cfg(self.cfg)
        self.play("card")
        if getattr(self, "us_next", "mp") == "title":
            self.phase = "title"
        else:
            self.mp_open_menu()

    def username_click(self, pos):
        r = pygame.Rect(0, 0, 220, 46)
        r.center = (W // 2, 440)
        if r.collidepoint(pos):
            self.username_confirm()

    def draw_username(self):
        scr = self.screen
        box = pygame.Rect(0, 0, 600, 300)
        box.center = (W // 2, 360)
        self.rrect(box, (14, 12, 20, 235), 18, 3, (200, 150, 90, 255))
        self.otext("ESCOLHA SEU NOME DE USUÁRIO", 30, (255, 232, 150), (W // 2, box.y + 40), ow=2)
        self.text("Ele é único, só seu, e fica salvo. Seus amigos vão te achar por ele.", 19, (210, 206, 220), (W // 2, box.y + 84), shadow=False)
        fld = pygame.Rect(0, 0, 360, 54)
        fld.center = (W // 2, box.y + 150)
        self.rrect(fld, (8, 8, 14, 255), 10, 3, (150, 165, 230, 255))
        self.text(self.us_text + ("|" if int(self.t * 2) % 2 == 0 else " "), 32, (255, 255, 255), fld.center, shadow=False)
        if self.us_msg:
            self.text(self.us_msg, 19, (255, 150, 140), (W // 2, box.y + 200), shadow=False)
        else:
            self.text(f"{USER_MIN} a {USER_MAX} caracteres: letras, números ou _", 17, (150, 146, 160), (W // 2, box.y + 200), shadow=False)
        b = pygame.Rect(0, 0, 220, 46)
        b.center = (W // 2, 440)
        self.small_btn(b, "CONFIRMAR")
        self.draw_keybar(597, (("ENTER", "confirmar"), ("ESC", "voltar")))

    def mp_open_menu(self):
        if not self.cfg.get("username"):
            self.open_username()
            return
        m = self.mp_m
        filled = [i for i, sv in enumerate(self.saves) if sv]
        if m["slot"] is None or m["slot"] not in filled:
            m["slot"] = self.slot if (self.slot in filled) else (filled[0] if filled else None)
        m["msg"], m["busy"], m["sel"], m["queue"], m["pub_t"] = "", False, 0, [], 0.0
        self.mp_pub_done = False
        m["auto"] = m["slot"] is not None                  # entra sozinho no melhor servidor (qualquer tecla cancela)
        if m["auto"]:
            m["msg"] = "Procurando servidor...  (↑ ↓ para escolher manualmente)"
        self.phase = "mp_menu"

    def mp_cycle_slot(self, d):
        filled = [i for i, sv in enumerate(self.saves) if sv]
        if not filled:
            return
        cur = self.mp_m["slot"]
        k = filled.index(cur) if cur in filled else 0
        self.mp_m["slot"] = filled[(k + d) % len(filled)]
        self.play("card")

    def mpmenu_key(self, key, uni):
        m = self.mp_m
        if m.get("auto"):                                     # qualquer tecla cancela a entrada automática
            m["auto"] = False
            if m["msg"].startswith("Procurando"):
                m["msg"] = ""
        if key == pygame.K_ESCAPE:
            m["queue"] = []
            self.mp_cancel()
            self.phase = "title"
        elif key == pygame.K_UP:
            m["sel"] = (m["sel"] - 1) % 5
        elif key in (pygame.K_DOWN, pygame.K_TAB):
            m["sel"] = (m["sel"] + 1) % 5
        elif key == pygame.K_LEFT:
            self.mp_cycle_slot(-1)
        elif key == pygame.K_RIGHT:
            self.mp_cycle_slot(+1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.mp_activate(m["sel"])
        elif key in (pygame.K_F1, pygame.K_F2, pygame.K_F3):
            self.mp_join_public(key - pygame.K_F1)
        elif m["sel"] == 3:                                   # na linha de endereço dá para digitar o ip:porta
            if key == pygame.K_BACKSPACE:
                m["addr"] = m["addr"][:-1]
            elif uni and uni in MP_ADDR_CHARS and len(m["addr"]) < 60:
                m["addr"] += uni
        elif key == pygame.K_q:                               # atalho: entrada rápida
            self.mp_activate(5)

    def mp_menu_click(self, pos):
        self.mp_m["auto"] = False
        R = self.mp_rects()
        if R["back"].collidepoint(pos):
            self.mp_activate(6)
            return
        if R["quick"].collidepoint(pos):
            self.mp_activate(5)
            return
        for i, r in enumerate(R["rows"]):
            if r.collidepoint(pos):
                self.mp_m["sel"] = i
                self.mp_activate(i)
                return
        if R["char"].collidepoint(pos):
            self.mp_cycle_slot(-1 if pos[0] < R["char"].centerx else +1)

    def mp_cancel(self):
        if self.mp_net is not None:
            self.mp_net.close()
            self.mp_net = None
        if self.mp_server is not None:
            self.mp_server.stop()
            self.mp_server = None
        self.mp_m["busy"] = False

    def mp_connect(self, host, port, msg):
        """Abre a conexão com o personagem escolhido. (Quem chama já fez mp_cancel.)"""
        m = self.mp_m
        sv = self.saves[m["slot"]]
        user, tok = self.cfg.get("username", ""), self.cfg.get("token", "")
        hello = {"t": "hello", "v": PROTO, "name": user or sv["name"], "user": user, "tok": tok,
                 "hero": sv["hero"], "race": sv.get("race", "human")}
        self.mp_cur = (host, port)
        self.mp_net = NetClient()
        self.mp_net.connect(host, port, hello)
        m["busy"], m["msg"] = True, msg

    def mp_join_public(self, i):
        """Entra direto no servidor público i (clique na lista ou F1/F2/F3)."""
        m = self.mp_m
        if m["busy"] or not (0 <= i < len(self.mp_pub)):
            return
        if m["slot"] is None:
            m["msg"] = "Crie um personagem primeiro (CRIAR SAVE)."
            self.play("bad")
            return
        sv_ = self.mp_pub[i]
        if sv_["ok"] is False:
            m["msg"] = f"{sv_['name']} está offline."
            self.play("bad")
            return
        if sv_["ok"] and sv_["p"] >= sv_["max"]:
            m["msg"] = f"{sv_['name']} está cheio ({sv_['p']}/{sv_['max']})."
            self.play("bad")
            return
        m["queue"] = []
        self.mp_cancel()
        self.mp_connect(sv_["host"], sv_["port"], f"Entrando em {sv_['name']} ...")

    def mp_quick_join(self):
        """ENTRAR RÁPIDO: vai no servidor público com vaga que já tem mais gente; se falhar, tenta o próximo."""
        m = self.mp_m
        cand = [x for x in self.mp_pub if x["ok"] is not False and x["p"] < x["max"]]
        if not cand:
            m["msg"] = "Nenhum servidor público com vaga agora. Tente de novo em instantes."
            self.play("bad")
            self.mp_pub_refresh()
            return
        cand.sort(key=lambda x: -x["p"])
        m["queue"] = cand[1:]
        self.mp_cancel()
        self.mp_connect(cand[0]["host"], cand[0]["port"], f"Entrando em {cand[0]['name']} ...")

    def mp_activate(self, i):
        """0-2 servidor público | 3 entrar por endereço | 4 hospedar aqui | 5 entrada rápida | 6 voltar"""
        m = self.mp_m
        if i == 6:
            m["queue"] = []
            self.mp_cancel()
            self.phase = "title"
            return
        if m["busy"]:
            return
        if i < 3:
            self.mp_join_public(i)
            return
        if m["slot"] is None:
            m["msg"] = "Crie um personagem primeiro (CRIAR SAVE)."
            self.play("bad")
            return
        if i == 5:
            self.mp_quick_join()
            return
        try:
            host, port = parse_addr(m["addr"])
        except ValueError:
            m["msg"] = "Endereço inválido. Use ip:porta (ex.: 192.168.0.10:5555)."
            self.play("bad")
            return
        m["queue"] = []
        self.mp_cancel()
        if i == 4:                                   # HOSPEDAR AQUI
            try:
                self.mp_server = Server(port, log=lambda *a: None).start()
            except OSError as e:
                m["msg"] = f"Não foi possível abrir a porta {port}: {getattr(e, 'strerror', None) or e}"
                self.play("bad")
                return
            host = "127.0.0.1"
        self.mp_connect(host, port, "Servidor aberto! Conectando..." if i == 4 else f"Conectando em {host}:{port} ...")
        self.cfg["mp_addr"] = m["addr"]
        save_cfg(self.cfg)

    def mpmenu_tick(self, dt):
        m = self.mp_m
        if self.phase == "mp_menu" and not m["busy"]:
            m["pub_t"] -= dt
            if m["pub_t"] <= 0:
                m["pub_t"] = 3.0 if not m.get("auto") else 0.6
                self.mp_pub_refresh()
            if m.get("auto") and getattr(self, "mp_pub_done", False) and not self.mp_pub_busy:
                m["auto"] = False
                if any(x["ok"] and x["p"] < x["max"] for x in self.mp_pub):
                    self.mp_quick_join()
                else:
                    host = self.mp_pub_host()
                    if all(x["ok"] is False for x in self.mp_pub):
                        m["msg"] = ("Servidor público não configurado (PUBLIC_HOST no código)." if host in PUBLIC_LOCAL
                                    else "Servidores públicos offline agora. Tente de novo ou use HOSPEDAR AQUI.")
                    else:
                        m["msg"] = "Todos os servidores públicos estão cheios. Tente de novo em instantes."
                    self.play("bad")
        if self.mp_net is None:
            return
        for msg in self.mp_net.poll():
            t = msg.get("t")
            if t == "welcome" and self.phase == "mp_menu":
                self.mp_begin(msg)
            elif t == "err":
                m["msg"] = str(msg.get("msg", "erro do servidor"))
                if msg.get("code") in ("name_taken", "bad_name", "bad_tok"):
                    self.cfg["username"] = ""
                    save_cfg(self.cfg)
                    self.mp_cancel()
                    self.open_username(m["msg"])
                    return
            else:
                self.mp_handle(msg)
        if self.phase == "mp_menu" and self.mp_net is not None and self.mp_net.status in ("error", "closed"):
            err = self.mp_net.err or "Falha na conexão."
            self.mp_cancel()
            if m["queue"]:                           # entrada rápida: tenta o próximo servidor com vaga
                nx = m["queue"].pop(0)
                self.mp_connect(nx["host"], nx["port"], f"{err}  Tentando {nx['name']} ...")
                return
            m["msg"] = err
            m["pub_t"] = 0.0
            self.play("bad")

    def draw_mpmenu(self):
        scr, m = self.screen, self.mp_m
        R = self.mp_rects()
        if getattr(self, "auto_host", None) is not None:
            self.text(self.auto_host.info, 17, (150, 220, 150), (14, 12), center=False, shadow=False)
        pulse = 0.5 + 0.5 * math.sin(self.t * 4)
        self.otext("ESCOLHA UM SERVIDOR", 32, (255, 232, 150), (W // 2, 118), ow=2)
        # personagem (◄ ►)
        sv = self.saves[m["slot"]] if m["slot"] is not None else None
        self.chunky(R["char"], (24, 17, 14), None, 12, 3, 3)
        if sv:
            hn = next((h["name"] for h in HEROES if h["id"] == sv["hero"]), sv["hero"])
            self.text(f"◄   {sv['name']}  •  {hn}   ►", 24, (255, 255, 255), R["char"].center, shadow=False)
        else:
            self.text("Crie um personagem primeiro (CRIAR SAVE)", 22, (255, 150, 140), R["char"].center, shadow=False)

        for i, r in enumerate(R["rows"]):
            sel = m["sel"] == i
            if i < 3:
                ps = self.mp_pub[i]
                off = ps["ok"] is False
                full = bool(ps["ok"]) and ps["p"] >= ps["max"]
                col = (120, 112, 104) if off else ((230, 110, 100) if full else (150, 220, 150))
            else:
                ps, off, full, col = None, False, False, (230, 170, 90)
            if sel:
                self.rrect(r.inflate(16, 16), (*col, 46), 24)
            self.chunky(r, (24, 17, 14) if sel else (10, 8, 8), None, 16, 4, 5 if sel else 3, alpha=240 if sel else 210)
            if sel:
                pygame.draw.rect(scr, mix(col, 0.3 * pulse), r, 3, border_radius=16)
            badge = pygame.Rect(r.x + 10, r.y + 8, 38, 38)
            self.chunky(badge, shade(col, 0.7), None, 10, 3, 2)
            self.otext(str(i + 1), 28, (255, 255, 255), badge.center, ow=2)
            if ps is not None:
                self.otext(ps["name"], 30, (190, 184, 178) if off else (255, 255, 255), (r.x + 66, r.y + 4), ow=2, center=False)
                if off:
                    sub = "OFFLINE"
                elif ps["ok"] is None:
                    sub = "verificando..."
                elif full:
                    sub = f"CHEIO  •  {ps['p']}/{ps['max']} jogadores"
                else:
                    sub = f"{ps['max'] - ps['p']} vaga(s) livre(s)  •  {ps['p']}/{ps['max']} jogadores"
                self.text(sub, 19, mix(col, 0.35), (r.x + 68, r.y + 34), center=False, shadow=False)
                if not off and ps["ok"] is not None:
                    dw = ps["max"] * 16
                    for k in range(ps["max"]):
                        dr = pygame.Rect(r.right - 20 - dw + k * 16, r.centery - 9, 12, 18)
                        pygame.draw.rect(scr, col if k < ps["p"] else (58, 46, 40), dr, border_radius=3)
                if sel and not off and not full and ps["ok"] is not None:
                    hint = "ENTER: entrar"
                    self.text(hint, 20, (255, 226, 130), (r.right - 20 - ps["max"] * 16 - 16 - self.font(20).size(hint)[0], r.centery), center=False, shadow=False)
            elif i == 3:
                self.otext("ENTRAR POR ENDEREÇO", 30, (255, 255, 255), (r.x + 66, r.y + 4), ow=2, center=False)
                caret = "|" if (sel and int(self.t * 2) % 2 == 0) else " "
                self.text(m["addr"] + caret, 20, (255, 236, 200) if sel else (170, 160, 148), (r.x + 68, r.y + 34), center=False, shadow=False)
                if sel:
                    hint = "digite ip:porta  •  ENTER"
                    self.text(hint, 20, (255, 226, 130), (r.right - 20 - self.font(20).size(hint)[0], r.centery), center=False, shadow=False)
            else:
                self.otext("HOSPEDAR AQUI", 30, (255, 255, 255), (r.x + 66, r.y + 4), ow=2, center=False)
                self.text(f"Abre o servidor neste PC  •  IP na rede: {self.mp_lan}", 19, mix(col, 0.35), (r.x + 68, r.y + 34), center=False, shadow=False)
                if sel:
                    hint = "ENTER: hospedar"
                    self.text(hint, 20, (255, 226, 130), (r.right - 20 - self.font(20).size(hint)[0], r.centery), center=False, shadow=False)
        if m["msg"]:
            self.otext(m["msg"], 21, (255, 214, 140) if m["busy"] else (255, 140, 130), (W // 2, 514), ow=2)
        self.small_btn(R["back"], "VOLTAR")
        self.small_btn(R["quick"], "RÁPIDO (Q)", (104, 38, 10), (200, 120, 50))
        self.draw_keybar(597, (("↑ ↓", "servidor"), ("◄ ►", "personagem"), ("ENTER", "entrar"), ("Q", "rápido"), ("ESC", "voltar")))

    # ------------------------------------------------------------------ entrar / sair
    def mp_begin(self, welcome):
        i = self.mp_m["slot"]
        sv = self.saves[i]
        ids = [h["id"] for h in HEROES]
        self.slot = i
        self.hero_index = ids.index(sv["hero"]) if sv["hero"] in ids else 0
        self.best = max(1, sv.get("best", 1))
        self.forced_seed = MP_SEED
        self.new_run()                                  # monta o vilarejo (igual para todos)
        self.mp_on, self.mp_me = True, welcome.get("id")
        self.mp_players = {}
        for p in welcome.get("players", []):
            self.mp_upsert(p)
        self.mp_chat, self.mp_feed, self.mp_typing = [], [], None
        self.mp_k = self.mp_d = 0
        self.mp_m["queue"] = []
        self.mp_maxhp = 60 + 20 * self.maxhp
        self.mp_lobby(first=True)
        self.mp_m["busy"] = False
        self.play("card")

    def mp_leave(self, msg="", phase="title"):
        self.mp_cancel()
        was = self.mp_on
        self.mp_on, self.mp_arena, self.mp_players, self.mp_typing = False, False, {}, None
        self.smith_open = self.mk_open = self.inv_open = False
        if was:
            self.save_progress()
        self.new_run(title=True)                        # volta ao cenário normal do jogo solo
        self.shots, self.particles, self.floaters = [], [], []
        self.banner, self.banner_t = "", 0.0
        if phase == "mp_menu":
            self.phase = "mp_menu"
        else:
            self.phase = "title"
        self.mp_m["msg"], self.mp_m["busy"] = msg, False

    def mp_lobby(self, first=False):
        self.mp_arena, self.mp_room = False, "lobby"
        if not first:
            self.village, self.floor = True, 1
            self.new_floor()
        self.stairs = self.lay["stairs"]
        if not first:
            self.px, self.py = push_out(8.6, 8.9, HERO_R, self.solids)
        self.pz, self.pscale = ground(self.px, self.py, self.duplo), 1.0
        self.phase = "mp"
        self.mp_dead, self.mp_hp = False, self.mp_maxhp
        self.smith_done = self.market_done = True
        self.moving, self.inbuf, self.mp_lock = False, None, None
        self.banner, self.banner_t = "LOBBY  -  entre no poço para a ARENA PvP", 4.0
        self.mp_send_state(force=True)

    def mp_go_arena(self):
        self.mp_arena, self.mp_room = True, "arena"
        self.village, self.floor = False, 1
        self.new_floor()
        self.stairs = None
        self.px, self.py = self.mp_pick_spawn()
        self.pz, self.pscale = ground(self.px, self.py, self.duplo), 1.0
        self.phase = "mp"
        self.mp_dead, self.mp_hp, self.mp_lock = False, self.mp_maxhp, None
        self.inv_t = 1.5
        self.banner, self.banner_t = "ARENA PvP  -  [B] volta ao lobby", 3.5
        self.play("fall")
        self.mp_send_state(force=True)

    def mp_arena_lay(self):
        lay = None
        for s in range(MP_SEED, MP_SEED + 300):
            lay = gen_floor(2, random.Random(s), {}, [])
            if lay["room"] == "normal" and not lay["duplo"] and not lay["water"] and not lay.get("tunnel"):
                break
        lay = dict(lay)
        lay["foes"], lay["banner"] = [], "ARENA PvP"
        return lay

    def mp_pick_spawn(self):
        others = [(q["dx"], q["dy"]) for q in self.mp_foes()]
        cands = [(i + 0.5, j + 0.5) for i in range(N) for j in range(N)
                 if (i, j) not in self.blocked and not circle_hits(i + 0.5, j + 0.5, HERO_R + 0.12, self.solids)]
        if not cands:
            return self.lay["spawn"]
        if not others:
            return random.choice(cands)
        return max(cands, key=lambda c: min(math.hypot(c[0] - o[0], c[1] - o[1]) for o in others) + random.random() * 0.8)

    def mp_respawn(self):
        self.px, self.py = self.mp_pick_spawn()
        self.pz, self.pscale = ground(self.px, self.py, self.duplo), 1.0
        self.mp_hp, self.mp_dead = self.mp_maxhp, False
        self.stam, self.inv_t, self.hurt_t = self.STAM_MAX, 1.5, 0.0
        self.mp_send_state(force=True)

    # ------------------------------------------------------------------ rede
    def mp_upsert(self, p):
        pid = p.get("id")
        if pid is None or pid == self.mp_me:
            return
        q = self.mp_players.get(pid)
        if q is None:
            q = {"dx": p.get("x", 4.5), "dy": p.get("y", 4.5), "dhd": p.get("hd", 0.0), "flash": 0.0}
            self.mp_players[pid] = q
        if q.get("room") != p.get("room"):
            q["dx"], q["dy"] = p.get("x", q["dx"]), p.get("y", q["dy"])
        q.update(p)

    def mp_poll(self):
        if self.mp_net is None:
            return
        for m in self.mp_net.poll():
            self.mp_handle(m)
            if not self.mp_on:
                return
        if self.mp_net is not None and self.mp_net.status in ("closed", "error"):
            self.mp_leave(self.mp_net.err or "Conexão perdida.", "mp_menu")

    def mp_say(self, text):
        self.mp_feed.append((self.t, text))
        self.mp_feed = self.mp_feed[-6:]

    def mp_handle(self, m):
        t = m.get("t")
        if t == "snap":
            ids = set()
            for p in m.get("p", []):
                ids.add(p.get("id"))
                if p.get("id") == self.mp_me:
                    self.mp_k, self.mp_d = p.get("k", 0), p.get("d", 0)
                else:
                    self.mp_upsert(p)
            for pid in list(self.mp_players):
                if pid not in ids:
                    del self.mp_players[pid]
        elif t == "join":
            self.mp_say(f"{m.get('n', '?')} entrou")
        elif t == "leave":
            self.mp_players.pop(m.get("id"), None)
            self.mp_say(f"{m.get('n', '?')} saiu")
        elif t == "chat":
            self.mp_chat.append((self.t, m.get("n", "?"), m.get("text", "")))
            self.mp_chat = self.mp_chat[-40:]
        elif t == "atk":
            self.mp_on_atk(m)
        elif t == "shot":
            self.mp_on_shot(m)
        elif t == "hurt":
            self.mp_on_hurt(m)
        elif t == "kill":
            self.mp_on_kill(m)
        elif t == "fl":
            self.fr = {"f": m.get("f", []), "in": m.get("in", []), "out": m.get("out", [])}
            self.fr_sel = max(0, min(self.fr_sel, max(0, self.fr_len() - 1)))
        elif t == "note":
            self.fr_note, self.fr_note_t = str(m.get("msg", ""))[:90], self.t + 5.0
            self.mp_say(self.fr_note)
        elif t == "inv":
            who = str(m.get("from", "?"))[:12]
            self.fr_inv = [i for i in self.fr_inv if i["from"] != who][-3:] + [
                {"from": who, "s": str(m.get("s", "")), "p": int(_num(m.get("p"), 0, 65535, 0)), "until": self.t + 25.0}]
            self.play("card")
        elif t == "err":
            self.mp_say(str(m.get("msg", "erro")))

    # ------------------------------------------------------------------ AMIGOS / CONVITES
    FR_TABS = ("AMIGOS", "PEDIDOS", "ADICIONAR")

    def fr_len(self):
        return len(self.fr["f"]) if self.fr_tab == 0 else (len(self.fr["in"]) if self.fr_tab == 1 else 0)

    def fr_send(self, obj):
        if self.mp_net is not None:
            self.mp_net.send(obj)

    def fr_rects(self):
        box = pygame.Rect(0, 0, 560, 430)
        box.center = (W // 2, H // 2)
        return dict(box=box,
                    tabs=[pygame.Rect(box.x + 18 + i * 172, box.y + 44, 166, 34) for i in range(3)],
                    rows=[pygame.Rect(box.x + 18, box.y + 92 + i * 40, box.w - 36, 36) for i in range(6)],
                    act=pygame.Rect(box.x + 18, box.bottom - 56, 250, 40),
                    alt=pygame.Rect(box.x + 282, box.bottom - 56, 260, 40),
                    hud=pygame.Rect(W - 236, 176, 224, 28),
                    inv_yes=pygame.Rect(W // 2 - 190, 78, 180, 34), inv_no=pygame.Rect(W // 2 + 10, 78, 180, 34))

    def fr_toggle(self, on=None):
        self.fr_open = (not self.fr_open) if on is None else on
        self.fr_input = ""
        self.fr_sel = 0
        self.play("card")

    def fr_join(self, port, name):
        """Vai para o servidor onde o amigo está (ou aceita o convite dele)."""
        if not port:
            return
        cur = self.mp_cur
        if cur is not None and cur[1] == port:
            self.fr_note, self.fr_note_t = f"Você já está no mesmo servidor de {name}.", self.t + 4.0
            return
        host = cur[0] if cur else self.mp_pub_host()
        self.fr_open = False
        self.mp_leave("", "mp_menu")
        self.mp_m["auto"], self.mp_m["queue"] = False, []
        self.mp_connect(host, port, f"Entrando no servidor de {name} ...")

    def fr_action(self, primary=True):
        tab, sel = self.fr_tab, self.fr_sel
        if tab == 0 and 0 <= sel < len(self.fr["f"]):
            f = self.fr["f"][sel]
            if primary:
                if f["on"]:
                    self.fr_send({"t": "inv", "u": f["u"]})
                else:
                    self.fr_note, self.fr_note_t = f"{f['u']} está offline.", self.t + 3.0
            else:
                self.fr_send({"t": "fr_del", "u": f["u"]})
        elif tab == 1 and 0 <= sel < len(self.fr["in"]):
            self.fr_send({"t": "fr_acc" if primary else "fr_rej", "u": self.fr["in"][sel]})
        elif tab == 2 and primary and self.fr_input.strip():
            self.fr_send({"t": "fr_add", "u": self.fr_input.strip()})
            self.fr_input = ""

    def fr_join_selected(self):
        if self.fr_tab == 0 and 0 <= self.fr_sel < len(self.fr["f"]):
            f = self.fr["f"][self.fr_sel]
            if f["on"]:
                self.fr_join(f["p"], f["u"])

    def fr_key(self, key, uni):
        if key in (pygame.K_ESCAPE, pygame.K_TAB):
            self.fr_toggle(False)
        elif key == pygame.K_LEFT and not (self.fr_tab == 2 and self.fr_input):
            self.fr_tab, self.fr_sel = (self.fr_tab - 1) % 3, 0
        elif key == pygame.K_RIGHT and not (self.fr_tab == 2 and self.fr_input):
            self.fr_tab, self.fr_sel = (self.fr_tab + 1) % 3, 0
        elif key == pygame.K_UP:
            self.fr_sel = max(0, self.fr_sel - 1)
        elif key == pygame.K_DOWN:
            self.fr_sel = min(max(0, self.fr_len() - 1), self.fr_sel + 1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.fr_action(True)
        elif self.fr_tab == 2:
            if key == pygame.K_BACKSPACE:
                self.fr_input = self.fr_input[:-1]
            elif uni and len(self.fr_input) < USER_MAX and (uni.isalnum() or uni == "_") and uni.isascii():
                self.fr_input += uni
        elif key == pygame.K_j:
            self.fr_join_selected()
        elif key in (pygame.K_DELETE, pygame.K_x):
            self.fr_action(False)
        elif key == pygame.K_a and self.fr_tab == 1:
            self.fr_action(True)
        elif key == pygame.K_r and self.fr_tab == 1:
            self.fr_action(False)
        elif key == pygame.K_i and self.fr_tab == 0:
            self.fr_action(True)

    def fr_click(self, pos):
        R = self.fr_rects()
        if not R["box"].collidepoint(pos):
            self.fr_toggle(False)
            return
        for i, r in enumerate(R["tabs"]):
            if r.collidepoint(pos):
                self.fr_tab, self.fr_sel = i, 0
                return
        for i, r in enumerate(R["rows"]):
            if r.collidepoint(pos) and i < self.fr_len():
                self.fr_sel = i
                return
        if R["act"].collidepoint(pos):
            self.fr_action(True)
        elif R["alt"].collidepoint(pos):
            if self.fr_tab == 0:
                self.fr_join_selected()
            else:
                self.fr_action(False)

    def fr_invite_answer(self, yes):
        if not self.fr_inv:
            return
        inv = self.fr_inv.pop(0)
        if yes:
            self.fr_join(inv["p"], inv["from"])

    def draw_friends_hud(self):
        """Botão AMIGOS, aviso de convite recebido e painel de amigos."""
        scr, R = self.screen, self.fr_rects()
        self.fr_inv = [i for i in self.fr_inv if i["until"] > self.t]
        pend = len(self.fr["in"])
        r = R["hud"]
        if self.mp_room == "lobby":
            self.rrect(r, (10, 8, 14, 190), 10, 2, (110, 150, 110, 255))
            self.text("AMIGOS (TAB)" + (f"  •  {pend} pedido(s)" if pend else ""), 16, (170, 235, 170), r.center, shadow=False)
        if self.fr_inv:
            inv = self.fr_inv[0]
            bx = pygame.Rect(W // 2 - 220, 44, 440, 76)
            self.rrect(bx, (14, 20, 14, 240), 12, 3, (120, 220, 130, 255))
            self.text(f"{inv['from']} convidou você para jogar junto!", 20, (240, 255, 240), (bx.centerx, bx.y + 14), shadow=False)
            for rr, lab, col in ((R["inv_yes"], "ACEITAR (Y)", (60, 150, 70)), (R["inv_no"], "RECUSAR (N)", (150, 60, 60))):
                self.rrect(rr, col + (255,), 8, 2, (240, 240, 240, 255))
                self.text(lab, 18, (255, 255, 255), rr.center, shadow=False)
        if self.fr_note and self.t < self.fr_note_t and not self.fr_open:
            self.otext(self.fr_note, 20, (200, 245, 200), (W // 2, 150 if self.fr_inv else 56), ow=2)
        if not self.fr_open:
            return
        box = R["box"]
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 120))
        scr.blit(dim, (0, 0))
        self.rrect(box, (14, 12, 20, 245), 16, 3, (120, 150, 120, 255))
        me = self.cfg.get("username") or "?"
        self.text(f"AMIGOS  •  você é  {me}", 24, (255, 236, 170), (box.centerx, box.y + 22), shadow=False)
        for i, tr in enumerate(R["tabs"]):
            on = i == self.fr_tab
            self.rrect(tr, (60, 90, 60, 255) if on else (28, 26, 34, 255), 8, 2, (150, 220, 150, 255) if on else (70, 66, 80, 255))
            lab = self.FR_TABS[i] + (f" ({pend})" if i == 1 and pend else "")
            self.text(lab, 18, (255, 255, 255) if on else (170, 166, 180), tr.center, shadow=False)
        rows = R["rows"]
        if self.fr_tab == 0:
            lst = self.fr["f"]
            if not lst:
                self.text("Nenhum amigo ainda. Use a aba ADICIONAR.", 19, (190, 186, 200), (box.centerx, box.y + 180), shadow=False)
            for i, f in enumerate(lst[:6]):
                rr = rows[i]
                self.rrect(rr, (40, 56, 40, 255) if i == self.fr_sel else (24, 22, 30, 255), 8, 2,
                           (150, 220, 150, 255) if i == self.fr_sel else (60, 56, 70, 255))
                pygame.draw.circle(scr, (90, 220, 110) if f["on"] else (100, 96, 104), (rr.x + 16, rr.centery), 6)
                self.text(f["u"], 21, (255, 255, 255) if f["on"] else (150, 146, 156), (rr.x + 32, rr.centery), center=False, shadow=False)
                self.text(f["s"] if f["on"] else "offline", 17, (170, 220, 170) if f["on"] else (120, 116, 126),
                          (rr.right - 12 - self.font(17).size(f["s"] if f["on"] else "offline")[0], rr.centery), center=False, shadow=False)
            a1, a2 = "CONVIDAR (ENTER)", "IR ATÉ ELE (J)"
        elif self.fr_tab == 1:
            lst = self.fr["in"]
            if not lst:
                self.text("Nenhum pedido de amizade.", 19, (190, 186, 200), (box.centerx, box.y + 180), shadow=False)
            for i, nm in enumerate(lst[:6]):
                rr = rows[i]
                self.rrect(rr, (40, 56, 40, 255) if i == self.fr_sel else (24, 22, 30, 255), 8, 2,
                           (150, 220, 150, 255) if i == self.fr_sel else (60, 56, 70, 255))
                self.text(f"{nm} quer ser seu amigo", 20, (255, 255, 255), (rr.x + 14, rr.centery), center=False, shadow=False)
            a1, a2 = "ACEITAR (ENTER)", "RECUSAR (R)"
        else:
            self.text("Digite o nome de usuário do seu amigo:", 19, (210, 206, 220), (box.centerx, box.y + 112), shadow=False)
            fld = pygame.Rect(box.x + 90, box.y + 140, box.w - 180, 44)
            self.rrect(fld, (8, 8, 14, 255), 8, 2, (150, 165, 230, 255))
            self.text(self.fr_input + ("|" if int(self.t * 2) % 2 == 0 else " "), 26, (255, 255, 255), fld.center, shadow=False)
            if self.fr["out"]:
                self.text("Aguardando resposta: " + ", ".join(self.fr["out"][:4]), 17, (190, 186, 200), (box.centerx, box.y + 220), shadow=False)
            a1, a2 = "ENVIAR PEDIDO (ENTER)", ""
        for rr, lab, col in ((R["act"], a1, (50, 110, 60)), (R["alt"], a2, (90, 60, 110))):
            if lab:
                self.rrect(rr, col + (255,), 8, 2, (230, 230, 240, 255))
                self.text(lab, 18, (255, 255, 255), rr.center, shadow=False)
        if self.fr_note and self.t < self.fr_note_t:
            self.text(self.fr_note, 19, (200, 245, 200), (box.centerx, box.bottom - 80), shadow=False)
        self.text("← →  abas   ↑ ↓  escolher   X remover   TAB/ESC  fechar", 15, (150, 146, 160), (box.centerx, box.bottom - 12), shadow=False)

    def mp_send_state(self, dt=0.0, force=False):
        self.mp_ping_t = getattr(self, "mp_ping_t", 0.0) - dt
        if self.mp_ping_t <= 0 and self.mp_net is not None:
            self.mp_ping_t = 5.0
            self.mp_net.ping()
        self.mp_send_t -= dt
        if not force and self.mp_send_t > 0:
            return
        self.mp_send_t = 0.05
        if self.mp_net is not None:
            self.mp_net.send({"t": "state", "room": self.mp_room, "x": round(self.px, 3), "y": round(self.py, 3),
                              "hd": round(self.hd, 3), "mv": 1 if self.moving else 0,
                              "lg": round(max(0.0, self.lunge), 3), "rl": round(self.roll_t, 3) if self.rolling else -1.0,
                              "dead": 1 if self.mp_dead else 0, "hp": int(self.mp_hp), "pm": int(self.mp_maxhp)})

    def mp_smooth(self, dt):
        k = min(1.0, dt * 14.0)
        for q in self.mp_players.values():
            tx, ty = q.get("x", q["dx"]), q.get("y", q["dy"])
            if math.hypot(tx - q["dx"], ty - q["dy"]) > 4.0:
                q["dx"], q["dy"] = tx, ty
            q["dx"] += (tx - q["dx"]) * k
            q["dy"] += (ty - q["dy"]) * k
            q["dhd"] += angle_diff(q.get("hd", 0.0), q["dhd"]) * k
            q["flash"] = max(0.0, q.get("flash", 0.0) - dt)

    def mp_tick(self, dt, frozen):
        self.mp_poll()
        if not self.mp_on:
            return
        if frozen:
            self.t += dt
        else:
            self.update(dt)
        self.mp_smooth(dt)
        self.mp_send_state(dt)

    # ------------------------------------------------------------------ lógica local
    def mp_update(self, dt):
        hd0 = self.hd
        self.moving, self.steered = False, False
        if not self.mp_dead:
            self.pz += (ground(self.px, self.py, self.duplo) - self.pz) * min(1.0, dt * 15)
        if self.mp_room == "lobby":
            self.inbuf = None
            if self.mp_typing is None:
                dx, dy = self.move_input()
                self.moving = self.drive(dx, dy, dt, 3.2) > 1e-4
            if self.stairs and math.hypot(self.stairs[0] - self.px, self.stairs[1] - self.py) < 0.42:
                self.mp_go_arena()
                return
        else:
            self.mp_arena_update(dt)
        if not self.steered:
            self.spd += (0.0 - self.spd) * min(1.0, dt * 14.0)
        self.turn_v += (angle_diff(self.hd, hd0) / max(dt, 1e-3) - self.turn_v) * min(1.0, dt * 10.0)
        self.face = (math.cos(self.hd), math.sin(self.hd))
        if self.moving:
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = 0.16
                self.spawn_dust(self.px - self.face[0] * 0.15, self.py - self.face[1] * 0.15, ground(self.px, self.py, self.duplo))

    def mp_aim(self):
        fs = self.mp_foes()
        if not fs:
            self.mp_lock = None
            return None
        dist = lambda q: math.hypot(q["dx"] - self.px, q["dy"] - self.py)
        cur = next((q for q in fs if q["id"] == self.mp_lock), None)
        if cur is None or dist(cur) > 9.0:
            best = min(fs, key=dist)
            cur = best if dist(best) <= 7.0 else None
            self.mp_lock = cur["id"] if cur else None
        return (cur["dx"], cur["dy"]) if cur else None

    def mp_cycle_lock(self):
        fs = sorted([q for q in self.mp_foes() if math.hypot(q["dx"] - self.px, q["dy"] - self.py) <= 9.0],
                    key=lambda q: math.hypot(q["dx"] - self.px, q["dy"] - self.py))
        if not fs:
            return
        ids = [q["id"] for q in fs]
        self.mp_lock = ids[(ids.index(self.mp_lock) + 1) % len(ids)] if self.mp_lock in ids else ids[0]

    def mp_arena_update(self, dt):
        self.atk_cd = max(0.0, self.atk_cd - dt)
        self.roll_cd = max(0.0, self.roll_cd - dt)
        self.inv_t = max(0.0, self.inv_t - dt)
        self.hurt_t = max(0.0, self.hurt_t - dt)
        self.sk_cd = [max(0.0, c_ - dt) for c_ in self.sk_cd]
        self.trail_k = 0.0
        self.steered = True
        if self.mp_dead:
            self.mp_dead_t += dt
            self.pscale = 0.0
            if self.mp_dead_t >= MP_RESPAWN:
                self.mp_respawn()
            return
        if self.stam_delay > 0:
            self.stam_delay -= dt
        elif not (self.swinging or self.rolling):
            self.stam = min(self.STAM_MAX, self.stam + self.STAM_REGEN * (1.0 + 0.03 * self.attr_bonus("sab") + 0.01 * self.gear_bonus("amuleto")) * dt)
        act = None
        if self.mp_typing is not None:
            self.inbuf = None
        elif self.inbuf:
            act, tm = self.inbuf
            self.inbuf = (act, tm - dt) if tm - dt > 0 else None
        tgt = self.mp_aim()
        goal = math.atan2(tgt[1] - self.py, tgt[0] - self.px) if tgt else None
        if self.hurt_t > 0:
            self.swinging = self.heavy = self.rolling = False
            self.lunge, self.moving = 0.0, False
            self.px, self.py = push_out(self.px + self.kb[0] * dt, self.py + self.kb[1] * dt, HERO_R, self.solids)
            f = max(0.0, 1.0 - 7.0 * dt)
            self.kb = (self.kb[0] * f, self.kb[1] * f)
            if goal is not None:
                self.turn_to(goal, dt, 8.0)
        elif self.rolling:
            self.roll_t += dt
            k = min(1.0, self.roll_t / self.ROLL_T)
            ease = 1.0 - (1.0 - k) ** 2
            self.px, self.py = push_out(self.roll_from[0] + self.roll_dir[0] * self.ROLL_D * ease,
                                        self.roll_from[1] + self.roll_dir[1] * self.ROLL_D * ease, HERO_R, self.solids)
            self.moving = False
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = 0.07
                self.spawn_dust(self.px, self.py, ground(self.px, self.py, self.duplo))
            if k >= 1.0:
                self.rolling, self.roll_cd = False, self.ROLL_CD
        elif self.swinging:
            self.rt += dt
            if self.skill_cur:
                T, HIT = self.skill_cur["cast"]
            else:
                T, HIT = (self.HEAVY_T, self.HEAVY_HIT) if self.heavy else (self.SWING_T, self.SWING_HIT)
            if self.heavy:
                if self.rt < HIT:
                    self.lunge = -0.30 * (self.rt / HIT)
                elif self.rt < HIT + 0.14:
                    self.lunge = -0.30 + 1.10 * math.sin((self.rt - HIT) / 0.14 * math.pi / 2)
                else:
                    self.lunge = 0.80 * max(0.0, 1.0 - (self.rt - HIT - 0.14) / max(0.01, T - HIT - 0.14))
                self.trail_k = (self.rt - HIT) / 0.28 if self.rt >= HIT else 0.0
            else:
                self.lunge = math.sin(min(1.0, self.rt / T) * math.pi) * 0.55
                self.trail_k = self.rt / 0.5
            if self.skill_cur and self.rt < HIT:
                self.charge_fx()
            if not self.swing_hit and self.rt >= HIT:
                self.swing_hit = True
                self.mp_strike()
            if self.rt >= T:
                self.swinging = self.heavy = False
                self.skill_cur, self.lunge, self.atk_cd = None, 0.0, 0.10
            if self.mp_typing is None:
                self.fight_move(dt, 0.55 if (self.ranged_hero() and not self.skill_cur) else 0.30)
            if goal is not None:
                self.turn_to(goal, dt, 14.0)
        else:
            if act == "roll" and self.roll_cd <= 0 and self.stam > 0:
                self.inbuf = None
                self.begin_roll({"x": tgt[0], "y": tgt[1]} if tgt else None)
            elif act in ("sk0", "sk1") and self.try_skill(int(act[2])):
                self.inbuf = None
            elif act in ("atk", "heavy") and self.atk_cd <= 0 and self.stam > 0:
                self.inbuf, self.skill_cur = None, None
                self.heavy = act == "heavy"
                self.swinging, self.swing_hit, self.rt = True, False, 0.0
                self.spend(self.COST_HEAVY if self.heavy else self.COST_LIGHT)
            elif self.mp_typing is None:
                self.fight_move(dt)
            else:
                self.spd += (0.0 - self.spd) * min(1.0, dt * 14.0)
            if goal is not None:
                self.turn_to(goal, dt, 14.0)
            elif self.moving:
                dx, dy = self.move_input()
                if dx or dy:
                    self.turn_to(math.atan2(dy, dx), dt, 16.0)
        self.mp_check_shots()

    def mp_roll_dmg(self, mult):
        crit = random.random() < (self.hero["crit"] + 0.02 * self.weapon_lv + 0.01 * self.attr_bonus("des") + 0.01 * self.gear_bonus("anel"))
        dmg = max(1, int(round(self.dmg_value() * mult * MP_DMG_K))) * (2 if crit else 1)
        return min(150, dmg), 1 if crit else 0

    def mp_aim_angle(self):
        tgt = self.mp_aim()
        return math.atan2(tgt[1] - self.py, tgt[0] - self.px) if tgt else self.hd

    def mp_send_shot(self, kind, ang, spd, rng, mult, pierce, heavy=False):
        dmg, crit = self.mp_roll_dmg(mult)
        s = self.add_shot(kind, ang, spd, rng, mult, heavy=heavy, pierce=pierce, poise=0)
        s["mine"] = True
        if self.mp_net is not None:
            self.mp_net.send({"t": "shot", "x": round(self.px, 3), "y": round(self.py, 3), "ang": round(ang, 3), "dmg": dmg,
                              "crit": crit, "kind": kind, "spd": spd, "rng": rng, "pierce": 1 if pierce else 0})

    def mp_send_melee(self, reach, arc, mult):
        dmg, crit = self.mp_roll_dmg(mult)
        if self.mp_net is not None:
            self.mp_net.send({"t": "atk", "x": round(self.px, 3), "y": round(self.py, 3), "ang": round(self.hd, 3), "dmg": dmg,
                              "crit": crit, "reach": reach, "arc": arc})

    def mp_strike(self):
        ang = self.mp_aim_angle()
        if self.skill_cur:
            sk = MP_SKILLS.get(self.skill_cur["id"])
            if sk and sk[0] == "atk":
                _, reach, arc, mult, dash = sk
                if dash:
                    self.px, self.py = push_out(self.px + math.cos(self.hd) * dash, self.py + math.sin(self.hd) * dash, HERO_R, self.solids)
                self.mp_send_melee(reach, arc, mult)
                self.spawn(self.px, self.py, self.pz + 0.4, SKILL_FX.get(self.skill_cur["id"], (255, 255, 255)), 22, 3.0)
                self.shake = 8
            elif sk:
                self.mp_send_shot(sk[1], ang, sk[2], sk[3], sk[4], sk[1] == "snipe")
            return
        heavy = self.heavy
        hid = self.hero["id"]
        if hid == "ranger":
            self.mp_send_shot("arrow", ang, 14.0, 11.0, 1.9 if heavy else 1.0, heavy, heavy)
            self.play("ok")
        elif hid == "mage":
            self.mp_send_shot("bolt", ang, 10.0, 10.0, 0.8 if heavy else 0.45, False, heavy)
            self.play("card")
        else:
            self.mp_send_melee(1.95 if heavy else 1.55, 1.35 if heavy else 1.15, 1.9 if heavy else 1.0)

    # ------------------------------------------------------------------ dano recebido
    def mp_take_hit(self, by, dmg, crit, sx, sy):
        if self.mp_dead or self.mp_room != "arena" or self.phase != "mp":
            return False
        if self.rolling and self.roll_t <= self.ROLL_IFR:
            self.float_text("Esquivou!", self.px, self.py, self.pz + 1.5, (120, 220, 255))
            self.play("ok")
            return False
        if self.inv_t > 0:
            return False
        if random.random() < min(0.6, 0.04 * self.armor_lv + 0.01 * self.gear_bonus("armadura")):
            self.inv_t = max(self.inv_t, 0.5)
            self.float_text("Bloqueou!", self.px, self.py, self.pz + 1.5, (190, 200, 230))
            self.play("ok")
            return False
        dmg = int(max(1, dmg))
        self.mp_hp = max(0, self.mp_hp - dmg)
        self.pflash, self.shake = 0.3, 9
        self.hurt_t, self.inv_t = 0.30, 0.55
        self.swinging = self.heavy = self.rolling = False
        self.lunge, self.inbuf, self.skill_cur = 0.0, None, None
        dx, dy = self.px - sx, self.py - sy
        L = math.hypot(dx, dy) or 1.0
        self.kb = (dx / L * 4.5, dy / L * 4.5)
        self.spawn(self.px, self.py, self.pz + 0.5, (230, 70, 70), 12)
        self.float_text(f"-{dmg}", self.px, self.py, self.pz + 1.4, (255, 90, 90))
        self.play("crit" if crit else "bad")
        if self.mp_net is not None:
            self.mp_net.send({"t": "hurt", "by": by, "dmg": dmg, "crit": 1 if crit else 0, "x": round(self.px, 3), "y": round(self.py, 3)})
        if self.mp_hp <= 0:
            self.mp_die(by)
        return True

    def mp_die(self, by):
        self.mp_dead, self.mp_dead_t = True, 0.0
        self.swinging = self.heavy = self.rolling = False
        self.lunge, self.inbuf, self.skill_cur, self.pscale = 0.0, None, None, 0.0
        self.spawn(self.px, self.py, self.pz + 0.6, (230, 60, 60), 40, 3.2)
        self.shake = 14
        if self.mp_net is not None:
            self.mp_net.send({"t": "died", "by": by})
        self.mp_send_state(force=True)

    def mp_on_atk(self, m):
        if self.mp_room != "arena":
            return
        if m.get("reach", 0) > 2.2:
            self.spawn(m["x"], m["y"], self.pz + 0.4, (220, 200, 255), 14, 3.0)
        if self.mp_dead:
            return
        dx, dy = self.px - m["x"], self.py - m["y"]
        d = math.hypot(dx, dy)
        if d > m.get("reach", 1.9):
            return
        if d > 0.25 and abs(angle_diff(math.atan2(dy, dx), m.get("ang", 0.0))) > m.get("arc", 1.15):
            return
        self.mp_take_hit(m["id"], m.get("dmg", 1), m.get("crit", 0), m["x"], m["y"])

    def mp_on_shot(self, m):
        if self.mp_room != "arena":
            return
        ang, spd, rng = m.get("ang", 0.0), max(1.0, m.get("spd", 12.0)), m.get("rng", 10.0)
        self.shots.append({"kind": m.get("kind", "arrow"), "x": m["x"] + math.cos(ang) * 0.5, "y": m["y"] + math.sin(ang) * 0.5,
                           "vx": math.cos(ang) * spd, "vy": math.sin(ang) * spd, "ang": ang, "spd": spd, "life": rng / spd,
                           "mult": 1.0, "hit": set(), "t": 0.0, "r": 0.14, "heavy": False, "crit": None,
                           "pierce": bool(m.get("pierce")), "poise": None, "mp_owner": m["id"],
                           "dmg": m.get("dmg", 1), "mcrit": m.get("crit", 0)})

    def mp_check_shots(self):
        if self.mp_dead:
            return
        for s in self.shots:
            if "mp_owner" not in s or s.get("done"):
                continue
            if math.hypot(s["x"] - self.px, s["y"] - self.py) <= HERO_R + s["r"] + 0.1:
                if s["kind"] == "fireball":
                    s["done"], s["life"] = True, 0.0
                    self.mp_take_hit(s["mp_owner"], s["dmg"], s["mcrit"], s["x"], s["y"])
                    self.mp_boom(s["x"], s["y"])
                    continue
                if self.mp_take_hit(s["mp_owner"], s["dmg"], s["mcrit"], s["x"] - s["vx"], s["y"] - s["vy"]):
                    s["done"] = True
                    if not s["pierce"]:
                        s["life"] = 0.0

    def mp_boom(self, x, y):
        z = ground(x, y, self.duplo)
        self.spawn(x, y, z + 0.4, (255, 140, 40), 30, 4.0)
        self.spawn(x, y, z + 0.5, (255, 226, 120), 18, 3.0)
        self.play("boom")

    def mp_explode(self, x, y, s):
        self.mp_boom(x, y)
        self.shake = max(self.shake, 8 if math.hypot(self.px - x, self.py - y) < 5 else 2)
        owner = s.get("mp_owner")
        if owner is not None and not s.get("done") and not self.mp_dead:
            d = math.hypot(self.px - x, self.py - y)
            if d <= 1.9:
                s["done"] = True
                self.mp_take_hit(owner, int(s["dmg"] * (1.0 if d <= 0.95 else 0.6)), s.get("mcrit", 0), x, y)

    def mp_on_hurt(self, m):
        q = self.mp_players.get(m.get("id"))
        x, y = m.get("x", 0.0), m.get("y", 0.0)
        if q is not None:
            q["flash"] = 0.3
        if self.mp_room != "arena":
            return
        z = ground(x, y, self.duplo)
        self.spawn(x, y, z + 0.6, (230, 70, 70), 12)
        self.float_text(f"-{m.get('dmg', 0)}", x, y, z + 1.6, (255, 230, 80) if m.get("by") == self.mp_me else (255, 140, 120))
        if m.get("crit"):
            self.float_text("CRIT!", x, y, z + 2.1, (255, 255, 255))
        if m.get("by") == self.mp_me:
            self.play("crit" if m.get("crit") else "hit")
            self.shake = max(self.shake, 5)
        for s in self.shots:                                    # o projétil que acertou some em todos os PCs
            if (s.get("mp_owner") == m.get("by") or (s.get("mine") and m.get("by") == self.mp_me)) and not s["pierce"] \
                    and math.hypot(s["x"] - x, s["y"] - y) < 1.2:
                s["life"] = 0.0
                s["done"] = True

    def mp_on_kill(self, m):
        by_me, me_dead = m.get("by") == self.mp_me, m.get("victim") == self.mp_me
        if m.get("bn"):
            self.mp_say(f"{m['bn']} derrotou {m.get('vn', '?')}")
        else:
            self.mp_say(f"{m.get('vn', '?')} caiu")
        q = self.mp_players.get(m.get("victim"))
        if q is not None and self.mp_room == "arena":
            self.spawn(q["dx"], q["dy"], self.pz + 0.6, (230, 60, 60), 30, 3.0)
        if by_me and not me_dead:
            self.gold += 15
            self.float_text("+15 ouro", self.px, self.py, self.pz + 2.0, (255, 224, 120))
            self.banner, self.banner_t = f"Você derrotou {m.get('vn', '?')}!", 2.5
            self.save_progress()

    # ------------------------------------------------------------------ teclado / mouse
    def mp_key(self, key, uni):
        if self.fr_open:
            self.fr_key(key, uni)
            return True
        if self.mp_typing is None and self.fr_inv and key in (pygame.K_y, pygame.K_n):
            self.fr_invite_answer(key == pygame.K_y)
            return True
        if self.mp_typing is None and self.mp_room == "lobby" and key == pygame.K_TAB:
            self.fr_toggle(True)
            return True
        if self.mp_typing is not None:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                txt, self.mp_typing = self.mp_typing.strip(), None
                if txt and self.mp_net is not None:
                    self.mp_net.send({"t": "chat", "text": txt})
            elif key == pygame.K_ESCAPE:
                self.mp_typing = None
            elif key == pygame.K_BACKSPACE:
                self.mp_typing = self.mp_typing[:-1]
            elif uni and uni.isprintable() and len(self.mp_typing) < 100:
                self.mp_typing += uni
            return True
        if key == pygame.K_ESCAPE:
            self.back_to_menu()
            return True
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.mp_typing, self.inbuf = "", None
            return True
        if key == pygame.K_t:
            return True
        if self.mp_room == "lobby":
            if key in (pygame.K_e, pygame.K_f):
                if self.smith_near():
                    self.open_smith()
                elif self.market_near():
                    self.open_market()
                return True
            return False
        if key == pygame.K_b:
            self.mp_lobby()
        elif key == pygame.K_TAB:
            self.mp_cycle_lock()
        elif key in (pygame.K_j, pygame.K_z):
            self.fight_attack()
        elif key in (pygame.K_l, pygame.K_e):
            self.fight_heavy()
        elif key in (pygame.K_k, pygame.K_x, pygame.K_SPACE):
            self.fight_roll()
        elif key == pygame.K_q:
            self.fight_skill(0)
        elif key == pygame.K_r:
            self.fight_skill(1)
        else:
            return False
        return True

    def mp_game_click(self, pos):
        R = self.fr_rects()
        if self.fr_open:
            self.fr_click(pos)
            return
        if self.fr_inv and R["inv_yes"].collidepoint(pos):
            self.fr_invite_answer(True)
            return
        if self.fr_inv and R["inv_no"].collidepoint(pos):
            self.fr_invite_answer(False)
            return
        if self.mp_room == "lobby" and R["hud"].collidepoint(pos):
            self.fr_toggle(True)
            return
        if self.menu_btn_rect().collidepoint(pos):
            self.back_to_menu()
        elif self.smith_hint is not None and self.smith_hint.collidepoint(pos) and self.smith_near():
            self.open_smith()
        elif self.mk_hint is not None and self.mk_hint.collidepoint(pos) and self.market_near():
            self.open_market()
        elif self.mp_room == "arena" and self.mp_typing is None:
            self.fight_attack()

    # ------------------------------------------------------------------ desenho
    def mp_shadows(self):
        if not self.mp_on:
            return []
        return [(q["dx"], q["dy"], ground(q["dx"], q["dy"], self.duplo), 0.30) for q in self.mp_visible()]

    def mp_remote_items(self, items, objs):
        if not self.mp_on:
            return
        for q in self.mp_visible():
            hid, race = q.get("h", "knight"), q.get("r", "human")
            lg, rl, mv = q.get("lg", 0.0), q.get("rl", -1.0), bool(q.get("mv"))
            x, y = q["dx"], q["dy"]
            pp = parts_player(self.t, mv, hid, (0.7071, 0.7071), max(0.0, min(1.0, lg / 0.55)) if lg else 0.0, race)
            ang = q["dhd"] - HERO_FRONT
            sx = sy = sz = 1.0
            lean, zoff, flash = [0.0, 0.0], 0.0, q.get("flash", 0.0)
            if mv:
                lean = [0.0707, 0.0707]
            else:
                sz = 1 + 0.015 * math.sin(self.t * 3)
            if lg > 0.01:
                lk = 0.25 if hid in ("ranger", "mage") else 1.0
                x += math.cos(q["dhd"]) * lg * lk
                y += math.sin(q["dhd"]) * lg * lk
                sz, sx, sy = 0.94, 1.04, 1.04
            if rl >= 0:
                kr = min(1.0, rl / self.ROLL_T)
                ang = (ang + kr * math.tau + math.pi) % math.tau - math.pi
                sz, sx, sy, zoff = 0.72, 1.12, 1.12, 0.05
                if rl <= self.ROLL_IFR:
                    flash += 0.18
            pp = pose_parts(pp, sx, sy, sz, tuple(lean))
            hs = HERO_SCALE * (VILLAGE_HERO_K if getattr(self, "village", False) else 1.0)
            z = ground(x, y, self.duplo) + zoff
            hkey = x + y
            lo, hi = -1e9, 1e9
            for (ox0, oy0, ox1, oy1, kmin, kmax) in objs:
                in_front = x - HERO_R >= ox1 - 1e-6 or y - HERO_R >= oy1 - 1e-6
                behind = ox0 >= x + HERO_R - 1e-6 or oy0 >= y + HERO_R - 1e-6
                if in_front and not behind:
                    lo = max(lo, kmax)
                elif behind and not in_front:
                    hi = min(hi, kmin)
            if lo < hi:
                hkey = min(max(hkey, lo + 0.002), hi - 0.002)
            key = ("mp", q["id"], hid, int(math.floor(ang / 0.2)), mv, lg > 0.01, rl >= 0)
            items.append((hkey, z, (x, y, z, hs, ang, key, scale_parts(pp, hs, flash), "npc", 0.0)))

    def mp_hero_color(self, hid):
        return next((h["color"] for h in HEROES if h["id"] == hid), (220, 220, 220))

    def draw_mp_overlay(self):
        scr, cam = self.screen, self.cam
        arena = self.mp_room == "arena"
        for q in self.mp_visible():                                     # nome (e vida na arena) sobre cada jogador
            px_, py_ = proj(q["dx"], q["dy"], ground(q["dx"], q["dy"], self.duplo) + (1.7 if self.village else 2.3), cam)
            self.ptext(q.get("n", "?"), 12, mix(self.mp_hero_color(q.get("h")), 0.4), (px_, py_ - 12), 2, max_w=150)
            if arena:
                fr = max(0.0, min(1.0, q.get("hp", 1) / max(1, q.get("pm", 1))))
                bw = 46
                pygame.draw.rect(scr, (10, 6, 10), (px_ - bw // 2 - 2, py_ - 4, bw + 4, 8))
                pygame.draw.rect(scr, (200, 52, 60), (px_ - bw // 2, py_ - 2, int(bw * fr), 4))
        if self.stairs and not arena:
            sx_, sy_ = proj(self.stairs[0], self.stairs[1], 2.0, cam)
            n = sum(1 for q in self.mp_players.values() if q.get("room") == "arena")
            self.ptext(f"POÇO = ARENA PvP ({n} lá dentro)", 12, (255, 150, 120), (sx_, sy_), 2)
        # barras de vida e fôlego
        hc = tuple(self.hero["color"])[:3]
        scr.blit(px_get(("portrait", hc), lambda: px_up(px_portrait(hc))), (12, 10))
        for (y0, fr, c1, c2) in ((16, self.mp_hp / max(1, self.mp_maxhp), (214, 54, 62), (120, 24, 40)),
                                 (46, self.stam / self.STAM_MAX, (70, 160, 236), (36, 86, 176))):
            pygame.draw.rect(scr, (10, 6, 12), (84, y0, 210, 22), border_radius=5)
            pygame.draw.rect(scr, c2, (87, y0 + 3, 204, 16), border_radius=4)
            pygame.draw.rect(scr, c1, (87, y0 + 3, int(204 * max(0.0, min(1.0, fr))), 16), border_radius=4)
        self.text(f"{int(self.mp_hp)}/{int(self.mp_maxhp)}", 18, (255, 255, 255), (189, 27), shadow=True)
        self.text(f"OURO {self.gold}   K/D {self.mp_k}/{self.mp_d}", 20, (255, 224, 120), (12, 84), center=False)
        # skills
        sk = SKILLS[self.hero["id"]]
        if arena:
            for i_, d_ in enumerate(sk):
                r_ = pygame.Rect(12 + i_ * 104, 108, 98, 26)
                cd = self.sk_cd[i_]
                pygame.draw.rect(scr, (24, 18, 30), r_, border_radius=6)
                pygame.draw.rect(scr, d_["color"] if cd <= 0 else (70, 66, 76), r_, 2, border_radius=6)
                self.text(f"{d_['key']} {d_['name'][:9]}" + (f" {cd:.0f}s" if cd > 0 else ""), 16, (240, 240, 250), r_.center, shadow=False)
        # sala
        self.ptext("ARENA" if arena else "LOBBY", 16, (255, 110, 100) if arena else (226, 192, 128), (W // 2 - 60, 22), 2)
        # placar
        rows = [(self.cfg.get("username") or (self.saves[self.slot]["name"] if self.slot is not None and self.saves[self.slot] else "Você"), self.mp_k, self.mp_d,
                 self.hero["color"], True)]
        rows += [(q.get("n", "?"), q.get("k", 0), q.get("d", 0), self.mp_hero_color(q.get("h")), False) for q in self.mp_players.values()]
        rows.sort(key=lambda r: (-r[1], r[2]))
        rows = rows[:9]
        box = pygame.Rect(W - 236, 212, 224, 26 + 20 * len(rows))
        self.rrect(box, (10, 8, 14, 190), 10, 2, (110, 90, 70, 255))
        self.text("JOGADORES      K / D", 15, (190, 180, 160), (box.x + 10, box.y + 6), center=False, shadow=False)
        for i_, (n_, k_, d_, c_, me_) in enumerate(rows):
            col = (255, 240, 170) if me_ else mix(c_, 0.35)
            self.text(n_[:11], 17, col, (box.x + 10, box.y + 26 + i_ * 20), center=False, shadow=False)
            self.text(f"{k_} / {d_}", 17, col, (box.right - 54, box.y + 26 + i_ * 20), center=False, shadow=False)
        # banner, avisos de abate, chat
        if self.banner_t > 0:
            self.otext(self.banner, 26, (255, 240, 226), (W // 2, 120), ow=2)
        for i_, (tt, s_) in enumerate([f for f in self.mp_feed if self.t - f[0] < 6.0][-5:]):
            self.text(s_, 19, (255, 214, 160), (12, 146 + i_ * 20), center=False)
        lines = [c for c in self.mp_chat if self.mp_typing is not None or self.t - c[0] < 10.0][-7:]
        for i_, (tt, n_, s_) in enumerate(lines):
            self.text(f"{n_}: {s_}", 19, (230, 240, 255), (12, H - 70 - (len(lines) - i_) * 20), center=False)
        if self.mp_typing is not None:
            r_ = pygame.Rect(10, H - 62, 560, 30)
            self.rrect(r_, (8, 8, 14, 230), 8, 2, (150, 165, 230, 255))
            self.text("Chat: " + self.mp_typing + ("|" if int(self.t * 2) % 2 == 0 else ""), 22, (255, 255, 255), (r_.x + 8, r_.centery), center=False, shadow=False)
        hint = ("J leve  L forte  K/ESPAÇO rolar  Q/R habilidade  TAB mira  B lobby  ENTER chat" if arena
                else "WASD andar  •  E loja  •  I inventário  •  ENTER chat  •  TAB amigos  •  poço = ARENA")
        self.text(hint, 18, (200, 196, 210), (W // 2, H - 14), shadow=True)
        for f in self.floaters:
            self.text(f["s"], 40, f["c"], self.view_map(f["x"], f["y"]))
        self.draw_friends_hud()
        if self.mp_dead:
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((120, 0, 0, 90))
            scr.blit(ov, (0, 0))
            self.otext("VOCÊ FOI DERROTADO", 60, (255, 120, 120), (W // 2, H // 2 - 20), ow=3)
            self.otext(f"Renasce em {max(0.0, MP_RESPAWN - self.mp_dead_t):.1f}s", 30, (255, 230, 220), (W // 2, H // 2 + 30), ow=2)


class Game(MPMixin):
    def __init__(self):
        try:
            pygame.mixer.pre_init(22050, -16, 1, 512)
        except Exception:
            pass
        pygame.init()
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        pygame.display.set_caption("Obscurity")
        self.clock = pygame.time.Clock()
        self.fonts = {}
        self.icons = {}
        self.sounds = {}
        self.hero_index = 0
        self.hero = HEROES[self.hero_index]
        self.music_channel = None
        self.music_sound = None
        self.cfg = load_cfg()
        self.saves = load_saves()
        self.slot = None              # slot em uso na partida
        self.menu_sel = 0             # botão do menu (0 = START, 1 = CRIAR SAVE)
        self.slot_sel = 0
        self.slot_mode = "load"       # "load" (START) ou "create" (CRIAR SAVE)
        self.confirm = None           # ("del" | "ow", slot) esperando confirmação
        self.cr_name, self.cr_cls, self.cr_slot = "", 0, 0
        self.cr_msg, self.cr_msg_until = "", 0.0
        self.music_on = self.cfg["music"]
        self.settings_open = False
        self.smith_open, self.smith_sel, self.smith_msg, self.smith_msg_t = False, 0, "", 0.0
        self.smith_done, self.smith_t, self.smith_hint = False, 0.0, None
        self.mk_open, self.mk_tab, self.mk_i, self.mk_msg, self.mk_msg_t = False, 0, 0, "", 0.0
        self.mk_hint, self.mk_t, self.market_done, self.mk_stock = None, 0.0, True, []
        self.vnpcs, self.solids_static, self.npc_rng = [], [], random.Random(7)
        self.weapon_lv = self.armor_lv = 0
        self.gear = {}
        self.bag = []
        self.inv_open, self.inv_area, self.inv_i, self.inv_msg, self.inv_msg_t = False, "bag", 0, "", 0.0
        self.set_sel = 0
        self.fs = False
        self.ui_t = 0.0
        self._music_box = {}
        try:
            pygame.mixer.set_reserved(1)       # canal 0 é só da trilha; os efeitos usam os outros
        except Exception:
            pass
        # a trilha é sintetizada em segundo plano para o jogo abrir na hora
        def _make_music(box=self._music_box):
            try:
                box["data"] = build_medieval_track(lambda: time.sleep(0.001))
            except Exception:
                traceback.print_exc()
        threading.Thread(target=_make_music, daemon=True).start()
        try:
            self.sounds = {
                "ok": tone(660, 0.18, 0.2, 400), "bad": tone(200, 0.3, 0.25, -100),
                "hit": tone(140, 0.15, 0.3, -60), "card": tone(500, 0.35, 0.2, 500),
                "fall": tone(400, 0.6, 0.2, -300), "crit": tone(900, 0.18, 0.22, 600),
                "boom": tone(62, 0.7, 0.4, -22), "roar": tone(98, 1.1, 0.42, -58),
            }
        except Exception:
            self.sounds = {}
        self.vig = make_vignette()
        self.cglow = {}
        self.glow = [make_glow(110, (70, 40, 12)), make_glow(120, (90, 52, 16))]
        self.stair_glow = [make_glow(120, (10, 26, 70)), make_glow(125, (18, 44, 110)), make_glow(130, (28, 64, 150))]
        self.best = 1
        self.t = 0.0
        self.shake = 0.0
        self.cam = (0, 0)
        self.particles, self.floaters = [], []
        self.shots, self.crystals = [], []          # projéteis (flechas, bolas de fogo...) e cristais de gelo
        self.skill_cur, self.sk_cd = None, [0.0, 0.0]
        self.banner, self.banner_t = "", 0.0
        self.score = 0
        self.transition = None
        self.mp_init()
        self.auto_host = AutoHost() if (self.cfg.get("auto_host") or "--abrir" in sys.argv) else None
        self.new_run(title=True)
        if not self.cfg.get("username"):                     # primeira vez: escolhe o nome de usuário único
            self.open_username("", "title")

    # ---------------------------------------------------------- utilidades
    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.Font(None, size)
        return self.fonts[size]

    def title_font(self, size):
        """Fonte do título do menu (estilo Dungeons & Dragons); cai na padrão se nada for encontrado."""
        if not hasattr(self, "_title_path"):
            self._title_path = find_title_font()
            print(f"[obscurity] fonte do título: {self._title_path or 'padrão do pygame'}")
        key = ("title", size)
        if key not in self.fonts:
            try:
                self.fonts[key] = pygame.font.Font(self._title_path, size)
            except Exception:
                self.fonts[key] = pygame.font.Font(None, size)
        return self.fonts[key]

    def text(self, s, size, color, pos, center=True, shadow=True):
        f = self.font(size)
        if shadow:
            sh = f.render(s, True, (0, 0, 0))
            r = sh.get_rect(center=(pos[0] + 2, pos[1] + 2)) if center else sh.get_rect(topleft=(pos[0] + 2, pos[1] + 2))
            self.screen.blit(sh, r)
        img = f.render(s, True, color)
        r = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
        self.screen.blit(img, r)

    def play(self, name):
        if self.cfg.get("sfx", True) and name in self.sounds:
            self.sounds[name].play()

    def icon(self, k, size):
        key = (k, size)
        if key not in self.icons:
            grid, pal = ICON_ART[k]
            base = pygame.Surface((12, 12), pygame.SRCALPHA)
            for r, row in enumerate(grid):
                for c, ch in enumerate(row):
                    if ch in pal:
                        base.set_at((c, r), pal[ch])
            self.icons[key] = pygame.transform.scale(base, (size, size))
        return self.icons[key]

    # ------------------------------------------------------------ estado
    def new_run(self, title=False):
        self.hero = HEROES[self.hero_index]
        self.floor = 1
        self.village = True            # cenário inicial: o vilarejo vem antes do andar 1
        seed = getattr(self, "forced_seed", None)
        self.forced_seed = None
        self.run_seed = seed if seed is not None else random.randrange(1, 1 << 30)
        self.prev, self.boss_bag = {}, []
        print(f"[obscurity] semente da partida: {self.run_seed}")
        sv_ = self.saves[self.slot] if (getattr(self, "slot", None) is not None and self.saves[self.slot]) else None
        self.weapon_lv = min(FORGE_MAX, sv_.get("weapon", 0)) if sv_ else 0      # upgrades do ferreiro (ficam no save)
        self.armor_lv = min(FORGE_MAX, sv_.get("armor", 0)) if sv_ else 0
        self.race = (sv_ or {}).get("race", "human")                                                                # raça do save (muda o visual)
        self.attrs = class_attrs(self.hero["id"], (sv_ or {}).get("race", "human"))                                # atributos: da classe, ou os do save
        if sv_ and isinstance(sv_.get("attrs"), dict):
            self.attrs.update(sv_["attrs"])
        self.maxhp = self.hero["hp"] + forge_hearts(self.armor_lv) + self.attr_bonus("con") // 4
        self.hp = self.maxhp
        self.gold = sv_.get("gold", 0) if sv_ else 0
        self.gear = {}                 # loot equipado (vale só nesta descida)
        self.bag = clean_bag(sv_.get("bag")) if sv_ else []        # mochila: loot guardado (fica no save), ainda não equipado
        self.mk_stock = make_market_stock(random.Random(self.run_seed ^ 0x3A4B5C))
        self.inv_open = False
        self.mk_open, self.market_done = False, True
        self.smith_open, self.smith_done = False, False
        self.streak = 0
        self.mistakes = 0
        self.score = 0
        self.transition = None
        self.new_floor()
        if title:
            self.phase = "title"
            self.pz = ground(self.px, self.py, self.duplo)

    def make_foe(self, kind, x, y, hpmul=1.0, elite=False):
        f = self.floor
        boss = kind in BOSS_KINDS
        mhp = int((12 + 5 * f) * (1.8 if boss else 1.0) * hpmul)
        s = ENEMY_SCALE.get(kind, 1.0) * (1.15 if elite else 1.0)
        return {"kind": kind, "x": x, "y": y, "z": ground(x, y, self.duplo), "hp": mhp, "maxhp": mhp,
                "flash": 0.0, "scale": 1.0, "s": s, "boss": boss, "elite": elite,
                "stop": 1.3 + (STOP_SCALE.get(kind, ENEMY_SCALE.get(kind, 1.0)) * (1.15 if elite else 1.0) - 1) * 1.4}

    def start_transition(self, kind="dark", duration=1.1):
        self.transition = {"kind": kind, "time": 0.0, "duration": duration}

    def advance_floor(self):
        if getattr(self, "village", False):      # desceu o poço do vilarejo: começa o andar 1
            self.village = False
            self.new_floor()
            return
        self.floor = max(1, self.floor + 1)
        self.best = max(self.best, self.floor)
        self.save_progress()
        self.score += 50 + self.floor * 12
        self.new_floor()
        if self.floor % HEAL_EVERY == 0 and self.hp < self.maxhp:   # cura só a cada 3 andares
            self.hp = self.maxhp
            self.float_text("Vida restaurada! ♥", self.px, self.py, self.pz + 1.8, (120, 255, 140))

    def new_floor(self):
        f = self.floor
        rng = random.Random(self.run_seed * 1000003 + f * 7919)
        global N, OY                  # o vilarejo é maior que as salas: troca o tamanho da grade e a altura da câmera
        N, OY = (VILLAGE_N, VILLAGE_OY) if getattr(self, "village", False) else (DEF_N, DEF_OY)
        if getattr(self, "village", False):
            lay = gen_village(random.Random(self.run_seed * 1000003 + 4243))
        else:
            lay = self.mp_arena_lay() if getattr(self, "mp_arena", False) else gen_floor(f, rng, self.prev, self.boss_bag)
            self.prev = {"room": lay["room"], "pal": lay["pal_idx"], "kinds": [s["kind"] for s in lay["foes"]],
                         "cave": lay["cave"]}
        self.lay = lay
        self.pal = lay["pal"]
        self.duplo = lay["duplo"]
        self.room_kind = lay["room"]
        self.blocked = lay["blocked"]
        self.torches = lay["torches"]
        self.decor = lay["decor"]
        self.vnpcs = []
        self.npc_rng = random.Random(self.run_seed ^ 0xA11CE)
        if lay.get("village"):                          # aldeões saem da lista fixa e viram personagens que andam
            self.vnpcs = [npc_new(i, k, x, y) for i, (x, y, k) in enumerate(lay["decor"]) if k in WANDER_KINDS]
            self.decor = [d for d in lay["decor"] if d[2] not in WANDER_KINDS]
        if lay.get("village"):
            self.room = build_village(rng.randrange(1 << 30), lay)
        else:
            self.room = build_room(self.pal, self.duplo, rng.randrange(1 << 30), lay)
        self.foes = [self.make_foe(s["kind"], s["x"], s["y"], s["hpmul"], s["elite"]) for s in lay["foes"]]
        # sólidos: o que o herói não atravessa (decoração grande, baús, beira da plataforma)
        self.solids = self.build_solids()
        self.solids_static = self.solids
        self.pblocked = set(self.blocked) | {cell_of(x, y) for (x, y, k) in self.decor if k == "chest"}
        self.banner, self.banner_t = lay["banner"], (3.0 if lay["banner"] else 0.0)
        self.cur = 0
        self.enemy = self.foes[0] if self.foes else None
        self.waypoints = []
        self.px, self.py = lay["spawn"]
        self.pz = ground(self.px, self.py, self.duplo) + 5.0
        self.pscale, self.pflash = 1.0, 0.0
        self.reset_fight()
        self.fc_k, self.fc_focus, self.view_rect = 0.0, None, None     # câmera travada no inimigo
        self.stairs = None
        self.moving = False
        self.land_t = 0.0
        self.dust_t = 0.0
        self.flash_t = 0.0
        if self.foes:   # nasce já olhando para o primeiro inimigo
            self.hd = math.atan2(self.foes[0]["y"] - self.py, self.foes[0]["x"] - self.px)
        else:
            self.hd = HERO_FRONT
        self.face = (math.cos(self.hd), math.sin(self.hd))
        self.turn_v = self.spd = self.stuck_t = 0.0
        self.steered = False
        self.phase = "arrive"
        self.pt = 0.0
        self.dtm = 0.0
        self.particles.clear()
        self.floaters.clear()
        self.shots, self.crystals = [], []

    def find_path(self, src, dst, target=None):
        """Caminho (A* + suavização) até dst desviando de obstáculos e de outros inimigos vivos."""
        a, b = cell_of(*src), cell_of(*dst)
        soft = {cell_of(fo["x"], fo["y"]) for fo in self.foes if fo["hp"] > 0 and fo is not target}
        foe_boxes = [(fo["x"] - 0.45 * fo["s"], fo["y"] - 0.45 * fo["s"], fo["x"] + 0.45 * fo["s"], fo["y"] + 0.45 * fo["s"])
                     for fo in self.foes if fo["hp"] > 0 and fo is not target]
        for blk, extra in ((self.pblocked | soft, foe_boxes), (self.pblocked, []), (set(self.blocked), [])):
            blk = set(blk)
            blk.discard(a)
            blk.discard(b)
            cells = find_cells(a, b, self.duplo, blk)
            if cells:
                pts = [src] + [(i + 0.5, j + 0.5) for i, j in cells[1:-1]] + [dst]
                return smooth_path(pts, self.duplo, blk, self.solids + extra)[1:-1]
        return []

    # ------------------------------------------------- colisão e giro do herói
    def decor_rect(self, x, y, kind):
        """Pegada no chão (x0, y0, x1, y1) de uma decoração, calculada a partir dos próprios voxels dela."""
        ps = self.decor_parts(kind)
        return (x + min(p[0] for p in ps), y + min(p[1] for p in ps),
                x + max(p[0] + p[3] for p in ps), y + max(p[1] + p[4] for p in ps))

    def build_solids(self):
        out = [self.decor_rect(x, y, k) for (x, y, k) in self.decor if k in SOLID_KINDS]
        for (i, j) in self.lay.get("water", ()):      # o rio é parede para o herói (só ponte/vau atravessa)
            out.append((i + 0.06, j + 0.06, i + 0.94, j + 0.94))
        if self.duplo:
            for j in range(N):
                if not 3 <= j <= 4:     # fora da rampa: faixa do desnível + guarda-corpo da plataforma
                    out.append((PLAT_X - 0.16, j, PLAT_X + 1.0, j + 1.0))
        return out

    def turn_to(self, goal, dt, rate):
        """Gira suavemente o herói (self.hd) em direção ao ângulo `goal`."""
        d = angle_diff(goal, self.hd)
        self.hd = (self.hd + d * (1.0 - math.exp(-rate * dt)) + math.pi) % math.tau - math.pi

    def steer(self, tx, ty, dt, speed, limit=None):
        """Anda em direção a (tx, ty): primeiro vira o corpo, acelera aos poucos, e nunca entra em nada sólido."""
        dx, dy = tx - self.px, ty - self.py
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return 0.0
        speed *= self.cfg["speed"]
        self.steered = True
        goal = math.atan2(dy, dx)
        self.turn_to(goal, dt, 16.0)
        align = max(0.0, math.cos(angle_diff(goal, self.hd)))      # de costas pro alvo: quase parado, só girando
        self.spd += (speed - self.spd) * min(1.0, dt * 12.0)       # acelera/freia suave
        step = self.spd * dt * (0.25 + 0.75 * align)
        step = min(step, dist if limit is None else max(0.0, limit))
        ox, oy = self.px, self.py
        self.px, self.py = push_out(ox + dx / dist * step, oy + dy / dist * step, HERO_R, self.solids)
        moved = math.hypot(self.px - ox, self.py - oy)
        if step > 1e-4 and moved < step * 0.35:     # encostou e não sai do lugar
            self.stuck_t += dt
        else:
            self.stuck_t = max(0.0, self.stuck_t - dt)
        return moved

    # ---- modo manual e configurações
    SET_ROWS = ("mode", "speed", "music", "music_vol", "sfx", "shake", "fs", "reset", "menu", "back")

    def set_keys(self):
        return [k for k in self.SET_ROWS if not (k == "menu" and self.phase in MENU_PHASES)]

    def manual(self):
        return self.cfg["mode"] == "manual"

    def move_input(self):
        k = pygame.key.get_pressed()
        sx = int(bool(k[pygame.K_RIGHT] or k[pygame.K_d])) - int(bool(k[pygame.K_LEFT] or k[pygame.K_a]))
        sy = int(bool(k[pygame.K_DOWN] or k[pygame.K_s])) - int(bool(k[pygame.K_UP] or k[pygame.K_w]))
        wx, wy = sx + sy, sy - sx
        n = math.hypot(wx, wy)
        return (wx / n, wy / n) if n else (0.0, 0.0)

    def foe_solids(self):
        out = []
        for fo in self.foes:
            if fo["hp"] > 0 and fo["scale"] > 0.02:
                h = max(0.2, min(0.42 * fo["s"], (fo["stop"] - HERO_R - 0.12) / 1.42))
                out.append((fo["x"] - h, fo["y"] - h, fo["x"] + h, fo["y"] + h))
        return out

    def drive(self, dx, dy, dt, speed):
        if dx == 0 and dy == 0:
            return 0.0
        self.steered = True
        goal = math.atan2(dy, dx)
        self.turn_to(goal, dt, 22.0)
        align = max(0.0, math.cos(angle_diff(goal, self.hd)))
        self.spd += (speed * self.cfg["speed"] - self.spd) * min(1.0, dt * 12.0)
        step = self.spd * dt * (0.5 + 0.5 * align)
        ox, oy = self.px, self.py
        self.px, self.py = push_out(ox + dx * step, oy + dy * step, HERO_R, self.solids + self.foe_solids())
        return math.hypot(self.px - ox, self.py - oy)

    def dry_line(self, fo):
        """False se há rio entre o herói e o inimigo (não dá pra lutar do outro lado da água)."""
        water = self.lay.get("water")
        if not water:
            return True
        for k in range(13):
            x = self.px + (fo["x"] - self.px) * k / 12
            y = self.py + (fo["y"] - self.py) * k / 12
            if cell_of(x, y) in water:
                return False
        return True

    def walk_manual(self, dt):
        dx, dy = self.move_input()
        moved = self.drive(dx, dy, dt, 3.2)
        self.moving = moved > 1e-4
        best, bd = None, 1e9
        for i, fo in enumerate(self.foes):
            if fo["hp"] > 0 and fo["scale"] > 0.02:
                d = math.hypot(fo["x"] - self.px, fo["y"] - self.py)
                if d < bd:
                    best, bd = i, d
        if best is None:
            self.room_reward()
            return
        self.cur, self.enemy = best, self.foes[best]
        if bd <= self.enemy["stop"] + 0.02 and self.dry_line(self.enemy):      # encostou num inimigo: começa o combate
            self.moving = False
            self.start_combat()

    def stairs_manual(self, dt):
        dx, dy = self.move_input()
        moved = self.drive(dx, dy, dt, 3.4)
        self.moving = moved > 1e-4
        sx, sy = self.stairs
        if math.hypot(sx - self.px, sy - self.py) < 0.38:      # entrou no poço da escada
            self.moving = False
            self.phase = "descend"
            self.dt_ = 0.0
            self.play("fall")

    def sync_mode(self):
        if self.phase == "walk" and self.enemy is not None:
            self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), (self.enemy["x"], self.enemy["y"]), self.enemy)
        elif self.phase == "stairs" and self.stairs:
            tgt = self.stairs
            if self.lay.get("village"):
                tgt = self.lay["smith"] if not self.smith_done else (self.lay["market"] if not self.market_done else self.stairs)
            self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), tgt)

    def set_mode(self, mode):
        self.cfg["mode"] = mode
        save_cfg(self.cfg)
        self.sync_mode()

    def cycle_mode(self):
        self.set_mode("auto" if self.manual() else "manual")
        if self.phase not in MENU_PHASES:
            self.banner = "MODO MANUAL: você controla!" if self.manual() else "MODO AUTOMÁTICO"
            self.banner_t = 1.8

    def toggle_music(self):
        self.music_on = not self.music_on
        self.cfg["music"] = self.music_on
        save_cfg(self.cfg)

    def toggle_fs(self):
        try:
            pygame.display.toggle_fullscreen()
        except Exception:
            pass
        self.fs = not self.fs

    def open_settings(self):
        self.settings_open = True
        self.set_sel = 0

    def close_settings(self):
        self.settings_open = False
        save_cfg(self.cfg)
        self.sync_mode()

    def settings_change(self, row, d):
        c = self.cfg
        if row == "mode":
            self.set_mode("manual" if c["mode"] == "auto" else "auto")
        elif row == "speed":
            if d:
                c["speed"] = round(min(1.6, max(0.6, c["speed"] + 0.1 * d)), 2)
        elif row == "music":
            self.toggle_music()
        elif row == "music_vol":
            if d:
                c["music_vol"] = round(min(1.0, max(0.0, c["music_vol"] + 0.1 * d)), 2)
        elif row == "sfx":
            c["sfx"] = not c["sfx"]
            if c["sfx"]:
                self.play("ok")
        elif row == "shake":
            c["shake"] = not c["shake"]
        elif row == "fs":
            self.toggle_fs()
        elif row == "reset" and d == 0:
            self.cfg = dict(DEFAULT_CFG)
            self.music_on = self.cfg["music"]
            self.sync_mode()
        elif row == "menu" and d == 0:
            self.settings_open = False
            save_cfg(self.cfg)
            self.back_to_menu()
            return
        elif row == "back" and d == 0:
            self.close_settings()
            return
        save_cfg(self.cfg)

    def settings_key(self, key):
        if key == pygame.K_F11:
            self.toggle_fs()
            return
        if key in (pygame.K_ESCAPE, pygame.K_c):
            self.close_settings()
            return
        keys = self.set_keys()
        n = len(keys)
        row = keys[min(self.set_sel, n - 1)]
        if key in (pygame.K_UP, pygame.K_w):
            self.set_sel = (self.set_sel - 1) % n
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.set_sel = (self.set_sel + 1) % n
        elif key in (pygame.K_LEFT, pygame.K_a):
            self.settings_change(row, -1)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.settings_change(row, 1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.settings_change(row, 0)

    def draw_badges(self, title=False):
        man = self.manual()
        if title:
            pills = [(pygame.Rect(14, 14, 214, 32), f"MOVER: {'MANUAL' if man else 'AUTOMÁTICO'}  [T]"),
                     (pygame.Rect(14, 52, 214, 32), "CONFIGURAÇÕES  [C]")]
        else:
            pills = [(pygame.Rect(W - 150, 134, 138, 32), f"{'MANUAL' if man else 'AUTO'}  [T]"),
                     (pygame.Rect(W - 150, 172, 138, 32), "CONFIG  [C]")]
        for i, (r, s) in enumerate(pills):
            base = (24, 84, 60) if (i == 0 and man) else (34, 40, 84)
            edge = (130, 240, 180) if (i == 0 and man) else (150, 165, 230)
            if title:
                self.chunky(r, (22, 62, 44) if (i == 0 and man) else (18, 15, 14), edge if (i == 0 and man) else (120, 90, 64), 14, 3, 3)
                self.otext(s, 20, (255, 255, 255), r.center, ow=1)
                continue
            self.rrect(r, (*base, 225), 14, 2, (*edge, 255))
            self.text(s, 21, (240, 246, 255), r.center, shadow=False)

    def draw_settings(self):
        scr, c = self.screen, self.cfg
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 218))
        scr.blit(dim, (0, 0))
        pw, ph = 720, 520
        panel = pygame.Rect((W - pw) // 2, 30, pw, ph)
        self.rrect(panel.inflate(14, 14), (255, 100, 20, 22), 34)
        self.rrect(panel, (7, 6, 6, 252), 28, 4, (104, 76, 54, 255))
        self.otext("CONFIGURAÇÕES", 50, (244, 232, 214), (W // 2, panel.y + 44), ink=(104, 38, 10), ow=3)
        gold, green, red = (226, 176, 104), (130, 206, 150), (206, 112, 106)

        def onoff(v, on="LIGADO", off="DESLIGADO"):
            return (on, green) if v else (off, red)

        rows = [
            ("mode", "Movimento do herói", "MANUAL (você controla)" if self.manual() else "AUTOMÁTICO", gold, None),
            ("speed", "Velocidade do herói", f"{int(round(c['speed'] * 100))}%", gold, (c["speed"] - 0.6) / 1.0),
            ("music", "Música  [N]", *onoff(self.music_on), None),
            ("music_vol", "Volume da música", f"{int(round(c['music_vol'] * 100))}%", gold, c["music_vol"]),
            ("sfx", "Efeitos sonoros", *onoff(c["sfx"]), None),
            ("shake", "Tremor de tela", *onoff(c["shake"]), None),
            ("fs", "Tela cheia  [F11]", *onoff(self.fs, "SIM", "NÃO"), None),
            ("reset", "Restaurar padrões", "ENTER", (168, 158, 144), None),
            ("menu", "Voltar ao menu", "ENTER", (168, 158, 144), None),
            ("back", "Voltar ao jogo" if self.phase not in MENU_PHASES else "Voltar", "ENTER", (168, 158, 144), None),
        ]
        rows = [r_ for r_ in rows if r_[0] in self.set_keys()]
        y0 = panel.y + 92
        for i, (key, label, val, col, frac) in enumerate(rows):
            r = pygame.Rect(panel.x + 24, y0 + i * 38, pw - 48, 34)
            sel = i == self.set_sel
            if sel:
                self.rrect(r, (104, 38, 10, 245), 14, 2, (200, 120, 50, 255))
            else:
                self.rrect(r, (13, 11, 11, 215), 14, 1, (46, 36, 30, 255))
            self.text(label, 27, (244, 232, 214) if sel else (160, 150, 136), (r.x + 16, r.y + 8), center=False, shadow=False)
            cy = r.centery
            adj = key not in ("reset", "menu", "back")
            if frac is not None:
                bx = r.x + 350
                bar = pygame.Rect(bx, cy - 5, 160, 10)
                pygame.draw.rect(scr, (20, 17, 17), bar, border_radius=5)
                pygame.draw.rect(scr, col, (bar.x, bar.y, int(bar.w * max(0.0, min(1.0, frac))), bar.h), border_radius=5)
                pygame.draw.rect(scr, (110, 90, 72), bar, 1, border_radius=5)
                self.text(val, 25, col, (bar.right + 34, cy), center=False, shadow=False)
                lx, rx = bar.x - 16, bar.right + 16
            else:
                cx = r.x + 440
                self.text(val, 27, col, (cx, cy), shadow=False)
                half = self.font(27).size(val)[0] // 2
                lx, rx = cx - half - 18, cx + half + 18
            if sel and adj:
                pygame.draw.polygon(scr, (240, 180, 100), [(lx - 5, cy), (lx + 5, cy - 8), (lx + 5, cy + 8)])
                pygame.draw.polygon(scr, (240, 180, 100), [(rx + 5, cy), (rx - 5, cy - 8), (rx - 5, cy + 8)])
        self.text("↑ ↓ escolher     ← → mudar     ENTER alternar     C / ESC voltar", 21, (140, 130, 118),
                  (W // 2, panel.bottom - 22), shadow=False)

    # -------------------------------------------------------------- lógica
    def attr_bonus(self, k):
        """Pontos acima do valor base (8) no atributo k."""
        return max(0, getattr(self, "attrs", {}).get(k, ATTR_BASE) - ATTR_BASE)

    def gear_bonus(self, slot):
        it = getattr(self, "gear", {}).get(slot)
        return it["bonus"] if it else 0

    def dmg_value(self):
        return (5 + self.floor + self.hero["damage"] + min(self.streak, 5) + getattr(self, "weapon_lv", 0)
                + self.attr_bonus("for") // 2 + self.gear_bonus("arma"))

    # ------------------------------------------------------------ combate estilo Souls (tempo real, sem turnos)
    # mover: WASD/setas | leve: J | forte: L | rolar: K/ESPAÇO | trocar alvo: TAB | mouse: esq. ataca, dir. rola
    STAM_MAX, STAM_REGEN, STAM_DELAY = 100.0, 42.0, 0.60       # fôlego: máximo, recuperação por segundo, pausa antes de recuperar
    COST_LIGHT, COST_HEAVY, COST_ROLL = 20.0, 36.0, 24.0
    ROLL_T, ROLL_D, ROLL_CD, ROLL_IFR = 0.50, 1.8, 0.12, 0.34   # rolagem: duração, distância, recarga, janela de imortalidade
    SWING_T, SWING_HIT = 0.42, 0.16                # golpe leve: duração e instante do acerto
    HEAVY_T, HEAVY_HIT = 0.88, 0.52                # golpe forte: lento, mas atordoa e bate mais
    FOE_REACH = 0.45                               # alcance do golpe do monstro = stop + isto
    FOE_ARC = 1.05                                 # meio-ângulo do golpe do monstro (60°): fora do cone ele erra
    FOE_STRIKE_T, FOE_LUNGE = 0.30, 0.55           # golpe do monstro: duração e avanço
    AGGRO = 4.6                                    # a que distância os monstros notam o herói
    MOVE_SPEED = 3.1

    def reset_fight(self):
        self.swinging = self.swing_hit = self.heavy = False
        self.rolling = False
        self.rt = 0.0                      # tempo do golpe em andamento
        self.roll_t = 0.0                  # tempo da rolagem em andamento
        self.roll_dir, self.roll_from = (0.0, 0.0), (0.0, 0.0)
        self.atk_cd = self.roll_cd = 0.0
        self.roll_side = getattr(self, "roll_side", 1)
        self.inbuf = None                  # comando guardado por 0,3 s (apertar um pouco cedo funciona)
        self.lunge = 0.0
        self.trail_k = 0.0
        self.stam, self.stam_delay = self.STAM_MAX, 0.0
        self.hurt_t = self.inv_t = 0.0     # atordoamento ao apanhar / imortalidade curta depois do golpe
        self.kb = (0.0, 0.0)
        self.lock_manual = False
        self.dt_last = 1.0 / 60.0
        self.shots, self.crystals = [], []
        self.skill_cur, self.sk_cd = None, [0.0, 0.0]

    # ---- entrada
    def fight_attack(self):
        if self.phase in ("fight", "mp"):
            self.inbuf = ("atk", 0.30)

    def fight_heavy(self):
        if self.phase in ("fight", "mp"):
            self.inbuf = ("heavy", 0.30)

    def fight_roll(self):
        if self.phase in ("fight", "mp"):
            self.inbuf = ("roll", 0.30)

    def fight_skill(self, i):
        if self.phase in ("fight", "mp") and i < len(SKILLS[self.hero["id"]]):
            self.inbuf = ("sk%d" % i, 0.30)

    def skill_btns(self):
        n = len(SKILLS[self.hero["id"]])
        top = H - 165
        rs = [pygame.Rect(W - 160, top + 89, 150, 54), pygame.Rect(10, top + 89, 150, 54)]
        return rs[:n]

    def fight_hint(self):
        sk = SKILLS[self.hero["id"]]
        keys = " / ".join(d["key"] for d in sk)
        if self.ranged_hero():
            return f"Ataque de longe!  {keys} = {'magias' if len(sk) > 1 else 'habilidade'}"
        return f"Mova-se, ataque e role!  {keys} = habilidade"

    def fight_btns(self):
        top = H - 165
        w, g = 200, 14
        x0 = W // 2 - (3 * w + 2 * g) // 2
        return tuple(pygame.Rect(x0 + i * (w + g), top + 80, w, 72) for i in range(3))     # ROLAR, ATACAR, FORTE

    # ---- alvos
    def alive_foes(self):
        return [f for f in self.foes if f["hp"] > 0]

    def noticed(self):
        """Algum monstro vivo, com caminho seco até o herói, está perto o bastante para notá-lo?"""
        for fo in self.foes:
            if fo["hp"] > 0 and fo["scale"] > 0.02 and math.hypot(fo["x"] - self.px, fo["y"] - self.py) <= self.AGGRO \
                    and self.dry_line(fo):
                return True
        return False

    def pick_lock(self, force=False, cycle=False):
        """Trava a mira (e a câmera) no monstro mais próximo; TAB troca de alvo."""
        al = self.alive_foes()
        if not al:
            return
        dist = lambda f: math.hypot(f["x"] - self.px, f["y"] - self.py)
        cur = self.enemy
        if cycle:
            al.sort(key=dist)
            nxt = al[(al.index(cur) + 1) % len(al)] if (cur in al and len(al) > 1) else al[0]
            self.enemy, self.lock_manual = nxt, True
        elif not (self.lock_manual and cur is not None and cur["hp"] > 0 and not force):
            best = min(al, key=dist)
            if force or cur is None or cur not in al or dist(best) < dist(cur) - 0.6:
                self.enemy = best
                if force:
                    self.lock_manual = False
        self.cur = self.foes.index(self.enemy)

    def start_combat(self):
        """Algum monstro notou o herói: a luta começa em tempo real e TODOS os monstros vivos vêm atrás dele."""
        self.reset_fight()
        self.phase = "fight"
        for i, fo in enumerate(self.alive_foes()):
            fo["ai"], fo["ait"] = "chase", 0.0
            fo["acd"] = 0.7 + random.random() * 0.7 + 0.30 * i       # reação: o primeiro golpe não é instantâneo
            fo["elunge"] = 0.0
            fo["path"], fo["path_t"] = [], 0.0
            fo["poise"], fo["poise_t"], fo["armor_t"] = self.poise_max(fo), 0.0, 0.0
            fo["cw"] = random.choice((-1, 1))
            fo["cw_t"] = random.random() * 1.5
        self.pick_lock(force=True)

    # ---- herói
    def spend(self, cost):
        self.stam = max(0.0, self.stam - cost)
        self.stam_delay = self.STAM_DELAY + (0.55 if self.stam <= 0.0 else 0.0)      # zerou o fôlego: demora mais para voltar

    def begin_roll(self, e):
        dx, dy = self.move_input()
        if dx == 0 and dy == 0:            # sem direção: pulo para trás, de frente para o alvo (como no Souls)
            if e is not None:
                ex, ey = self.px - e["x"], self.py - e["y"]
            else:
                ex, ey = -math.cos(self.hd), -math.sin(self.hd)
            L = math.hypot(ex, ey) or 1.0
            dx, dy = ex / L, ey / L
        else:
            self.hd = math.atan2(dy, dx)
        self.roll_dir, self.roll_from = (dx, dy), (self.px, self.py)
        self.rolling, self.roll_t = True, 0.0
        self.swinging = self.heavy = False
        self.lunge = 0.0
        self.spend(self.COST_ROLL)
        self.spawn_dust(self.px, self.py, ground(self.px, self.py, self.duplo))

    def fight_move(self, dt, mul=1.0):
        """Andar livre durante a luta (o corpo continua olhando para o alvo travado)."""
        dx, dy = self.move_input()
        self.steered = True
        if dx == 0 and dy == 0:
            self.spd += (0.0 - self.spd) * min(1.0, dt * 14.0)
            self.moving = False
            return
        self.spd += (self.MOVE_SPEED * self.cfg["speed"] * mul - self.spd) * min(1.0, dt * 12.0)
        ox, oy = self.px, self.py
        self.px, self.py = push_out(ox + dx * self.spd * dt, oy + dy * self.spd * dt, HERO_R, self.solids + self.foe_solids())
        self.moving = math.hypot(self.px - ox, self.py - oy) > 1e-4

    def fight_update(self, dt, e):
        self.dt_last = dt
        al = self.alive_foes()
        if not al:
            return
        self.pick_lock()
        e = self.enemy
        self.atk_cd = max(0.0, self.atk_cd - dt)
        self.roll_cd = max(0.0, self.roll_cd - dt)
        self.inv_t = max(0.0, self.inv_t - dt)
        self.hurt_t = max(0.0, self.hurt_t - dt)
        self.sk_cd = [max(0.0, c_ - dt) for c_ in self.sk_cd]
        self.trail_k = 0.0
        self.steered = True
        # fôlego: só volta a encher quando o herói não está atacando nem rolando
        if self.stam_delay > 0:
            self.stam_delay -= dt
        elif not (self.swinging or self.rolling):
            self.stam = min(self.STAM_MAX, self.stam + self.STAM_REGEN * (1.0 + 0.03 * self.attr_bonus("sab") + 0.01 * self.gear_bonus("amuleto")) * dt)
        act = None
        if self.inbuf:
            act, tm = self.inbuf
            self.inbuf = (act, tm - dt) if tm - dt > 0 else None
        goal = math.atan2(e["y"] - self.py, e["x"] - self.px)

        if self.hurt_t > 0:                 # apanhou: fica atordoado e é empurrado para longe do golpe
            self.swinging = self.heavy = self.rolling = False
            self.lunge = 0.0
            self.moving = False
            self.px, self.py = push_out(self.px + self.kb[0] * dt, self.py + self.kb[1] * dt, HERO_R,
                                        self.solids + self.foe_solids())
            f = max(0.0, 1.0 - 7.0 * dt)
            self.kb = (self.kb[0] * f, self.kb[1] * f)
            self.turn_to(goal, dt, 8.0)
        elif self.rolling:                  # IMORTAL só no começo da rolagem (ROLL_IFR); depois fica vulnerável
            self.roll_t += dt
            k = min(1.0, self.roll_t / self.ROLL_T)
            ease = 1.0 - (1.0 - k) ** 2
            tx = self.roll_from[0] + self.roll_dir[0] * self.ROLL_D * ease
            ty = self.roll_from[1] + self.roll_dir[1] * self.ROLL_D * ease
            self.px, self.py = push_out(tx, ty, HERO_R, self.solids + self.foe_solids())
            self.moving = False
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = 0.07
                self.spawn_dust(self.px, self.py, ground(self.px, self.py, self.duplo))
            if k >= 1.0:
                self.rolling = False
                self.roll_cd = self.ROLL_CD
        elif self.swinging:
            self.rt += dt
            if self.skill_cur:
                T, HIT = self.skill_cur["cast"]
            else:
                T, HIT = (self.HEAVY_T, self.HEAVY_HIT) if self.heavy else (self.SWING_T, self.SWING_HIT)
            if self.heavy:                  # ergue a arma (recua), desce com tudo e recupera
                if self.rt < HIT:
                    self.lunge = -0.30 * (self.rt / HIT)
                elif self.rt < HIT + 0.14:
                    self.lunge = -0.30 + 1.10 * math.sin((self.rt - HIT) / 0.14 * math.pi / 2)
                else:
                    self.lunge = 0.80 * max(0.0, 1.0 - (self.rt - HIT - 0.14) / max(0.01, T - HIT - 0.14))
                self.trail_k = (self.rt - HIT) / 0.28 if self.rt >= HIT else 0.0
            else:
                self.lunge = math.sin(min(1.0, self.rt / T) * math.pi) * 0.55
                self.trail_k = self.rt / 0.5
            if self.skill_cur and self.rt < HIT:
                self.charge_fx()
            if not self.swing_hit and self.rt >= HIT:
                self.swing_hit = True
                self.swing_strike()
                if self.phase != "fight":
                    return
            if self.rt >= T:
                self.swinging = self.heavy = False
                self.skill_cur = None
                self.lunge = 0.0
                self.atk_cd = 0.10
            # arqueira/maga atiram andando; as habilidades pedem mais firmeza
            self.fight_move(dt, 0.55 if (self.ranged_hero() and not self.skill_cur) else 0.30)
            self.turn_to(goal, dt, 14.0)
        else:
            if act == "roll" and self.roll_cd <= 0 and self.stam > 0:
                self.inbuf = None
                self.begin_roll(e)
            elif act in ("sk0", "sk1") and self.try_skill(int(act[2])):
                self.inbuf = None
            elif act in ("atk", "heavy") and self.atk_cd <= 0 and self.stam > 0:
                self.inbuf = None
                self.skill_cur = None
                self.heavy = act == "heavy"
                self.swinging, self.swing_hit, self.rt = True, False, 0.0
                self.spend(self.COST_HEAVY if self.heavy else self.COST_LIGHT)
            else:
                self.fight_move(dt)
            self.turn_to(goal, dt, 14.0)

        # ---- os monstros
        for fo in al:
            if self.phase != "fight":
                break
            if fo["hp"] > 0:
                self.foe_think(dt, fo)

    def swing_strike(self):
        """Instante do acerto: o golpe varre um arco na frente do herói e pode pegar vários monstros."""
        if self.skill_cur:                      # habilidade (Q / R)
            self.cast_skill(self.skill_cur["id"])
            return
        if self.ranged_hero():                  # arqueira e maga atacam de longe
            self.fire_basic()
            return
        heavy = self.heavy
        reach = 0.9 + (0.35 if heavy else 0.0)
        arc = 1.35 if heavy else 1.15           # meio-ângulo do arco (rad)
        hit = False
        for fo in self.alive_foes():
            dx, dy = fo["x"] - self.px, fo["y"] - self.py
            d = math.hypot(dx, dy)
            if d > fo["stop"] + reach or abs(angle_diff(math.atan2(dy, dx), self.hd)) > arc or not self.dry_line(fo):
                continue
            hit = True
            self.hit_foe(fo, 1.9 if heavy else 1.0, heavy)
            if self.phase != "fight":
                return
        if not hit:
            self.float_text("Errou!", self.px, self.py, self.pz + 1.4, (210, 214, 230))

    # ---- ataques à distância, habilidades e efeitos
    def ranged_hero(self):
        return self.hero["id"] in ("ranger", "mage")

    def aim_angle(self):
        e = self.enemy
        if e is not None and e["hp"] > 0:
            return math.atan2(e["y"] - self.py, e["x"] - self.px)
        return self.hd

    def try_skill(self, i):
        sk = SKILLS[self.hero["id"]]
        if i >= len(sk) or self.sk_cd[i] > 0 or self.atk_cd > 0:
            return False
        d = sk[i]
        self.skill_cur = d
        self.sk_cd[i] = d["cd"] * max(0.4, 1.0 - 0.03 * self.attr_bonus("int"))
        self.heavy = True                       # reaproveita a animação do golpe forte (recua e solta)
        self.swinging, self.swing_hit, self.rt = True, False, 0.0
        self.play("card")
        return True

    def charge_fx(self):
        if random.random() < 0.7:
            a = self.hd + random.uniform(-0.6, 0.6)
            self.trail(self.px + math.cos(a) * 0.45, self.py + math.sin(a) * 0.45, self.pz + random.uniform(0.7, 1.3),
                       SKILL_FX[self.skill_cur["id"]], 0.08, 0.3)

    def trail(self, x, y, z, c, s=0.08, life=0.3):
        self.particles.append({"x": x + random.uniform(-0.06, 0.06), "y": y + random.uniform(-0.06, 0.06), "z": z,
                               "vx": random.uniform(-0.3, 0.3), "vy": random.uniform(-0.3, 0.3),
                               "vz": random.uniform(0.2, 1.2), "life": life, "c": c, "s": s, "gz": z})

    def add_shot(self, kind, ang, speed, rng, mult, **kw):
        s = {"kind": kind, "x": self.px + math.cos(ang) * 0.5, "y": self.py + math.sin(ang) * 0.5,
             "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed, "ang": ang, "spd": speed,
             "life": rng / speed, "mult": mult, "hit": set(), "t": 0.0, "r": 0.14, "heavy": False,
             "crit": None, "pierce": False, "poise": None}
        s.update(kw)
        self.shots.append(s)
        return s

    def fire_basic(self):
        """Ataque comum à distância: a arqueira atira flechas; a maga, faíscas arcanas (pouco dano)."""
        ang = self.aim_angle()
        heavy = self.heavy
        if self.hero["id"] == "ranger":
            self.add_shot("arrow", ang, 14.0, 11.0, 1.9 if heavy else 1.0, heavy=heavy, pierce=heavy)
            self.play("ok")
        else:
            self.add_shot("bolt", ang, 10.0, 10.0, 0.8 if heavy else 0.45, heavy=heavy, poise=0)
            self.play("card")

    def cast_skill(self, sid):
        ang = self.aim_angle()
        if sid == "tiro_preciso":
            self.add_shot("snipe", ang, 26.0, 16.0, 3.0, heavy=True, crit=True, pierce=True, poise=3, r=0.2)
            self.shake = 8
            self.float_text("Tiro Preciso!", self.px, self.py, self.pz + 1.8, (255, 230, 120))
            self.play("crit")
        elif sid == "bola_fogo":
            self.add_shot("fireball", ang, 8.5, 12.0, 4.0, heavy=True, r=0.26)
            self.shake = 6
            self.float_text("Bola de Fogo!", self.px, self.py, self.pz + 1.8, (255, 150, 60))
            self.play("boom")
        elif sid == "cristais_gelo":
            self.cast_crystals()
        elif sid == "investida":
            self.skill_charge(ang)
        elif sid == "pancada_sismica":
            self.skill_slam()
        elif sid == "golpe_furtivo":
            self.skill_backstab()

    def explode(self, x, y, s):
        if self.phase == "mp":
            self.mp_explode(x, y, s)
            return
        R = 1.9
        z = ground(x, y, self.duplo)
        self.spawn(x, y, z + 0.4, (255, 140, 40), 36, 4.5)
        self.spawn(x, y, z + 0.5, (255, 226, 120), 22, 3.0)
        self.spawn(x, y, z + 0.3, (80, 60, 60), 14, 2.0)
        for i in range(24):                      # anel de brasas
            a = i / 24 * math.tau
            self.particles.append({"x": x, "y": y, "z": z + 0.1, "vx": math.cos(a) * 5.0, "vy": math.sin(a) * 5.0,
                                   "vz": 0.8, "life": 0.5, "c": (255, 170 + (i % 3) * 25, 50), "s": 0.12, "gz": z})
        for fo in list(self.alive_foes()):
            d = math.hypot(fo["x"] - x, fo["y"] - y)
            if fo["hp"] > 0 and d <= R + self.foe_radius(fo):
                m = s["mult"] if d <= 0.95 else s["mult"] * 0.6
                self.hit_foe(fo, m, True, crit=False, col=(255, 170, 60), poise=3)
                if fo["hp"] > 0:
                    fo["burn"], fo["burn_tk"] = 3.0, 0.5
                    fo["burn_dmg"] = max(1, int(self.dmg_value() * 0.35))
                    self.float_text("Queimando!", fo["x"], fo["y"], fo["z"] + 2.2 * fo["s"], (255, 150, 50))
        self.shake = 16
        self.flash_t = 0.12
        self.play("boom")

    def freeze_foe(self, e, dur):
        if e.get("boss"):
            dur *= 0.5
        e["ai"], e["ait"], e["elunge"] = "stagger", dur, 0.0
        e["armor_t"] = dur + 0.8
        e["ice_t"] = dur
        self.float_text("Congelado!", e["x"], e["y"], e["z"] + 2.0 * e["s"], (150, 230, 255))
        self.spawn(e["x"], e["y"], e["z"] + 0.6, (190, 235, 255), 14, 2.4)

    def cast_crystals(self):
        """Cristais de gelo brotam do chão em fila até o alvo e em volta dele; congelam quem tocarem."""
        e = self.enemy
        d = math.hypot(e["x"] - self.px, e["y"] - self.py) if e is not None else 4.0
        d = min(d, 8.0)
        ang = self.aim_angle()
        ux, uy = math.cos(ang), math.sin(ang)
        cast, pts = set(), []
        n = max(2, int(d / 0.85))
        for i in range(1, n + 1):
            dist = 1.1 + (d - 1.1) * i / n
            pts.append((self.px + ux * dist, self.py + uy * dist, i * 0.07))
        cx, cy = (e["x"], e["y"]) if e is not None else (self.px + ux * d, self.py + uy * d)
        for i in range(7):
            a = i / 7 * math.tau + random.uniform(-0.3, 0.3)
            r = random.uniform(0.5, 1.2)
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r, n * 0.07 + 0.05 + i * 0.04))
        for x, y, dl in pts:
            if circle_hits(x, y, 0.2, self.solids):
                continue
            self.crystals.append({"x": x, "y": y, "t": -dl, "life": 4.0, "h": random.uniform(0.8, 1.45),
                                  "w": random.uniform(0.2, 0.3), "hit": False, "cast": cast,
                                  "lean": (random.uniform(-1, 1), random.uniform(-1, 1))})
        self.float_text("Cristais de Gelo!", self.px, self.py, self.pz + 1.8, (170, 225, 255))
        self.shake = 5
        self.play("crit")

    def skill_charge(self, ang):
        e = self.enemy
        dx, dy = math.cos(ang), math.sin(ang)
        d = math.hypot(e["x"] - self.px, e["y"] - self.py) if e is not None else 2.0
        run = max(0.0, min(3.2, d - (e["stop"] * 0.75 if e is not None else 0.0)))
        steps = max(1, int(run / 0.25))
        for i in range(steps):
            self.px, self.py = push_out(self.px + dx * run / steps, self.py + dy * run / steps, HERO_R,
                                        self.solids + self.foe_solids())
            if i % 2 == 0:
                self.spawn_dust(self.px, self.py, ground(self.px, self.py, self.duplo))
        self.inv_t = max(self.inv_t, 0.25)
        for fo in list(self.alive_foes()):
            ddx, ddy = fo["x"] - self.px, fo["y"] - self.py
            if fo["hp"] > 0 and math.hypot(ddx, ddy) <= fo["stop"] + 1.3 and abs(angle_diff(math.atan2(ddy, ddx), ang)) <= 1.2:
                self.hit_foe(fo, 2.6, True, poise=5)
        self.shake = max(self.shake, 14)
        self.float_text("Investida!", self.px, self.py, self.pz + 1.8, (255, 200, 150))
        self.play("boom")

    def skill_slam(self):
        for fo in list(self.alive_foes()):
            if fo["hp"] > 0 and math.hypot(fo["x"] - self.px, fo["y"] - self.py) <= 2.4 + self.foe_radius(fo):
                self.hit_foe(fo, 2.0, True, poise=5)
        z = self.pz
        for i in range(28):
            a = i / 28 * math.tau
            self.particles.append({"x": self.px, "y": self.py, "z": z + 0.1, "vx": math.cos(a) * 5.5, "vy": math.sin(a) * 5.5,
                                   "vz": 1.2, "life": 0.55, "c": (170, 130, 90) if i % 2 else (230, 210, 170), "s": 0.14, "gz": z})
        self.shake = max(self.shake, 16)
        self.float_text("Pancada Sísmica!", self.px, self.py, self.pz + 1.8, (255, 200, 150))
        self.play("boom")

    def skill_backstab(self):
        e = self.enemy
        if e is None or e["hp"] <= 0:
            return
        self.spawn(self.px, self.py, self.pz + 0.5, (70, 50, 90), 16, 2.0)
        dx, dy = e["x"] - self.px, e["y"] - self.py
        L = math.hypot(dx, dy) or 1.0
        gap = e["stop"] * 0.9
        self.px, self.py = push_out(e["x"] + dx / L * gap, e["y"] + dy / L * gap, HERO_R, self.solids)
        self.hd = math.atan2(e["y"] - self.py, e["x"] - self.px)
        self.spawn(self.px, self.py, ground(self.px, self.py, self.duplo) + 0.5, (110, 70, 150), 16, 2.0)
        self.inv_t = max(self.inv_t, 0.5)
        self.float_text("Golpe Furtivo!", self.px, self.py, self.pz + 1.8, (200, 150, 255))
        self.hit_foe(e, 3.2, True, crit=True, poise=5)

    def update_shots(self, dt):
        keep = []
        for s in self.shots:
            n = max(1, int(s["spd"] * dt / 0.2) + 1)
            h = dt / n
            alive = True
            for _ in range(n):
                s["x"] += s["vx"] * h
                s["y"] += s["vy"] * h
                s["t"] += h
                s["life"] -= h
                if circle_hits(s["x"], s["y"], 0.05, self.solids):
                    alive = False
                    if s["kind"] == "fireball":
                        self.explode(s["x"] - s["vx"] * h * 1.5, s["y"] - s["vy"] * h * 1.5, s)
                    break
                for fo in self.alive_foes():
                    if id(fo) in s["hit"]:
                        continue
                    if math.hypot(fo["x"] - s["x"], fo["y"] - s["y"]) <= self.foe_radius(fo) + s["r"]:
                        s["hit"].add(id(fo))
                        if s["kind"] == "fireball":
                            self.explode(s["x"], s["y"], s)
                            alive = False
                            break
                        col = (255, 236, 150) if s["kind"] == "snipe" else (210, 150, 255) if s["kind"] == "bolt" else (255, 255, 255)
                        self.hit_foe(fo, s["mult"], s["heavy"], crit=s["crit"], col=col, poise=s["poise"])
                        if self.phase not in ("fight", "mp"):
                            self.shots = []
                            return
                        if not s["pierce"]:
                            alive = False
                            break
                if not alive:
                    break
                if s["life"] <= 0:
                    alive = False
                    if s["kind"] == "fireball":
                        self.explode(s["x"], s["y"], s)
                    break
            z = ground(s["x"], s["y"], self.duplo) + 0.85
            k = s["kind"]
            if k == "fireball":
                for _ in range(3):
                    self.trail(s["x"], s["y"], z, random.choice(((255, 140, 40), (255, 200, 80), (200, 70, 30))), 0.11, 0.4)
            elif k == "snipe":
                for _ in range(2):
                    self.trail(s["x"] - s["vx"] * 0.01, s["y"] - s["vy"] * 0.01, z, (255, 226, 120), 0.07, 0.25)
            elif k == "bolt":
                self.trail(s["x"], s["y"], z, (190, 120, 255), 0.07, 0.3)
            if alive:
                keep.append(s)
            if self.phase not in ("fight", "mp"):
                self.shots = []
                return
        self.shots = keep

    def update_fx(self, dt):
        """Projéteis, queimadura, congelamento e cristais de gelo."""
        for fo in self.foes:
            if fo.get("ice_t", 0.0) > 0:
                fo["ice_t"] -= dt
        fight = self.phase in ("fight", "mp")
        if fight:
            self.update_shots(dt)
        elif self.shots:
            self.shots = []
        if self.phase == "fight":                      # queimadura (bola de fogo)
            for fo in list(self.alive_foes()):
                if fo.get("burn", 0.0) <= 0:
                    continue
                fo["burn"] -= dt
                fo["burn_tk"] -= dt
                if random.random() < 0.5:
                    self.trail(fo["x"], fo["y"], fo["z"] + random.uniform(0.3, 1.2) * fo["s"], (255, random.randint(110, 200), 40), 0.09, 0.4)
                if fo["burn_tk"] <= 0:
                    fo["burn_tk"] += 0.5
                    dmg = fo["burn_dmg"]
                    fo["hp"] = max(0, fo["hp"] - dmg)
                    fo["flash"] = 0.3
                    self.float_text(f"-{dmg}", fo["x"], fo["y"], fo["z"] + 1.6 * fo["s"], (255, 150, 50))
                    if fo["hp"] <= 0:
                        self.kill_foe(fo)
                        if self.phase != "fight":
                            break
        for c in self.crystals:                        # cristais brotam, congelam e somem
            c["t"] += dt
            if c["t"] >= 0 and not c["hit"]:
                c["hit"] = True
                z = ground(c["x"], c["y"], self.duplo)
                self.spawn(c["x"], c["y"], z + 0.3, (190, 235, 255), 8, 1.8)
                if self.phase == "fight":
                    for fo in list(self.alive_foes()):
                        if id(fo) in c["cast"] or fo["hp"] <= 0:
                            continue
                        if math.hypot(fo["x"] - c["x"], fo["y"] - c["y"]) <= self.foe_radius(fo) + 0.85:
                            c["cast"].add(id(fo))
                            self.hit_foe(fo, 1.8, True, crit=False, col=(190, 235, 255), poise=0)
                            if fo["hp"] > 0:
                                self.freeze_foe(fo, 2.6)
                            if self.phase != "fight":
                                break
        self.crystals = [c for c in self.crystals if c["t"] < c["life"]]

    def shot_items(self, items, s):
        z = ground(s["x"], s["y"], self.duplo) + 0.85
        ux, uy = math.cos(s["ang"]), math.sin(s["ang"])
        segs = {
            "arrow": [(0.12, 0.07, (220, 224, 232)), (0.0, 0.06, (160, 120, 80)), (-0.12, 0.06, (160, 120, 80)), (-0.24, 0.07, (120, 170, 110))],
            "bolt": [(0.0, 0.20, (200, 130, 255)), (0.0, 0.11, (255, 255, 255)), (-0.14, 0.10, (150, 90, 220))],
            "snipe": [(0.3, 0.10, (255, 255, 255)), (0.15, 0.10, (255, 236, 150)), (0.0, 0.10, (255, 210, 90)),
                      (-0.15, 0.09, (255, 190, 60)), (-0.3, 0.08, (230, 150, 40)), (-0.45, 0.07, (200, 120, 30))],
            "fireball": [(0.0, 0.42, (235, 90, 25)), (0.0, 0.28, (255, 170, 50)), (0.0, 0.15, (255, 240, 170)),
                         (-0.2, 0.24, (210, 70, 20)), (-0.38, 0.16, (160, 50, 20))],
        }[s["kind"]]
        for off, sz, col in segs:
            bx, by = s["x"] + ux * off - sz / 2, s["y"] + uy * off - sz / 2
            bz = z - sz / 2
            items.append((bx + by + sz, bz, (bx, by, bz, sz, sz, sz, col, False, 0.0)))

    def crystal_items(self, items, c):
        t = c["t"]
        z0 = ground(c["x"], c["y"], self.duplo)
        if t < 0:                                      # aviso no chão antes de brotar
            sz = 0.34
            col = (120, 190, 235) if int(self.t * 14) % 2 == 0 else (200, 240, 255)
            items.append((c["x"] + c["y"] + sz, z0, (c["x"] - sz / 2, c["y"] - sz / 2, z0, sz, sz, 0.03, col, False, 0.0)))
            return
        grow = min(1.0, t / 0.22)
        grow = 1.0 - (1.0 - grow) ** 3
        k = grow * min(1.0, (c["life"] - t) / 0.6)
        if k <= 0.02:
            return
        h, w = c["h"] * k, c["w"] * (0.5 + 0.5 * k)
        lx, ly = c["lean"]
        z = z0
        for i, (fh, fw, col) in enumerate(((0.45, 1.0, (120, 190, 235)), (0.35, 0.7, (170, 225, 250)), (0.20, 0.4, (235, 250, 255)))):
            cx, cy = c["x"] + lx * i * 0.05, c["y"] + ly * i * 0.05
            sz, hh = w * fw, h * fh
            items.append((cx + cy + sz, z, (cx - sz / 2, cy - sz / 2, z, sz, sz, hh, col, False, 0.0)))
            z += hh
        for sx_, sy_ in ((0.20, -0.12), (-0.14, 0.18)):          # estilhaços ao lado
            cx, cy = c["x"] + sx_, c["y"] + sy_
            sz, hh = w * 0.5, h * 0.5
            items.append((cx + cy + sz, z0, (cx - sz / 2, cy - sz / 2, z0, sz, sz, hh, (150, 210, 245), False, 0.0)))

    def ice_block_items(self, items, fo):
        r = self.foe_radius(fo) + 0.1
        k = min(1.0, fo["ice_t"] / 0.4)
        for i in range(5):
            a = i * 1.2566 + 0.4
            cx, cy = fo["x"] + math.cos(a) * r, fo["y"] + math.sin(a) * r
            z = fo["z"]
            for fh, fw, col in ((0.40, 0.18, (140, 205, 245)), (0.28, 0.11, (225, 248, 255))):
                hh, sz = fh * fo["s"] * (0.7 + 0.3 * (i % 2)) * k, fw
                items.append((cx + cy + sz, z, (cx - sz / 2, cy - sz / 2, z, sz, sz, hh, col, False, 0.0)))
                z += hh

    # ---- monstros
    def poise_max(self, e):
        return 5 if e.get("boss") else 3 if e.get("elite") else 2

    def foe_radius(self, e):
        return max(0.22, min(0.5, 0.26 * e["s"]))

    def attackers(self):
        return sum(1 for f in self.foes if f["hp"] > 0 and f.get("ai") in ("wind", "strike"))

    def max_attackers(self):
        return 1 if self.floor < 4 else 2          # nos primeiros andares só um monstro ataca por vez

    def wind_time(self, e):
        base = 0.78 - 0.008 * min(self.floor, 25)
        if e.get("boss"):
            base *= 0.82
        elif e.get("elite"):
            base *= 0.92
        return max(0.42, base) + random.random() * 0.18

    def foe_place(self, e, nx, ny):
        """Põe o monstro em (nx, ny) respeitando paredes, rio, outros monstros e o herói."""
        r = self.foe_radius(e)
        nx, ny = push_out(nx, ny, r, self.solids)
        for o in self.foes:
            if o is e or o["hp"] <= 0:
                continue
            ddx, ddy = nx - o["x"], ny - o["y"]
            d = math.hypot(ddx, ddy)
            md = r + self.foe_radius(o) + 0.2
            if 1e-6 < d < md:
                nx += ddx / d * (md - d) * 0.6
                ny += ddy / d * (md - d) * 0.6
        ddx, ddy = nx - self.px, ny - self.py
        d = math.hypot(ddx, ddy)
        md = e["stop"] * 0.82
        if 1e-6 < d < md:
            nx, ny = self.px + ddx / d * md, self.py + ddy / d * md
        nx, ny = push_out(nx, ny, r, self.solids)
        e["x"], e["y"] = nx, ny
        e["z"] = ground(nx, ny, self.duplo)

    def foe_walk(self, e, dx, dy, speed, dt):
        L = math.hypot(dx, dy)
        if L > 1e-6:
            self.foe_place(e, e["x"] + dx / L * speed * dt, e["y"] + dy / L * speed * dt)

    def foe_approach(self, e, dt, speed):
        """Vai atrás do herói (reto; se houver obstáculo no caminho, contorna com A*)."""
        p, q = (e["x"], e["y"]), (self.px, self.py)
        tx, ty = q
        if not segment_clear(p, q, self.solids, r=self.foe_radius(e)):
            e["path_t"] = e.get("path_t", 0.0) - dt
            if e["path_t"] <= 0 or not e.get("path"):
                e["path_t"] = 0.45
                e["path"] = self.find_path(p, q, e)
            pts = e.get("path") or []
            while pts and math.hypot(pts[0][0] - e["x"], pts[0][1] - e["y"]) < 0.22:
                pts.pop(0)
            if pts:
                tx, ty = pts[0]
        else:
            e["path"] = []
        self.foe_walk(e, tx - e["x"], ty - e["y"], speed, dt)

    def foe_strafe(self, e, dt, speed):
        """Perto do herói, esperando a hora de atacar: gira em volta dele."""
        dx, dy = e["x"] - self.px, e["y"] - self.py
        d = math.hypot(dx, dy) or 1e-6
        e["cw_t"] = e.get("cw_t", 0.0) - dt
        if e["cw_t"] <= 0:
            e["cw_t"] = 1.0 + random.random() * 1.6
            e["cw"] = random.choice((-1, 1))
        cw = e.get("cw", 1)
        vx = -dy / d * cw - dx / d * (d - e["stop"]) * 0.8
        vy = dx / d * cw - dy / d * (d - e["stop"]) * 0.8
        self.foe_walk(e, vx, vy, speed, dt)

    def foe_think(self, dt, e):
        """IA do monstro: persegue -> prepara o golpe (aviso vermelho) -> golpeia -> recupera (e pode encadear)."""
        ai = e.get("ai", "chase")
        e["acd"] = max(0.0, e.get("acd", 0.0) - dt)
        e["armor_t"] = max(0.0, e.get("armor_t", 0.0) - dt)
        e["poise_t"] = e.get("poise_t", 0.0) + dt
        if e["poise_t"] > 2.5:
            e["poise"] = self.poise_max(e)
        e["ait"] = e.get("ait", 0.0) - dt
        dx, dy = self.px - e["x"], self.py - e["y"]
        dist = math.hypot(dx, dy) or 1e-6
        spd = FOE_SPEED.get(e["kind"], 2.1) * (1.0 + min(0.35, 0.012 * self.floor))
        if ai == "stagger":
            e["elunge"] = -0.15
            if e["ait"] <= 0:
                e["ai"], e["acd"], e["elunge"] = "chase", 0.35, 0.0
        elif ai == "chase":
            e["elunge"] = 0.0
            if dist > e["stop"] + 0.12:
                self.foe_approach(e, dt, spd)
            else:
                self.foe_strafe(e, dt, spd * 0.45)
                if e["acd"] <= 0:
                    if self.attackers() < self.max_attackers():
                        e["ai"], e["wind"] = "wind", self.wind_time(e)
                        e["ait"] = e["wind"]
                    else:
                        e["acd"] = 0.25 + random.random() * 0.35
        elif ai == "wind":
            e["elunge"] = -0.22 * (1.0 - max(0.0, e["ait"]) / e["wind"])      # recua antes de bater
            if dist > e["stop"] + 0.35:         # o herói se afastou: acompanha devagar
                self.foe_approach(e, dt, spd * 0.6)
            if e["ait"] <= 0:
                e["ai"], e["ait"], e["hit_done"] = "strike", self.FOE_STRIKE_T, False
                e["aim"] = math.atan2(dy, dx)    # a mira trava aqui: dá para sair do caminho
                e["sx"], e["sy"] = e["x"], e["y"]
                e["elunge"] = 0.0
        elif ai == "strike":
            k = 1.0 - max(0.0, e["ait"]) / self.FOE_STRIKE_T
            ease = math.sin(min(1.0, k) * math.pi / 2)
            self.foe_place(e, e["sx"] + math.cos(e["aim"]) * self.FOE_LUNGE * ease,
                           e["sy"] + math.sin(e["aim"]) * self.FOE_LUNGE * ease)
            if not e.get("hit_done") and k >= 0.45:
                e["hit_done"] = True
                self.enemy_strike(e)
                if self.phase != "fight":
                    return
            if e["ait"] <= 0:
                e["ai"], e["ait"] = "recover", (0.45 if e.get("boss") else 0.60)
        elif ai == "recover":
            e["elunge"] = 0.0
            if e["ait"] <= 0:
                e["ai"] = "chase"
                e["acd"] = max(0.30, 1.2 - 0.03 * self.floor) + random.random() * 0.6
                if (e.get("boss") or e.get("elite")) and random.random() < 0.35 and dist <= e["stop"] + 0.8:
                    e["ai"], e["wind"] = "wind", 0.38        # chefes e elites encadeiam um segundo golpe
                    e["ait"] = e["wind"]

    def stagger_foe(self, e, dur):
        e["ai"], e["ait"] = "stagger", dur
        e["armor_t"] = dur + 1.3                 # depois de atordoar, fica um tempo sem poder ser atordoado de novo
        e["poise"], e["elunge"] = self.poise_max(e), -0.15
        self.float_text("Atordoado!", e["x"], e["y"], e["z"] + 2.0 * e["s"], (255, 214, 120))

    def spawn(self, x, y, z, color, n, power=2.2):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(0.3, 1.0) * power
            self.particles.append({"x": x, "y": y, "z": z, "vx": math.cos(a) * sp, "vy": math.sin(a) * sp,
                                   "vz": random.uniform(1.5, 4.0), "life": random.uniform(0.6, 1.2),
                                   "c": color, "s": random.uniform(0.06, 0.13), "gz": z})

    def float_text(self, s, x, y, z, color):
        px, py = proj(x, y, z)
        self.floaters.append({"s": s, "x": px, "y": py, "life": 1.2, "c": color})

    def hit_foe(self, e, mult=1.0, heavy=False, crit=None, col=(255, 255, 255), poise=None):
        self.streak += 1
        if crit is None:
            crit = random.random() < (self.hero["crit"] + 0.02 * getattr(self, "weapon_lv", 0) + 0.01 * self.attr_bonus("des")
                                  + 0.01 * self.gear_bonus("anel"))
        dmg = max(1, int(round(self.dmg_value() * mult))) * (2 if crit else 1)
        e["hp"] = max(0, e["hp"] - dmg)
        e["flash"] = 1.0 if crit else 0.85
        if crit:
            self.flash_t = 0.22
        self.shake = 11 if heavy else (9 if crit else 7)
        self.spawn(e["x"], e["y"], e["z"] + 0.5, col, 24 if heavy else 18)
        self.float_text(f"-{dmg}", e["x"], e["y"], e["z"] + 1.4 * e["s"], (255, 230, 80))
        if crit:
            self.float_text("CRIT!", e["x"], e["y"], e["z"] + 1.9 * e["s"], (255, 255, 255))
            self.play("crit")
        else:
            self.play("hit")
        if self.streak >= 2:
            self.float_text(f"Sequência x{self.streak}!", self.px, self.py, self.pz + 1.8, (120, 255, 160))
        self.score += 18 + self.floor * 10 + (2 if crit else 0)
        if e["hp"] <= 0:
            self.kill_foe(e)
            return
        # postura: golpes seguidos quebram a guarda e o monstro cambaleia (perde o golpe que estava preparando)
        pd = poise if poise is not None else (2 if heavy else 1) + (1 if crit else 0)
        e["poise"] = e.get("poise", self.poise_max(e)) - pd
        e["poise_t"] = 0.0
        if pd > 0 and e.get("armor_t", 0.0) <= 0 and e["poise"] <= 0:
            self.stagger_foe(e, 0.95 if heavy else 0.70)

    def kill_foe(self, e):
        self.spawn(e["x"], e["y"], e["z"] + 0.6, ENEMY_COLOR[e["kind"]], 40, 3.2)
        self.play("fall")
        e["ai"], e["kt"], e["elunge"] = "dead", 0.0, 0.0
        g_ = random.randint(2, 5) + self.floor // 2
        g_ *= 5 if e.get("boss") else (2 if e.get("elite") else 1)
        g_ = max(1, int(round(g_ * (1.0 + 0.04 * self.attr_bonus("car")))))
        self.gold += g_
        self.float_text(f"+{g_}", e["x"], e["y"], e["z"] + 2.2 * e["s"], (255, 214, 90))
        if self.alive_foes():
            self.pick_lock(force=True)             # ainda tem monstro: a luta continua no próximo alvo
        else:
            self.enemy = e
            self.cur = self.foes.index(e)
            self.lunge = 0.0
            self.swinging = self.heavy = False
            self.phase = "killed"
            self.kt = 0.0

    def enemy_strike(self, e):
        """Momento do golpe do monstro: só acerta quem está no alcance E dentro do cone da mira."""
        d = math.hypot(e["x"] - self.px, e["y"] - self.py)
        arc = 1.35 if e.get("boss") else self.FOE_ARC
        da = abs(angle_diff(math.atan2(self.py - e["y"], self.px - e["x"]), e.get("aim", 0.0)))
        if d > e["stop"] + self.FOE_REACH or da > arc:
            return                                  # errou o herói (ele saiu do caminho)
        if self.rolling and self.roll_t <= self.ROLL_IFR:
            self.float_text("Esquivou!", self.px, self.py, self.pz + 1.5, (120, 220, 255))
            self.play("ok")
            return
        if self.inv_t > 0:
            return
        self.hurt_hero(e)

    def hurt_hero(self, src=None):
        if random.random() < 0.04 * self.armor_lv + 0.01 * self.gear_bonus("armadura"):       # armadura (ferreiro + loot) bloqueia o golpe
            self.inv_t = max(self.inv_t, 0.6)
            self.float_text("Bloqueou!", self.px, self.py, self.pz + 1.5, (190, 200, 230))
            self.spawn(self.px, self.py, self.pz + 0.7, (210, 214, 232), 8)
            self.play("ok")
            return
        self.streak = 0
        self.mistakes += 1
        self.hp = max(0, self.hp - 1)
        self.pflash = 0.3
        self.shake = 9
        self.hurt_t, self.inv_t = 0.38, 1.1
        self.swinging = self.heavy = self.rolling = False
        self.lunge = 0.0
        self.inbuf = None
        if src is not None:
            dx, dy = self.px - src["x"], self.py - src["y"]
            L = math.hypot(dx, dy) or 1.0
            self.kb = (dx / L * 5.5, dy / L * 5.5)
        self.spawn(self.px, self.py, self.pz + 0.5, (230, 70, 70), 12)
        self.float_text("-1 ♥", self.px, self.py, self.pz + 1.4, (255, 90, 90))
        self.play("bad")
        if self.hp <= 0:
            self.best = max(self.best, self.floor)
            self.save_progress()
            self.phase = "dead"
            self.dtm = 0.0
            self.lunge = 0.0

    def treasure_room(self):
        self.room_reward()

    def village_start(self):
        """Chegou ao vilarejo: sem combate e sem recompensa. No AUTO o herói segue a trilha de terra até o poço
        da masmorra; no MANUAL você anda à vontade e entra no poço quando quiser."""
        self.enemy = None
        self.stairs = self.lay["stairs"]
        self.smith_done, self.smith_t = False, 0.0
        self.market_done, self.mk_t = not (self.gold >= 30 or self.bag), 0.0      # no AUTO só passa no mercado se tiver o que comprar/vender
        # no AUTO o herói passa primeiro no ferreiro (a loja abre sozinha) e só depois segue para o poço
        self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), self.lay["smith"])
        self.phase = "stairs"

    # ------------------------------------------------------------ FERREIRO (melhorar equipamento)
    def smith_near(self):
        if not self.lay.get("village") or self.smith_open or self.phase not in ("stairs", "mp"):
            return False
        nx, ny = self.lay["smith_npc"]
        return math.hypot(self.px - nx, self.py - ny) < 1.9

    def open_smith(self):
        self.smith_open, self.smith_done = True, True
        self.smith_sel, self.smith_msg, self.smith_msg_t = 0, "", 0.0
        self.moving, self.spd = False, 0.0
        nx, ny = self.lay["smith_npc"]
        self.hd = math.atan2(ny - self.py, nx - self.px)          # o herói olha para o ferreiro
        self.face = (math.cos(self.hd), math.sin(self.hd))
        self.play("card")

    def close_smith(self):
        self.smith_open = False
        if not self.manual() and self.phase == "stairs" and self.stairs:
            tgt = self.stairs if self.market_done else self.lay["market"]          # depois do ferreiro, o mercado (se houver o que fazer)
            self.waypoints = self.find_path((self.px, self.py), tgt)

    def smith_say(self, s):
        self.smith_msg, self.smith_msg_t = s, self.ui_t + 2.4

    def smith_buy(self, kind):
        lv = self.weapon_lv if kind == 0 else self.armor_lv
        if lv >= FORGE_MAX:
            self.smith_say("Já está no nível máximo!")
            self.play("bad")
            return
        cost = FORGE_COST[kind][lv]
        if self.gold < cost:
            self.smith_say(f"Faltam {cost - self.gold} de ouro.")
            self.play("bad")
            return
        self.gold -= cost
        if kind == 0:
            self.weapon_lv += 1
            self.smith_say("Arma melhorada!")
        else:
            gain = forge_hearts(lv + 1) - forge_hearts(lv)
            self.armor_lv += 1
            if gain:
                self.maxhp += gain
                self.hp += gain
            self.smith_say("Armadura melhorada!" + ("  +1 coração!" if gain else ""))
        self.save_progress()
        self.play("crit")
        self.flash_t = 0.12

    def smith_key(self, key):
        if key == pygame.K_F11:
            self.toggle_fs()
        elif key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_BACKSPACE, pygame.K_q):
            self.close_smith()
        elif key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
            self.smith_sel = 0
        elif key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
            self.smith_sel = 1
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.smith_buy(self.smith_sel)

    SMITH_PANEL = pygame.Rect(110, 40, 740, 530)

    def smith_card_rect(self, i):
        return pygame.Rect(140 + i * 350, 196, 320, 262)

    def smith_btn_rect(self, i):
        r = self.smith_card_rect(i)
        return pygame.Rect(r.x + 20, r.bottom - 60, r.w - 40, 44)

    def smith_exit_rect(self):
        return pygame.Rect(W // 2 - 100, 494, 200, 46)

    def smith_click(self, pos):
        if self.smith_exit_rect().collidepoint(pos):
            self.close_smith()
            return
        for i in (0, 1):
            if self.smith_btn_rect(i).collidepoint(pos):
                self.smith_sel = i
                self.smith_buy(i)
                return
            if self.smith_card_rect(i).collidepoint(pos):
                self.smith_sel = i
                return

    # ------------------------------------------------------------ MERCADO (comprar e vender equipamento)
    MK_PANEL = pygame.Rect(110, 24, 740, 572)
    MK_COLS = 8

    def market_near(self):
        if not self.lay.get("village") or self.mk_open or self.smith_open or self.phase not in ("stairs", "mp"):
            return False
        nx, ny = self.lay["market_npc"]
        return math.hypot(self.px - nx, self.py - ny) < 2.1

    def open_market(self):
        self.mk_open, self.market_done = True, True
        self.mk_tab, self.mk_i = 0, 0
        self.moving, self.spd = False, 0.0
        nx, ny = self.lay["market_npc"]
        self.hd = math.atan2(ny - self.py, nx - self.px)          # o herói olha para o mercador
        self.face = (math.cos(self.hd), math.sin(self.hd))
        self.mk_say("Bem-vindo, viajante! Veja as mercadorias.")
        self.play("card")

    def close_market(self):
        self.mk_open = False
        if not self.manual() and self.phase == "stairs" and self.stairs:
            self.waypoints = self.find_path((self.px, self.py), self.stairs)       # segue para o poço
        self.save_progress()

    def mk_say(self, s_):
        self.mk_msg, self.mk_msg_t = s_, self.ui_t + 2.6

    def mk_items(self):
        return self.mk_stock if self.mk_tab == 0 else self.bag

    def mk_selected(self):
        its = self.mk_items()
        return its[self.mk_i] if 0 <= self.mk_i < len(its) else None

    def mk_switch(self, tab):
        self.mk_tab, self.mk_i = tab, 0
        self.play("card")

    def mk_act(self):
        it = self.mk_selected()
        if it is None:
            self.play("bad")
            return
        if self.mk_tab == 0:                                       # COMPRAR
            if it["sold"]:
                self.mk_say("Essa peça já foi vendida.")
                self.play("bad")
                return
            if len(self.bag) >= BAG_MAX:
                self.mk_say("Mochila cheia! Venda alguma coisa primeiro.")
                self.play("bad")
                return
            if self.gold < it["price"]:
                self.mk_say(f"Faltam {it['price'] - self.gold} de ouro.")
                self.play("bad")
                return
            self.gold -= it["price"]
            it["sold"] = True
            self.bag.append({k_: it[k_] for k_ in ("slot", "rarity", "bonus", "name")})
            self.mk_say(f"Comprou {it['name']}   -{it['price']} ouro   ([I] para equipar)")
            self.play("crit")
        else:                                                      # VENDER
            v = loot_value(it, self.floor, self.attr_bonus("car"))
            self.bag.pop(self.mk_i)
            self.gold += v
            self.mk_i = min(self.mk_i, max(0, len(self.bag) - 1))
            self.mk_say(f"Vendeu {it['name']}   +{v} ouro")
            self.play("card")
        self.save_progress()

    def mk_key(self, key):
        n = len(self.mk_items())
        c = self.MK_COLS
        if key == pygame.K_F11:
            self.toggle_fs()
        elif key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q, pygame.K_BACKSPACE):
            self.close_market()
        elif key in (pygame.K_TAB, pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            self.mk_switch(1 - self.mk_tab)
        elif key in (pygame.K_LEFT, pygame.K_a):
            self.mk_i = max(0, self.mk_i - 1)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.mk_i = min(max(0, n - 1), self.mk_i + 1)
        elif key in (pygame.K_UP, pygame.K_w):
            self.mk_i = max(0, self.mk_i - c)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.mk_i = min(max(0, n - 1), self.mk_i + c)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.mk_act()

    def mk_cell_rect(self, i):
        return pygame.Rect(140 + (i % self.MK_COLS) * 86, 178 + (i // self.MK_COLS) * 86, 78, 78)

    def mk_tab_rect(self, t_):
        return pygame.Rect(W // 2 - 210 + t_ * 220, 108, 200, 38)

    def mk_box_rect(self):
        return pygame.Rect(130, 446, 700, 76)

    def mk_act_rect(self):
        b = self.mk_box_rect()
        return pygame.Rect(b.right - 200, b.y + 14, 186, 48)

    def mk_exit_rect(self):
        return pygame.Rect(W // 2 - 90, 534, 180, 40)

    def mk_click(self, pos):
        if self.mk_exit_rect().collidepoint(pos):
            self.close_market()
            return
        for t_ in (0, 1):
            if self.mk_tab_rect(t_).collidepoint(pos):
                if self.mk_tab != t_:
                    self.mk_switch(t_)
                return
        if self.mk_act_rect().collidepoint(pos):
            self.mk_act()
            return
        for i in range(len(self.mk_items())):
            if self.mk_cell_rect(i).collidepoint(pos):
                self.mk_i = i
                return

    def draw_market_hint(self):
        """Etiqueta 'MERCADO' sobre o mercador e, perto dele, o aviso [E] para abrir a loja."""
        self.mk_hint = None
        if not self.lay.get("village") or self.phase not in ("stairs", "descend", "mp") or self.settings_open:
            return
        nx, ny = self.lay["market_npc"]
        px_, py_ = proj(nx, ny - 0.1, 2.15, self.cam)
        self.ptext("MERCADO", 11, (150, 232, 170), (px_, py_), 2)
        if self.phase in ("stairs", "mp") and self.market_near() and not self.mk_open:
            pulse = 0.5 + 0.5 * math.sin(self.ui_t * 5)
            r = pygame.Rect(0, 0, 250, 34)
            r.center = (int(px_), int(py_) - 26)
            r.clamp_ip(pygame.Rect(6, 6, W - 12, H - 12))
            self.rrect(r, (14, 34, 24, 235), 14, 2, mix((90, 200, 130), pulse * 0.6))
            self.text("[E]  COMPRAR E VENDER", 21, (214, 255, 226), r.center, shadow=False)
            self.mk_hint = r

    def draw_market(self):
        scr = self.screen
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 205))
        scr.blit(dim, (0, 0))
        panel = self.MK_PANEL
        self.rrect(panel.inflate(14, 14), (240, 190, 70, 24), 34)
        self.rrect(panel, (18, 14, 10, 252), 28, 4, (196, 150, 70, 255))
        self.otext("MERCADO", 46, (255, 222, 150), (W // 2, panel.y + 38), ink=(96, 56, 14), ow=3)
        self.text(f"OURO:  {self.gold}", 24, (255, 224, 120), (W // 2, panel.y + 74), shadow=False)
        pulse = 0.5 + 0.5 * math.sin(self.ui_t * 6)
        gold_sel = mix((255, 226, 130), 0.5 * pulse, (255, 255, 255))
        for t_, lab in enumerate(("COMPRAR", "VENDER")):
            r = self.mk_tab_rect(t_)
            on = self.mk_tab == t_
            self.rrect(r, (92, 62, 24, 255) if on else (34, 26, 18, 255), 14, 3, (240, 196, 100, 255) if on else (84, 66, 44, 255))
            self.text(lab, 24, (255, 240, 200) if on else (150, 134, 110), r.center, shadow=False)
        if self.mk_msg and self.ui_t < self.mk_msg_t:
            self.text(self.mk_msg, 20, (255, 236, 170), (W // 2, 162), shadow=False)
        its = self.mk_items()
        if not its:
            self.text("Sua mochila está vazia." if self.mk_tab else "Sem mercadoria.", 24, (140, 128, 110), (W // 2, 300), shadow=False)
        car = self.attr_bonus("car")
        for i, it in enumerate(its):
            r = self.mk_cell_rect(i)
            sold = bool(it.get("sold", False))
            sel = self.mk_i == i
            col = (70, 64, 58) if sold else RARITY_COLORS[it["rarity"]]
            self.rrect(r, (44, 34, 22, 255) if sel else (26, 20, 14, 255), 12, 2, (76, 62, 44, 255))
            inner = r.inflate(-10, -10)
            self.rrect(inner, (*shade(col, 0.22), 255), 10, 3, (*col, 255))
            self.text(LOOT_LETTER[it["slot"]], 28, col, (inner.centerx, inner.centery - 8), shadow=False)
            if sold:
                lab = "VENDIDO"
            elif self.mk_tab == 0:
                lab = str(it["price"])
            else:
                lab = "+" + str(loot_value(it, self.floor, car))
            self.text(lab, 14, (120, 110, 100) if sold else (255, 224, 120), (inner.centerx, inner.bottom - 12), shadow=False)
            if sel:
                pygame.draw.rect(scr, gold_sel, r.inflate(6, 6), 3, border_radius=14)
        # detalhe do item selecionado + botão de comprar / vender
        box = self.mk_box_rect()
        self.rrect(box, (28, 22, 16, 255), 16, 3, (96, 76, 48, 255))
        it = self.mk_selected()
        btn = self.mk_act_rect()
        if it:
            sl, col = it["slot"], RARITY_COLORS[it["rarity"]]
            self.text(it["name"], 26, col, (box.x + 16, box.y + 8), center=False, shadow=False)
            self.text(f"{RARITY_NAMES[it['rarity']]}  ·  {LOOT_LABEL[sl]}  ·  +{it['bonus']} {LOOT_UNIT[sl]}", 19,
                      (214, 226, 240), (box.x + 16, box.y + 42), center=False, shadow=False)
            cur = self.gear.get(sl)
            if cur:
                diff = it["bonus"] - cur["bonus"]
                cmp_t = f"vs equipado: {'+' if diff >= 0 else ''}{diff}"
                cmp_c = (140, 230, 160) if diff > 0 else ((230, 150, 150) if diff < 0 else (190, 190, 200))
            else:
                cmp_t, cmp_c = "slot vazio", (140, 230, 160)
            self.text(cmp_t, 17, cmp_c, (box.x + 380, box.y + 44), center=False, shadow=False)
            if self.mk_tab == 0:
                if it["sold"]:
                    self.rrect(btn, (44, 40, 36, 255), 14, 3, (96, 90, 84, 255))
                    self.text("VENDIDO", 24, (140, 130, 120), btn.center, shadow=False)
                else:
                    can = self.gold >= it["price"] and len(self.bag) < BAG_MAX
                    self.rrect(btn, (36, 110, 64, 255) if can else (84, 40, 40, 255), 14, 3, (150, 255, 190, 255) if can else (200, 120, 120, 255))
                    self.text(f"COMPRAR  {it['price']}", 24, (255, 255, 255) if can else (230, 180, 180), btn.center, shadow=False)
            else:
                v = loot_value(it, self.floor, car)
                self.rrect(btn, (90, 70, 30, 255), 14, 3, (230, 190, 90, 255))
                self.text(f"VENDER  +{v}", 24, (255, 236, 170), btn.center, shadow=False)
        else:
            self.text("Nada aqui. Selecione um item.", 22, (120, 116, 136), (box.x + 16, box.y + 26), center=False, shadow=False)
        eb = self.mk_exit_rect()
        self.rrect(eb, (40, 30, 20, 255), 12, 3, (200, 160, 100, 255))
        self.text("SAIR", 26, (255, 240, 220), eb.center, shadow=False)
        self.text("SETAS / WASD  mover      TAB  trocar aba      ENTER  comprar / vender      ESC  sair", 16,
                  (140, 130, 118), (W // 2, panel.bottom - 12), shadow=False)

    def draw_smith_hint(self):
        """Etiqueta 'FERREIRO' sobre a forja e, perto dele, o aviso [E] para abrir a loja."""
        self.smith_hint = None
        if not self.lay.get("village") or self.phase not in ("stairs", "descend", "mp") or self.settings_open:
            return
        nx, ny = self.lay["smith_npc"]
        px_, py_ = proj(nx, ny - 0.1, 2.35, self.cam)
        self.ptext("FERREIRO", 11, (255, 196, 110), (px_, py_), 2)
        if self.phase in ("stairs", "mp") and self.smith_near() and not self.smith_open:
            pulse = 0.5 + 0.5 * math.sin(self.ui_t * 5)
            r = pygame.Rect(0, 0, 250, 34)
            r.center = (int(px_), int(py_) - 26)
            r.clamp_ip(pygame.Rect(6, 6, W - 12, H - 12))
            self.rrect(r, (36, 24, 14, 235), 14, 2, mix((226, 160, 80), pulse * 0.6))
            self.text("[E]  MELHORAR EQUIPAMENTO", 21, (255, 236, 200), r.center, shadow=False)
            self.smith_hint = r

    def draw_smith(self):
        scr = self.screen
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 205))
        scr.blit(dim, (0, 0))
        panel = self.SMITH_PANEL
        self.rrect(panel.inflate(14, 14), (255, 110, 20, 26), 34)
        self.rrect(panel, (14, 9, 7, 252), 28, 4, (122, 82, 50, 255))
        self.otext("FERREIRO", 54, (255, 214, 150), (W // 2, panel.y + 46), ink=(104, 38, 10), ow=3)
        self.text("Melhore seu equipamento com o ouro que você junta na masmorra.", 22, (186, 168, 150),
                  (W // 2, panel.y + 92), shadow=False)
        self.text(f"OURO:  {self.gold}", 34, (255, 224, 120), (W // 2, panel.y + 124))
        hid = self.hero["id"]
        for i in (0, 1):
            r = self.smith_card_rect(i)
            sel = self.smith_sel == i
            lv = self.weapon_lv if i == 0 else self.armor_lv
            self.chunky(r, (40, 28, 22) if sel else (28, 20, 18), (220, 160, 90) if sel else (110, 80, 60), 18, 4, 4)
            self.otext("ARMA" if i == 0 else "ARMADURA", 30, (255, 236, 200), (r.centerx, r.y + 30), ow=2)
            nm = FORGE_WEAPON.get(hid, "Arma") if i == 0 else FORGE_ARMOR.get(hid, "Armadura")
            self.text(f"{nm} {FORGE_TIER[lv]}", 25, (255, 214, 130), (r.centerx, r.y + 66), shadow=False)
            for k in range(FORGE_MAX):                                  # 5 quadradinhos de nível
                q = pygame.Rect(0, 0, 30, 14)
                q.center = (r.centerx + (k - 2) * 38, r.y + 98)
                on = k < lv
                self.rrect(q, (255, 190, 80, 255) if on else (50, 40, 36, 255), 4, 2, (255, 230, 150, 255) if on else (90, 70, 56, 255))
            self.text(forge_stats(i, lv), 22, (214, 226, 240), (r.centerx, r.y + 134), shadow=False)
            b = self.smith_btn_rect(i)
            if lv >= FORGE_MAX:
                self.text("NÍVEL MÁXIMO", 24, (255, 214, 130), (r.centerx, r.y + 170), shadow=False)
                self.rrect(b, (60, 50, 30, 255), 14, 3, (200, 160, 80, 255))
                self.text("COMPLETO", 26, (255, 224, 150), b.center, shadow=False)
                continue
            cost = FORGE_COST[i][lv]
            can = self.gold >= cost
            self.text("Próximo:  " + forge_stats(i, lv + 1), 20, (140, 230, 160), (r.centerx, r.y + 170), shadow=False)
            self.rrect(b, (36, 110, 64, 255) if can else (84, 40, 40, 255), 14, 3, (150, 255, 190, 255) if can else (190, 90, 90, 255))
            self.text(f"MELHORAR  -  {cost} ouro", 24, (255, 255, 255) if can else (230, 180, 180), b.center, shadow=False)
        eb = self.smith_exit_rect()
        self.rrect(eb, (40, 36, 70, 255), 16, 3, (150, 165, 230, 255))
        self.text("SAIR", 28, (240, 246, 255), eb.center, shadow=False)
        if self.smith_msg and self.ui_t < self.smith_msg_t:
            self.text(self.smith_msg, 26, (255, 236, 170), (W // 2, 476))
        self.text("← →  escolher      ENTER  melhorar      ESC / E  sair", 20, (140, 130, 118),
                  (W // 2, panel.bottom - 16), shadow=False)

    # ------------------------------------------------------------ INVENTÁRIO (equipar / desequipar loot)
    INV_PANEL = pygame.Rect(60, 30, 840, 570)
    INV_COLS = 6

    def inv_slot_rect(self, i):
        return pygame.Rect(90, 150 + i * 78, 330, 68)

    def inv_cell_rect(self, i):
        r, c = divmod(i, self.INV_COLS)
        return pygame.Rect(450 + c * 64, 150 + r * 64, 56, 56)

    def inv_equip_btn(self):
        return pygame.Rect(528, 479, 180, 44)

    def inv_sell_btn(self):
        return pygame.Rect(716, 479, 104, 44)

    def inv_exit_rect(self):
        return pygame.Rect(838, 44, 48, 40)

    def inv_hud_rect(self):
        return pygame.Rect(12, 118, 4 * 32 - 4, 28)

    def inv_say(self, s):
        self.inv_msg, self.inv_msg_t = s, self.ui_t + 2.4

    def open_inv(self):
        if self.inv_open or self.phase in MENU_PHASES or self.phase in ("dead", "gameover"):
            return
        self.inv_open, self.inv_msg, self.inv_msg_t = True, "", 0.0
        self.inv_area, self.inv_i = ("bag", 0) if self.bag else ("slot", 0)
        self.play("card")

    def close_inv(self):
        self.inv_open = False
        self.play("card")

    def inv_selected(self):
        if self.inv_area == "slot":
            return self.gear.get(LOOT_SLOTS[self.inv_i])
        return self.bag[self.inv_i] if self.inv_i < len(self.bag) else None

    def inv_equip(self, idx):
        it = self.bag[idx]
        old = self.gear.get(it["slot"])
        self.gear[it["slot"]] = it
        if old:
            self.bag[idx] = old                        # o item que estava equipado ocupa o lugar do novo
        else:
            del self.bag[idx]
        self.inv_say(f"Equipou {it['name']}" + (f"  (guardou {old['name']})" if old else ""))
        self.play("crit")

    def inv_unequip(self, slot):
        it = self.gear.get(slot)
        if not it:
            self.play("bad")
            return
        if len(self.bag) >= BAG_MAX:
            self.inv_say("Mochila cheia! Venda ou equipe algum item.")
            self.play("bad")
            return
        del self.gear[slot]
        self.bag.append(it)
        self.inv_say(f"Desequipou {it['name']}")
        self.play("card")

    def inv_sell(self):
        if self.inv_area != "bag" or self.inv_i >= len(self.bag):
            self.play("bad")
            return
        it = self.bag.pop(self.inv_i)
        v = loot_value(it, self.floor, self.attr_bonus("car"))
        self.gold += v
        self.inv_say(f"Vendeu {it['name']}   +{v} ouro")
        self.play("card")
        self.save_progress()

    def inv_act(self):
        """Equipa o item da mochila ou desequipa o item do slot, conforme o que está selecionado."""
        if self.inv_area == "slot":
            self.inv_unequip(LOOT_SLOTS[self.inv_i])
        elif self.inv_i < len(self.bag):
            self.inv_equip(self.inv_i)
        else:
            self.play("bad")

    def inv_move(self, dx, dy):
        if self.inv_area == "slot":
            if dx > 0:
                self.inv_area, self.inv_i = "bag", min(self.inv_i, 3) * self.INV_COLS
            elif dy:
                self.inv_i = (self.inv_i + dy) % 4
            return
        r, c = divmod(self.inv_i, self.INV_COLS)
        if dx < 0 and c == 0:
            self.inv_area, self.inv_i = "slot", min(r, 3)
            return
        rows = BAG_MAX // self.INV_COLS
        c = max(0, min(self.INV_COLS - 1, c + dx))
        r = max(0, min(rows - 1, r + dy))
        self.inv_i = r * self.INV_COLS + c

    def inv_key(self, key):
        if key == pygame.K_F11:
            self.toggle_fs()
        elif key in (pygame.K_ESCAPE, pygame.K_i, pygame.K_q, pygame.K_BACKSPACE):
            self.close_inv()
        elif key in (pygame.K_LEFT, pygame.K_a):
            self.inv_move(-1, 0)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.inv_move(1, 0)
        elif key in (pygame.K_UP, pygame.K_w):
            self.inv_move(0, -1)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.inv_move(0, 1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
            self.inv_act()
        elif key in (pygame.K_v, pygame.K_DELETE):
            self.inv_sell()

    def inv_click(self, pos):
        if self.inv_exit_rect().collidepoint(pos):
            self.close_inv()
            return
        if self.inv_equip_btn().collidepoint(pos):
            self.inv_act()
            return
        if self.inv_sell_btn().collidepoint(pos):
            self.inv_sell()
            return
        for i in range(4):
            if self.inv_slot_rect(i).collidepoint(pos):
                same = self.inv_area == "slot" and self.inv_i == i
                self.inv_area, self.inv_i = "slot", i
                if same:
                    self.inv_act()                 # clicar de novo no item selecionado equipa/desequipa
                return
        for i in range(BAG_MAX):
            if self.inv_cell_rect(i).collidepoint(pos):
                same = self.inv_area == "bag" and self.inv_i == i
                self.inv_area, self.inv_i = "bag", i
                if same and i < len(self.bag):
                    self.inv_act()
                return

    def draw_inventory(self):
        scr = self.screen
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 205))
        scr.blit(dim, (0, 0))
        panel = self.INV_PANEL
        self.rrect(panel.inflate(14, 14), (90, 140, 255, 24), 34)
        self.rrect(panel, (12, 10, 18, 252), 28, 4, (84, 92, 140, 255))
        self.otext("INVENTÁRIO", 50, (214, 226, 255), (W // 2, panel.y + 40), ink=(24, 30, 70), ow=3)
        self.text(f"OURO:  {self.gold}", 26, (255, 224, 120), (W // 2, panel.y + 82), shadow=False)
        self.text("EQUIPADO", 22, (160, 170, 200), (90 + 165, 134), shadow=False)
        self.text(f"MOCHILA   {len(self.bag)}/{BAG_MAX}", 22, (160, 170, 200), (450 + 188, 134), shadow=False)
        pulse = 0.5 + 0.5 * math.sin(self.ui_t * 6)
        gold_sel = mix((255, 226, 130), 0.5 * pulse, (255, 255, 255))

        def icon_box(r, it, sl):
            col = RARITY_COLORS[it["rarity"]] if it else (70, 66, 84)
            self.rrect(r, (*shade(col, 0.22), 255) if it else (30, 28, 40, 255), 10, 3, (*col, 255))
            self.text(LOOT_LETTER[sl], 26, col, r.center, shadow=False)

        for i, sl in enumerate(LOOT_SLOTS):                       # slots equipados
            r = self.inv_slot_rect(i)
            sel = self.inv_area == "slot" and self.inv_i == i
            it = self.gear.get(sl)
            self.chunky(r, (36, 32, 52) if sel else (24, 22, 34), None, 14, 3, 3)
            if sel:
                pygame.draw.rect(scr, gold_sel, r.inflate(8, 8), 3, border_radius=16)
            icon_box(pygame.Rect(r.x + 8, r.y + 8, 52, 52), it, sl)
            self.text(LOOT_LABEL[sl], 15, (140, 140, 164), (r.x + 72, r.y + 8), center=False, shadow=False)
            if it:
                col = RARITY_COLORS[it["rarity"]]
                self.text(it["name"], 20, col, (r.x + 72, r.y + 26), center=False, shadow=False)
                self.text(f"{RARITY_NAMES[it['rarity']]}   +{it['bonus']} {LOOT_UNIT[sl]}", 17, (214, 226, 240),
                          (r.x + 72, r.y + 47), center=False, shadow=False)
            else:
                self.text("— vazio —", 20, (96, 92, 112), (r.x + 72, r.y + 32), center=False, shadow=False)
        for i in range(BAG_MAX):                                  # mochila
            r = self.inv_cell_rect(i)
            sel = self.inv_area == "bag" and self.inv_i == i
            it = self.bag[i] if i < len(self.bag) else None
            self.rrect(r, (34, 30, 50, 255) if sel else (22, 20, 32, 255), 10, 2, (60, 56, 76, 255))
            if it:
                icon_box(r.inflate(-6, -6), it, it["slot"])
            if sel:
                pygame.draw.rect(scr, gold_sel, r.inflate(6, 6), 3, border_radius=12)
        # detalhe do item selecionado + botões
        box = pygame.Rect(90, 466, 736, 70)
        self.rrect(box, (22, 20, 34, 255), 16, 3, (60, 56, 84, 255))
        it = self.inv_selected()
        eq_btn, sell_btn = self.inv_equip_btn(), self.inv_sell_btn()
        if it:
            sl, col = it["slot"], RARITY_COLORS[it["rarity"]]
            self.text(it["name"], 26, col, (box.x + 16, box.y + 8), center=False, shadow=False)
            line = f"{RARITY_NAMES[it['rarity']]}  ·  {LOOT_LABEL[sl]}  ·  +{it['bonus']} {LOOT_UNIT[sl]}"
            self.text(line, 19, (214, 226, 240), (box.x + 16, box.y + 40), center=False, shadow=False)
            if self.inv_area == "bag":
                cur = self.gear.get(sl)
                if cur:
                    diff = it["bonus"] - cur["bonus"]
                    cmp_t = f"vs atual: {'+' if diff >= 0 else ''}{diff}"
                    cmp_c = (140, 230, 160) if diff > 0 else ((230, 150, 150) if diff < 0 else (190, 190, 200))
                else:
                    cmp_t, cmp_c = "slot vazio", (140, 230, 160)
                self.text(cmp_t, 17, cmp_c, (box.x + 330, box.y + 42), center=False, shadow=False)
                self.rrect(eq_btn, (36, 110, 64, 255), 14, 3, (150, 255, 190, 255))
                self.text("EQUIPAR", 26, (255, 255, 255), eq_btn.center, shadow=False)
                v = loot_value(it, self.floor, self.attr_bonus("car"))
                self.rrect(sell_btn, (90, 70, 30, 255), 14, 3, (230, 190, 90, 255))
                self.text(f"VENDER +{v}", 18, (255, 236, 170), sell_btn.center, shadow=False)
            else:
                self.text("equipado", 19, (140, 190, 255), (box.x + 330, box.y + 40), center=False, shadow=False)
                self.rrect(eq_btn, (84, 52, 40, 255), 14, 3, (230, 150, 110, 255))
                self.text("DESEQUIPAR", 24, (255, 240, 230), eq_btn.center, shadow=False)
        else:
            self.text("Nada aqui. Selecione um item.", 22, (120, 116, 136), (box.x + 16, box.y + 24), center=False, shadow=False)
        xb = self.inv_exit_rect()
        self.rrect(xb, (40, 36, 70, 255), 12, 3, (150, 165, 230, 255))
        self.text("X", 28, (240, 246, 255), xb.center, shadow=False)
        if self.inv_msg and self.ui_t < self.inv_msg_t:
            self.text(self.inv_msg, 22, (255, 236, 170), (W // 2, 556))
        self.text("SETAS / WASD  mover      ENTER  equipar / desequipar      V  vender      ESC / I  fechar", 18,
                  (140, 130, 118), (W // 2, panel.bottom - 16), shadow=False)

    def room_reward(self):
        """Sala limpa: ouro e pontos (sem cartas) e segue direto para a escada."""
        k = getattr(self, "room_kind", "")
        gold = 6 + self.floor * 2
        if k == "elite":
            self.score += 120
            gold *= 2
        elif k == "tesouro":
            gold = 25 + self.floor * 4
            if self.hp < self.maxhp:
                self.hp += 1
                self.float_text("+1 ♥", self.px, self.py, self.pz + 2.0, (255, 120, 140))
        elif k == "boss":
            gold *= 4
        gold = int(round(gold * (1.0 + 0.04 * self.attr_bonus("car"))))
        self.gold += gold
        self.score += 80
        self.float_text(f"+{gold} ouro", self.px, self.py, self.pz + 1.6, (255, 224, 120))
        if k in ("tesouro", "boss"):                       # loot só em sala do tesouro ou depois de um chefe
            self.give_loot(boss=(k == "boss"))
        self.play("card")
        self.continue_after_card()

    def give_loot(self, boss=False):
        it = make_loot(self.floor, boss)
        col, rn = RARITY_COLORS[it["rarity"]], RARITY_NAMES[it["rarity"]]
        if len(self.bag) < BAG_MAX:
            self.bag.append(it)                             # vai para a mochila; equipe pelo inventário (tecla I)
            msg = f"{rn.upper()}: {it['name']}  -  [I] INVENTARIO"
        else:                                               # mochila cheia: vende na hora
            sell = loot_value(it, self.floor, self.attr_bonus("car"))
            self.gold += sell
            msg = f"{rn}: {it['name']} vendido (mochila cheia) +{sell} ouro"
        self.float_text(f"{rn.upper()}!", self.px, self.py, self.pz + 2.4, col)
        self.banner, self.banner_t = msg, 3.5
        self.score += 40 * (it["rarity"] + 1)
        self.save_progress()

    def respawn(self):
        self.phase = "title"
        self.banner, self.banner_t = "", 0.0

    # -------------------------------------------------------------- update
    def music_tick(self):
        """Toca a trilha em loop: começa quando fica pronta, abaixa no Game Over, N liga/desliga."""
        try:
            if self.music_sound is None:
                data = self._music_box.get("data")
                if data is None or not pygame.mixer.get_init():
                    return
                self.music_sound = pygame.mixer.Sound(buffer=data)
                self.music_channel = pygame.mixer.Channel(0)
                self.music_channel.set_volume(0.0)
                self.music_channel.play(self.music_sound, loops=-1)
                self.music_channel.set_volume(0.0)
            want = 0.0 if not self.music_on else (0.22 if self.phase == "gameover" else 0.3 if self.phase == "bossintro" else 0.55) * self.cfg["music_vol"]
            cur = self.music_channel.get_volume()
            self.music_channel.set_volume(cur + (want - cur) * 0.08)
        except Exception:
            pass

    def turn_foes(self, dt):
        """Os monstros giram suavemente para ficar de frente para o jogador."""
        for e in self.foes:
            if e["kind"] in NO_TURN or e["hp"] <= 0 or e.get("ai") == "strike":
                continue
            goal = math.atan2(self.py - e["y"], self.px - e["x"])
            cur = e.get("hd")
            if cur is None:
                e["hd"] = goal
                continue
            d = angle_diff(goal, cur)
            e["hd"] = (cur + d * (1.0 - math.exp(-7.0 * dt)) + math.pi) % math.tau - math.pi

    def update_village_npcs(self, dt):
        pos = [(n["x"], n["y"]) for n in self.vnpcs]
        for k, n in enumerate(self.vnpcs):
            npc_step(n, dt, (self.px, self.py), pos[:k] + pos[k + 1:], self.blocked, self.solids_static, self.npc_rng, N)
            pos[k] = (n["x"], n["y"])
            f = n.get("face")
            if f is not None:                           # gira o corpo suavemente para onde anda / para o herói
                n["ang"] += ((f - HERO_FRONT - n["ang"] + math.pi) % math.tau - math.pi) * min(1.0, dt * 6.0)
        r = NPC_RAD                                     # cada aldeão é um obstáculo para o herói
        self.solids = self.solids_static + [(n["x"] - r, n["y"] - r, n["x"] + r, n["y"] + r) for n in self.vnpcs]

    def update(self, dt):
        self.t += dt
        self.dt_last = dt
        if self.vnpcs and self.lay.get("village"):
            self.update_village_npcs(dt)
        self.fc_k += ((1.0 if self.phase == "fight" else 0.0) - self.fc_k) * min(1.0, dt * 5.0)     # câmera trava/solta
        if self.phase != "fight" and self.fc_k < 0.003:
            self.fc_k = 0.0
        self.turn_foes(dt)
        self.banner_t = max(0, self.banner_t - dt)
        self.shake = max(0, self.shake - dt * 25)
        self.cam = (random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake) if (self.shake > 0.3 and self.cfg["shake"]) else (0, 0)

        if self.transition is not None:
            self.transition["time"] += dt
            if self.transition["time"] >= self.transition["duration"]:
                kind = self.transition["kind"]
                self.transition = None
                if kind == "dark":
                    self.advance_floor()
                elif kind == "red":
                    self.phase = "gameover"
            return

        if self.phase not in ("stairs", "descend", "gameover", "title", "dead") and self.enemy is None:
            self.enemy = self.foes[self.cur] if self.foes and self.cur < len(self.foes) else (self.foes[-1] if self.foes else None)

        for fo in self.foes:
            fo["flash"] = max(0, fo["flash"] - dt)
            if fo["hp"] <= 0 and fo.get("ai") == "dead":      # monstro derrotado some aos poucos
                fo["kt"] = fo.get("kt", 0.0) + dt
                fo["scale"] = max(0.0, 1 - fo["kt"] / 0.5)
        e = self.enemy
        self.pflash = max(0, self.pflash - dt)
        self.land_t = max(0.0, getattr(self, "land_t", 0.0) - dt)
        self.flash_t = max(0.0, getattr(self, "flash_t", 0.0) - dt)
        for p in self.particles:
            p["life"] -= dt
            p["vz"] -= 12 * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["z"] += p["vz"] * dt
            gz = ground(p["x"], p["y"], self.duplo)
            if p["z"] < gz:
                p["z"] = gz
                p["vz"] *= -0.35
                p["vx"] *= 0.6
                p["vy"] *= 0.6
        self.particles = [p for p in self.particles if p["life"] > 0]
        for f in self.floaters:
            f["life"] -= dt
            f["y"] -= 38 * dt
        self.floaters = [f for f in self.floaters if f["life"] > 0]
        self.update_fx(dt)
        e = self.enemy
        if self.phase == "mp":
            self.mp_update(dt)
            return

        ph = self.phase
        self.moving = False
        self.steered = False
        hd0 = self.hd
        gnd = ground(self.px, self.py, self.duplo)
        if ph == "arrive":
            self.pt += dt
            k = min(1, self.pt / 0.7)
            self.pz = gnd + 5.0 * (1 - k) ** 2
            if k >= 1:
                self.pz = gnd
                self.shake = 5
                self.spawn(self.px, self.py, gnd + 0.1, (200, 200, 200), 8, 1.5)
                self.land_t = 0.3
                if not self.foes:
                    if self.lay.get("village"):
                        self.village_start()
                    else:
                        self.treasure_room()
                else:
                    self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), (e["x"], e["y"]), e)
                    if e is not None and e.get("boss"):
                        self.start_boss_intro()
                    else:
                        self.phase = "walk"
        else:
            self.pz += (gnd - self.pz) * min(1.0, dt * 15)

        if ph == "walk" and self.noticed():       # um monstro notou o herói: luta livre, em tempo real
            self.moving = False
            self.start_combat()
        elif ph == "walk" and self.manual():
            self.walk_manual(dt)
        elif ph == "walk":
            self.moving = True
            if self.waypoints:
                wx, wy = self.waypoints[0]
                if math.hypot(wx - self.px, wy - self.py) < 0.12:
                    self.waypoints.pop(0)
                else:
                    self.steer(wx, wy, dt, 3.0)
            else:
                dist = math.hypot(e["x"] - self.px, e["y"] - self.py)
                if dist <= e["stop"]:
                    self.moving = False
                    self.start_combat()
                else:   # reta final: desacelera chegando perto do inimigo
                    self.steer(e["x"], e["y"], dt, min(3.0, 1.1 + (dist - e["stop"]) * 3.0), limit=dist - (e["stop"] - 0.05))
            if self.phase == "walk" and self.stuck_t > 0.7:     # segurança: nunca trava a partida
                self.stuck_t = 0.0
                if self.waypoints:
                    self.px, self.py = self.waypoints.pop(0)
                else:
                    self.moving = False
                    self.start_combat()
        elif ph == "fight":
            self.fight_update(dt, e)
        elif ph == "killed":
            self.kt += dt
            e["scale"] = max(0.0, 1 - self.kt / 0.5)
            if self.kt >= 0.9:
                e["scale"] = 0.0
                alive = [i for i, f_ in enumerate(self.foes) if f_["hp"] > 0]
                if alive:
                    self.cur = next((i for i in alive if i > self.cur), alive[0])
                    self.enemy = self.foes[self.cur]
                    self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), (self.enemy["x"], self.enemy["y"]), self.enemy)
                    self.phase = "walk"
                else:
                    self.room_reward()
        elif ph == "stairs" and self.manual():
            self.stairs_manual(dt)
        elif ph == "stairs" and self.lay.get("village") and not self.smith_done:
            self.moving = True                       # AUTO: vai até o ferreiro; a loja abre quando chega
            self.smith_t += dt
            sx, sy = self.waypoints[0] if self.waypoints else self.lay["smith"]
            dist = math.hypot(sx - self.px, sy - self.py)
            if self.waypoints and dist < 0.12:
                self.waypoints.pop(0)
            elif dist < 0.15 or (self.stuck_t > 0.7 and not self.waypoints and dist < 1.2) or self.smith_t > 25:
                self.moving = False
                self.stuck_t = 0.0
                if self.smith_t > 25:                # segurança: nunca trava a partida
                    self.smith_done = True
                    self.waypoints = self.find_path((self.px, self.py), self.stairs)
                else:
                    self.open_smith()
            else:
                self.steer(sx, sy, dt, 3.2)
                if self.stuck_t > 0.7:
                    self.stuck_t = 0.0
                    if self.waypoints:
                        self.px, self.py = self.waypoints.pop(0)
        elif ph == "stairs" and self.lay.get("village") and not self.market_done:
            self.moving = True                       # AUTO: depois do ferreiro, passa no mercado; a loja abre quando chega
            self.mk_t += dt
            sx, sy = self.waypoints[0] if self.waypoints else self.lay["market"]
            dist = math.hypot(sx - self.px, sy - self.py)
            if self.waypoints and dist < 0.12:
                self.waypoints.pop(0)
            elif dist < 0.15 or (self.stuck_t > 0.7 and not self.waypoints and dist < 1.2) or self.mk_t > 25:
                self.moving = False
                self.stuck_t = 0.0
                if self.mk_t > 25:                   # segurança: nunca trava a partida
                    self.market_done = True
                    self.waypoints = self.find_path((self.px, self.py), self.stairs)
                else:
                    self.open_market()
            else:
                self.steer(sx, sy, dt, 3.2)
                if self.stuck_t > 0.7:
                    self.stuck_t = 0.0
                    if self.waypoints:
                        self.px, self.py = self.waypoints.pop(0)
        elif ph == "stairs":
            self.moving = True
            sx, sy = self.waypoints[0] if self.waypoints else self.stairs
            dist = math.hypot(sx - self.px, sy - self.py)
            if self.waypoints and dist < 0.12:
                self.waypoints.pop(0)
            elif dist < 0.1 or (self.stuck_t > 0.7 and not self.waypoints and dist < 1.0):
                self.moving = False
                self.phase = "descend"
                self.dt_ = 0.0
                self.stuck_t = 0.0
                self.play("fall")
            else:
                self.steer(sx, sy, dt, 3.2)
                if self.stuck_t > 0.7:      # segurança: nunca trava a partida
                    self.stuck_t = 0.0
                    if self.waypoints:
                        self.px, self.py = self.waypoints.pop(0)
        elif ph == "descend":
            if self.stairs:      # puxa o herói para o centro do poço (importa no modo manual)
                k_ = min(1.0, dt * 8.0)
                self.px += (self.stairs[0] - self.px) * k_
                self.py += (self.stairs[1] - self.py) * k_
            self.dt_ += dt
            self.pscale = max(0.0, 1 - self.dt_ / 0.7)
            if self.dt_ >= 1.0:
                self.start_transition("dark")
        elif ph == "bossintro":
            self.update_boss_intro(dt)
        elif ph == "dead":
            self.dtm += dt
            if self.dtm >= 0.8:
                self.start_transition("red")

        if not self.steered:    # parado: encara o inimigo no combate, e a câmera na hora da carta
            self.spd += (0.0 - self.spd) * min(1.0, dt * 14.0)
            goal = None
            if ph in ("fight", "killed") and e is not None:
                goal = math.atan2(e["y"] - self.py, e["x"] - self.px)
            if goal is not None:
                self.turn_to(goal, dt, 9.0)
        self.turn_v += (angle_diff(self.hd, hd0) / max(dt, 1e-3) - self.turn_v) * min(1.0, dt * 10.0)
        self.face = (math.cos(self.hd), math.sin(self.hd))
        if self.moving:
            self.dust_t -= dt
            if self.dust_t <= 0:
                self.dust_t = 0.16
                self.spawn_dust(self.px - self.face[0] * 0.15, self.py - self.face[1] * 0.15, gnd)

    def spawn_dust(self, x, y, z):
        for _ in range(2):
            self.particles.append({"x": x + random.uniform(-0.08, 0.08), "y": y + random.uniform(-0.08, 0.08), "z": z + 0.03,
                                   "vx": random.uniform(-0.3, 0.3), "vy": random.uniform(-0.3, 0.3),
                                   "vz": random.uniform(0.6, 1.3), "life": random.uniform(0.35, 0.55),
                                   "c": (206, 198, 184), "s": random.uniform(0.06, 0.11), "gz": z})

    def continue_after_card(self):
        self.enemy = None
        self.stairs = self.lay["stairs"]
        self.waypoints = [] if self.manual() else self.find_path((self.px, self.py), self.stairs)
        self.phase = "stairs"

    # ------------------------------------------------------------- desenho
    def npc_item(self, items, x, y, kind):
        """NPC do vilarejo desenhado como os heróis; os aldeões viram o corpo para o herói quando ele chega perto."""
        k = NPC_K[kind]
        cx, cy = NPC_CENTER[kind]
        wx, wy = x + cx, y + cy
        if not hasattr(self, "npc_ang"):
            self.npc_ang = {}
        key_ = (round(x, 2), round(y, 2), kind)
        cur, tgt = self.npc_ang.get(key_, 0.0), 0.0
        if kind != "smith_npc":
            dx, dy = self.px - wx, self.py - wy
            if math.hypot(dx, dy) < 3.4:
                tgt = math.atan2(dy, dx) - HERO_FRONT
        d = (tgt - cur + math.pi) % math.tau - math.pi
        cur += d * min(1.0, getattr(self, "dt_last", 1.0 / 60.0) * 6.0)
        self.npc_ang[key_] = cur
        items.append((wx + wy, 0.0, (wx, wy, ground(x, y, self.duplo), k, cur,
                                     ("npc", key_, int(math.floor(cur / 0.2))), npc_parts(kind, self.t), "npc", 0.0)))

    def npc_dyn_item(self, items, n):
        """Aldeão que anda: mesmo desenho dos outros NPCs, mas na posição viva, com a caminhada animada."""
        kind, k = n["kind"], NPC_K[n["kind"]]
        wx, wy = n["x"], n["y"]
        mv = bool(n["moving"])
        ang = n["ang"]
        items.append((wx + wy, 0.0, (wx, wy, ground(wx, wy, self.duplo), k, ang,
                                     ("npc", ("dyn", n["id"]), int(math.floor(ang / 0.2)), mv),
                                     npc_parts(kind, self.t, moving=mv, key=f"npc_dyn_{n['id']}"), "npc", 0.0)))

    def place(self, items, parts, x, y, z, s=1.0, flash=0.0, g=0.1):
        for (dx, dy, dz, w, d, h, c) in parts:
            if flash > 0:
                c = mix(c, min(1, flash * 3))
            X, Y, Z = x + dx * s, y + dy * s, z + dz * s
            items.append(((X + w * s / 2) + (Y + d * s / 2), Z, (X, Y, Z, w * s, d * s, h * s, c, True, g * s)))

    def decor_parts(self, kind, t=0.0):
        if kind in EXTRA_DECOR:
            return decor_parts2(kind, t)
        if kind == "crate":
            return [(0, 0, 0, 0.6, 0.6, 0.6, (160, 112, 64)), (-0.01, -0.01, 0.54, 0.62, 0.62, 0.06, (190, 140, 84)),
                    (-0.01, -0.01, 0, 0.62, 0.62, 0.05, (100, 70, 40)), (0.2, 0.6, 0.15, 0.2, 0.02, 0.3, (120, 84, 48)),
                    (0.6, 0.2, 0.15, 0.02, 0.2, 0.3, (120, 84, 48))]
        if kind == "barrel":
            return [(0.05, 0.05, 0, 0.5, 0.5, 0.7, (136, 92, 54)), (0.03, 0.03, 0.12, 0.54, 0.54, 0.07, (74, 74, 86)),
                    (0.03, 0.03, 0.46, 0.54, 0.54, 0.07, (74, 74, 86)), (0.08, 0.08, 0.70, 0.44, 0.44, 0.04, (170, 120, 70))]
        if kind == "chest":
            return [(0, 0, 0, 0.62, 0.42, 0.28, (140, 90, 48)), (-0.01, -0.01, 0.28, 0.64, 0.44, 0.14, (170, 112, 60)),
                    (0.26, 0.42, 0.18, 0.10, 0.03, 0.12, (245, 205, 70)), (0.62, 0.16, 0.18, 0.03, 0.10, 0.12, (245, 205, 70)),
                    (-0.01, -0.01, 0.0, 0.64, 0.44, 0.04, (80, 80, 92))]
        if kind == "pillar":
            return [(0.0, 0.0, 0, 0.5, 0.5, 0.16, (96, 94, 108)), (0.08, 0.08, 0.16, 0.34, 0.34, 1.35, (132, 128, 144)),
                    (0.0, 0.0, 1.51, 0.5, 0.5, 0.16, (110, 108, 122))]
        if kind == "rock":
            return [(0.0, 0.05, 0, 0.6, 0.5, 0.32, (104, 102, 114)), (0.1, 0.12, 0.32, 0.4, 0.3, 0.2, (122, 120, 132)),
                    (0.5, 0.0, 0, 0.14, 0.14, 0.12, (96, 94, 106))]
        return [(0.0, 0.1, 0, 0.3, 0.1, 0.07, (225, 225, 210)), (0.2, 0.3, 0, 0.1, 0.3, 0.07, (215, 215, 200)),
                (0.35, 0.0, 0, 0.12, 0.12, 0.12, (236, 236, 220)), (0.36, 0.01, 0.06, 0.03, 0.03, 0.04, DARK)]

    def cglow_img(self, r, col, k=1.0):
        key = (r, col, int(k * 4))
        g = self.cglow.get(key)
        if g is None:
            q = 0.25 + 0.75 * (int(k * 4) / 4.0)
            g = make_glow(r, tuple(int(c * 0.30 * q) for c in col))
            self.cglow[key] = g
        return g

    def draw_liquid(self, scr, cam):
        """Rio animado: correnteza em riscos de luz, brilho da lava e cachoeira na borda da ilha."""
        lay = self.lay
        water, fords, bridges = lay.get("water", set()), lay.get("fords", set()), lay.get("bridges", set())
        if not water and not fords:
            return
        liq = LIQUIDS[lay["liquid"]]
        t, axis = self.t, lay["river_axis"]
        fx, fy = (0.0, 1.0) if axis == "y" else (1.0, 0.0)          # sentido da correnteza
        P = lambda x, y, z: proj(x, y, z, cam)

        def lim(c):    # até onde o risco pode ir sem passar por cima da margem que fica na frente
            return 1.0 if c in water else (0.8 if c in fords else (0.64 if c in bridges else 0.72))
        for (i, j) in sorted(water | fords, key=lambda c: c[0] + c[1]):
            zt = -0.30 if (i, j) in water else -0.12
            mx, my = lim((i + 1, j)), lim((i, j + 1))
            for k in range(4):
                h = ((i * 7 + j * 13 + k * 5) % 10) / 10.0
                lat = 0.10 + 0.60 * (((i * 3 + j * 11 + k * 7) % 9) / 8.0)
                ph = (t * 0.45 + h + k * 0.25) % 1.0
                ln = 0.30
                u = ph * (1.0 - ln)
                x0, y0 = i + (lat if fx == 0 else u), j + (lat if fy == 0 else u)
                x1, y1 = min(x0 + fx * ln, i + mx), min(y0 + fy * ln, j + my)
                x0, y0 = min(x0, i + mx), min(y0, j + my)
                col = mix(liq["deep"], 0.25 + 0.55 * math.sin(math.pi * ph), liq["light"])
                pygame.draw.line(scr, col, P(x0, y0, zt), P(x1, y1, zt), 2)
            if liq["glow"] is not None and (i, j) in water:
                pl = 0.6 + 0.4 * math.sin(t * 2.0 + i * 1.7 + j * 2.3)
                gp = P(i + 0.5, j + 0.5, zt)
                scr.blit(self.cglow_img(70, liq["glow"], pl), (gp[0] - 70, gp[1] - 70),
                         special_flags=pygame.BLEND_RGB_ADD)
        for (i, j) in water:                                        # cachoeira pela borda da ilha flutuante
            if (axis == "y" and j == N - 1) or (axis == "x" and i == N - 1):
                A = (lambda u, z: P(i + u, N, z)) if axis == "y" else (lambda u, z: P(N, j + u, z))
                zt, zb = -0.30, -1.7
                pygame.draw.polygon(scr, shade(liq["deep"], 0.85), [A(0, zt), A(1, zt), A(1, zb), A(0, zb)])
                for k in range(5):
                    for sg in range(4):
                        ph = (t * 1.3 + sg * 0.25 + k * 0.13) % 1.0
                        z0 = zt - ph * 1.2
                        pygame.draw.line(scr, mix(liq["light"], 0.3 + 0.4 * (1 - ph)),
                                         A(0.1 + 0.2 * k, z0), A(0.1 + 0.2 * k, max(zb, z0 - 0.25)), 2)
                for k in range(3):
                    mp = A(0.2 + 0.3 * k, zb + 0.05 * math.sin(t * 3 + k))
                    pygame.draw.circle(scr, mix(liq["light"], 0.5), (int(mp[0]), int(mp[1])), 4 + (k % 2))

    def draw_glows(self, scr, cam):
        t, duplo = self.t, self.duplo
        for (x, y, kind) in self.decor:
            gc = GLOW_KINDS.get(kind)
            if gc is None:
                continue
            pl = 0.65 + 0.35 * math.sin(t * 2.2 + x * 3.1 + y * 1.7)
            if kind == "brazier":
                pl = 0.5 + 0.5 * math.sin(t * 9 + x) * math.sin(t * 5.3 + y)
            r = GLOW_R.get(kind, 80 if kind in CRYSTAL_COL else 70)
            gp = proj(x + 0.3, y + 0.3, ground(x, y, duplo) + 0.45, cam)
            scr.blit(self.cglow_img(r, gc, pl), (gp[0] - r, gp[1] - r), special_flags=pygame.BLEND_RGB_ADD)
        for i, (ax, v, zc, col) in enumerate(self.lay.get("wall_crystals", ())):
            pl = 0.65 + 0.35 * math.sin(t * 1.8 + i * 2.4)
            gp = proj(0.15, v + 0.25, zc + 0.35, cam) if ax == "x" else proj(v + 0.25, 0.15, zc + 0.35, cam)
            scr.blit(self.cglow_img(85, col, pl), (gp[0] - 85, gp[1] - 85), special_flags=pygame.BLEND_RGB_ADD)

    def draw_motes(self, scr, cam):
        """Poeira luminosa flutuando na caverna."""
        col, t = self.pal[5], self.t
        for (x0, y0, z0, ph) in self.lay.get("motes", ()):
            x = x0 + 0.45 * math.sin(t * 0.35 + ph)
            y = y0 + 0.45 * math.cos(t * 0.30 + ph * 1.3)
            z = z0 + 0.35 * math.sin(t * 0.6 + ph * 2.0)
            a = 0.5 + 0.5 * math.sin(t * 1.7 + ph * 3)
            p = proj(x, y, z, cam)
            pygame.draw.circle(scr, mix((30, 30, 40), 0.35 + 0.65 * a, col), (int(p[0]), int(p[1])), 2 if a > 0.6 else 1)

    def _lamp(self, r, col):
        """Brilho redondo reaproveitado (cache) para o mapa de luz."""
        key = (r, col)
        g = self.__dict__.setdefault("_lamps", {}).get(key)
        if g is None:
            g = self._lamps[key] = make_glow(r, col)
        return g

    def draw_embers(self, scr, cam):
        """Brasas e cinzas subindo devagar em todas as salas (sem sorteio: só funções do tempo)."""
        t = self.t
        hot = self.lay.get("pal_idx") in (2, 102)
        fly = bool(self.lay.get("village"))        # no vilarejo as brasas viram vaga-lumes
        for i in range(26):
            ph = (t * (0.05 + (i * 7 % 11) / 200.0) + i * 0.173) % 1.0
            x0 = 1.0 + (i * 37 % 70) / 10.0
            y0 = 1.0 + (i * 53 % 70) / 10.0
            x = x0 + 0.5 * math.sin(t * 0.7 + i)
            y = y0 + 0.5 * math.cos(t * 0.6 + i * 1.3)
            z = 0.1 + ph * 3.2
            p = proj(x, y, z, cam)
            a = math.sin(math.pi * ph)
            if fly:
                col = (int(190 * a ** 0.5), int(235 * a ** 0.5), int(70 * a))
            elif i % 3 == 0 or hot:
                col = (int(255 * a ** 0.5), int(110 + 60 * a), int(30 * a))
            else:
                v = int(70 + 60 * a)
                col = (v, int(v * 0.95), int(v * 0.9))
            scr.fill(col, (int(p[0]), int(p[1]), 2 if a > 0.5 else 1, 2 if a > 0.5 else 1))

    def apply_lighting(self, scr, cam):
        """Multiplica a cena por um mapa de luz: ambiente frio e escuro + lanterna do herói + tochas,
        braseiros, cristais, lava e o poço da escada."""
        lay, t, duplo = self.lay, self.t, self.duplo
        lm = self.__dict__.get("_lightmap")
        if lm is None:
            lm = self._lightmap = pygame.Surface((W, H))
        pi = lay.get("pal_idx", 0)
        if lay.get("village"):
            amb = (168, 150, 168)            # entardecer: bem mais claro que a masmorra
        elif lay.get("room") == "boss":
            amb = (104, 84, 106)
        elif pi in (2, 102):
            amb = (126, 98, 90)
        else:
            amb = (92, 96, 124)
        lm.fill(amb)
        ADD = pygame.BLEND_RGB_ADD
        fl = 0.5 + 0.25 * math.sin(t * 9) + 0.15 * math.sin(t * 23 + 1.3)
        # lanterna do herói (treme como chama)
        if self.pscale > 0.02:
            hp_ = proj(self.px, self.py, self.pz + 0.8, cam)
            g = self._lamp(300 if fl > 0.5 else 285, (150, 112, 70))
            lm.blit(g, (hp_[0] - g.get_width() // 2, hp_[1] - g.get_height() // 2), special_flags=ADD)
        # tochas na parede
        for i, (ax, v) in enumerate(self.torches):
            f_ = 0.5 + 0.5 * math.sin(t * 9 + i * 2.1) * math.sin(t * 5.3 + i)
            base = ground(0.1, v, duplo) if ax == "x" else ground(v, 0.1, duplo)
            gp = proj(0.05, v, base + 1.4, cam) if ax == "x" else proj(v, 0.05, base + 1.4, cam)
            g = self._lamp(210 if f_ > 0.5 else 195, (200, 120, 48))
            lm.blit(g, (gp[0] - g.get_width() // 2, gp[1] - g.get_height() // 2), special_flags=ADD)
        # decoração que brilha (braseiros, cristais, cogumelos, musgo)
        for (x, y, kind) in self.decor:
            gc = GLOW_KINDS.get(kind)
            if gc is None:
                continue
            pl = 0.7 + 0.3 * math.sin(t * 2.2 + x * 3.1 + y * 1.7)
            if kind == "brazier":
                pl = 0.55 + 0.45 * math.sin(t * 9 + x) * math.sin(t * 5.3 + y)
            r = int(GLOW_R.get(kind, 80 if kind in CRYSTAL_COL else 70) * 1.5)
            pl = round(pl * 4) / 4.0
            col = tuple(int(c * 0.75 * pl) for c in gc)
            gp = proj(x + 0.3, y + 0.3, ground(x, y, duplo) + 0.45, cam)
            g = self._lamp(r, col)
            lm.blit(g, (gp[0] - r, gp[1] - r), special_flags=ADD)
        for i, (ax, v, zc, col) in enumerate(lay.get("wall_crystals", ())):
            pl = 0.7 + 0.3 * math.sin(t * 1.8 + i * 2.4)
            gp = proj(0.15, v + 0.25, zc + 0.35, cam) if ax == "x" else proj(v + 0.25, 0.15, zc + 0.35, cam)
            pl = round(pl * 4) / 4.0
            g = self._lamp(120, tuple(int(c * 0.7 * pl) for c in col))
            lm.blit(g, (gp[0] - 120, gp[1] - 120), special_flags=ADD)
        # lava ilumina a sala toda de laranja
        liq = LIQUIDS.get(lay.get("liquid", "agua"))
        if liq and liq["glow"] is not None:
            for (i, j) in list(lay.get("water", ()))[:24]:
                gp = proj(i + 0.5, j + 0.5, -0.1, cam)
                pl = 0.6 + 0.4 * math.sin(t * 2.0 + i * 1.7 + j * 2.3)
                pl = round(pl * 4) / 4.0
                g = self._lamp(120, tuple(int(c * 0.55 * pl) for c in liq["glow"]))
                lm.blit(g, (gp[0] - 120, gp[1] - 120), special_flags=ADD)
        # poço da escada: luz azul-fantasma (marca o objetivo no escuro)
        if self.stairs:
            sx, sy = self.stairs
            gp = proj(sx, sy, ground(sx, sy, duplo) + 0.2, cam)
            g = self._lamp(150, (40, 78, 150))
            lm.blit(g, (gp[0] - 150, gp[1] - 150), special_flags=ADD)
        scr.blit(lm, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        # tom frio por cima (azul-acinzentado) para tirar a cor "viva"
        # (feito com uma multiplicação leve já embutida no ambiente; nada extra aqui)

    def draw_scene(self):
        scr = self.screen
        cam = self.cam
        scr.fill(self.pal[4])
        scr.blit(self.room, (int(cam[0]), int(cam[1])))
        duplo = self.duplo

        self.draw_liquid(scr, cam)

        # escada de descida (poço de voxels)
        if self.stairs:
            sx, sy = self.stairs
            draw_stairwell(scr, sx, sy, ground(sx, sy, duplo), cam, self.t, self.pal, self.stair_glow)

        # tochas
        for i, (ax, v) in enumerate(self.torches):
            fl = 0.5 + 0.5 * math.sin(self.t * 9 + i * 2.1) * math.sin(self.t * 5.3 + i)
            base = ground(0.1, v, duplo) if ax == "x" else ground(v, 0.1, duplo)
            zb = base + 0.9
            fcol = (255, 170 + int(60 * fl), 40)
            wa = self.pal[2]
            wbox(scr, ax, v, -0.2, 0.4, zb - 0.1, 0.55, 0.04, shade(wa, 0.62), g=0.1, cam=cam)
            wbox(scr, ax, v, -0.05, 0.1, zb, 0.1, 0.14, (70, 56, 44), off=0.04, cam=cam)
            wbox(scr, ax, v, -0.1, 0.2, zb + 0.1, 0.25, 0.14, (96, 70, 44), off=0.02, g=0.1, cam=cam)
            wbox(scr, ax, v, -0.08, 0.16, zb + 0.35, 0.15 + 0.1 * fl, 0.12, fcol, off=0.03, cam=cam)
            wbox(scr, ax, v, -0.04, 0.08, zb + 0.37, 0.08 + 0.1 * fl, 0.06, (255, 238, 160), off=0.06, cam=cam, outline=False)
            gp = proj(0.05, v, zb + 0.5, cam) if ax == "x" else proj(v, 0.05, zb + 0.5, cam)
            g = self.glow[1 if fl > 0.5 else 0]
            scr.blit(g, (gp[0] - g.get_width() // 2, gp[1] - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)

        self.draw_glows(scr, cam)

        # sombras
        sh = pygame.Surface((W, H), pygame.SRCALPHA)
        shadows = [(self.px, self.py, ground(self.px, self.py, duplo), 0.34 * self.pscale)]
        shadows += [(n_["x"], n_["y"], ground(n_["x"], n_["y"], duplo), 0.30) for n_ in self.vnpcs]
        shadows += self.mp_shadows()
        for e in self.foes:
            if e["scale"] > 0:
                shadows.append((e["x"], e["y"], e["z"], foe_shadow_r(e["kind"]) * e["s"] * e["scale"]))
        for (x, y, z0, r) in shadows:
            z0 += 0.02
            for rk, ak in ((1.18, 46), (0.88, 74), (0.58, 104)):
                rr = r * rk
                pts = [proj(x - rr, y, z0, cam), proj(x, y - rr, z0, cam), proj(x + rr, y, z0, cam), proj(x, y + rr, z0, cam)]
                pygame.draw.polygon(sh, (8, 16, 34, ak), pts)
        for (x, y, kind) in self.decor:
            if kind in NO_SHADOW:
                continue
            z0 = ground(x, y, duplo) + 0.02
            pts = [proj(x - 0.1, y - 0.1, z0, cam), proj(x + 0.7, y - 0.1, z0, cam),
                   proj(x + 0.7, y + 0.7, z0, cam), proj(x - 0.1, y + 0.7, z0, cam)]
            pygame.draw.polygon(sh, (0, 0, 0, 70), pts)
        for e in self.foes:     # anel pulsante no chão: dourado = elite, vermelho = chefe
            if e["scale"] > 0.3 and (e.get("elite") or e.get("boss")):
                pl = 0.5 + 0.5 * math.sin(self.t * 4 + e["x"])
                rr = foe_shadow_r(e["kind"]) * e["s"] * e["scale"] * (1.45 + 0.06 * pl)
                z0 = e["z"] + 0.03
                rc = (255, 70, 60) if e.get("boss") else (255, 196, 60)
                pts = [proj(e["x"] - rr, e["y"], z0, cam), proj(e["x"], e["y"] - rr, z0, cam),
                       proj(e["x"] + rr, e["y"], z0, cam), proj(e["x"], e["y"] + rr, z0, cam)]
                pygame.draw.polygon(sh, rc + (int(70 + 80 * pl),), pts, 3)
                pygame.draw.polygon(sh, rc + (int(20 + 25 * pl),), pts)
        en = self.enemy
        if self.phase == "fight":      # zona do golpe de cada monstro: setor vermelho que enche até a pancada
            for en in self.foes:
                if en["hp"] <= 0 or en.get("ai") not in ("wind", "strike"):
                    continue
                pw = 1.0 if en["ai"] == "strike" else 1.0 - max(0.0, en["ait"]) / max(0.01, en["wind"])
                rr, z0 = en["stop"] + self.FOE_REACH, en["z"] + 0.03
                a0 = en["aim"] if en["ai"] == "strike" else math.atan2(self.py - en["y"], self.px - en["x"])
                arc = 1.35 if en.get("boss") else self.FOE_ARC
                pts = [proj(en["x"], en["y"], z0, cam)]
                for i in range(13):
                    a_ = a0 + arc * (i / 6.0 - 1.0)
                    pts.append(proj(en["x"] + rr * math.cos(a_), en["y"] + rr * math.sin(a_), z0, cam))
                pygame.draw.polygon(sh, (255, 50, 40, int(25 + 105 * pw)), pts)
                pygame.draw.polygon(sh, (255, 120, 90, int(110 + 140 * pw)), pts, 3)
        scr.blit(sh, (0, 0))
        if self.pscale > 0.02:
            hid = self.hero["id"]
            if not hasattr(self, "hero_glows"):
                self.hero_glows = {}
            if hid not in self.hero_glows:
                self.hero_glows[hid] = make_glow(70, tuple(int(c * 0.30) for c in self.hero["color"]))
            gimg = self.hero_glows[hid]
            gp = proj(self.px, self.py, ground(self.px, self.py, duplo) + 0.05, cam)
            scr.blit(gimg, (gp[0] - 70, gp[1] - 70), special_flags=pygame.BLEND_RGB_ADD)

        # objetos ordenados (algoritmo do pintor)
        items = []
        objs = []   # caixas (x0, y0, x1, y1, chave mín., chave máx.) de tudo que o herói pode ficar na frente/atrás
        for (x, y, kind) in self.decor:
            if kind in FLAT_KINDS:      # já está desenhada no cenário em cache
                continue
            if kind in NPC_KINDS:       # NPCs do vilarejo: estilo dos heróis
                self.npc_item(items, x, y, kind)
                continue
            n0 = len(items)
            self.place(items, self.decor_parts(kind, self.t), x, y, ground(x, y, duplo), g=0.15)
            if kind in SOLID_KINDS:
                ks = [it[0] for it in items[n0:]]
                objs.append((*self.decor_rect(x, y, kind), min(ks), max(ks)))
        for n_ in self.vnpcs:           # aldeões que andam
            self.npc_dyn_item(items, n_)
        for e in self.foes:
            if e["scale"] > 0.02:
                ep = parts_enemy(e["kind"], self.t)
                ex, ey = e["x"], e["y"]
                if e.get("elunge"):
                    dx, dy = self.px - ex, self.py - ey
                    L = math.hypot(dx, dy) or 1
                    ex += dx / L * e["elunge"]
                    ey += dy / L * e["elunge"]
                fl = min(1.0, e["flash"])
                if fl > 0:
                    dxe, dye = ex - self.px, ey - self.py
                    Le = math.hypot(dxe, dye) or 1
                    ep = pose_parts(ep, 1 + 0.08 * fl, 1 + 0.08 * fl, 1 - 0.14 * fl, (dxe / Le * 0.2 * fl, dye / Le * 0.2 * fl))
                else:
                    ep = pose_parts(ep, 1.0, 1.0, 1 + 0.012 * math.sin(self.t * 3 + e["x"]))
                es = e["s"] * e["scale"]
                rr = 0.38 * es
                if e["kind"] in NO_TURN:
                    n0 = len(items)
                    self.place(items, ep, ex, ey, e["z"], es, e["flash"])
                    ks = [it[0] for it in items[n0:]]
                    objs.append((ex - rr, ey - rr, ex + rr, ey + rr, min(ks), max(ks)))
                else:
                    # gira o monstro para o jogador (mesmo desenho girado do herói)
                    ang_e = e.get("hd", foe_front(e["kind"])) - foe_front(e["kind"])
                    fkey = ex + ey
                    lo, hi = -1e9, 1e9
                    for (ox0, oy0, ox1, oy1, kmin, kmax) in objs:
                        in_front = ex - rr >= ox1 - 1e-6 or ey - rr >= oy1 - 1e-6
                        behind = ox0 >= ex + rr - 1e-6 or oy0 >= ey + rr - 1e-6
                        if in_front and not behind:
                            lo = max(lo, kmax)
                        elif behind and not in_front:
                            hi = min(hi, kmin)
                    if lo < hi:
                        fkey = min(max(fkey, lo + 0.002), hi - 0.002)
                    ckey = ("foe", id(e), int(math.floor(ang_e / 0.2)), e["kind"], bool(e.get("elite")))
                    items.append((fkey, e["z"], (ex, ey, e["z"], es, ang_e, ckey,
                                                 scale_parts(ep, es, e["flash"]), "foe", 0.0)))
                    objs.append((ex - rr, ey - rr, ex + rr, ey + rr, fkey, fkey))
        if self.pscale > 0.02:
            atk_ = max(0.0, min(1.0, self.lunge / 0.55)) if self.lunge else 0.0
            # o modelo é montado olhando para (+1,+1); girar = desenhar com `ang` (heading do herói)
            pp = parts_player(self.t, self.moving, self.hero["id"], (0.7071, 0.7071), atk_, getattr(self, "race", "human"))
            px, py = self.px, self.py
            ph_ = self.phase
            sx = sy = sz = 1.0
            lean = [0.0, 0.0]       # inclinação no espaço do modelo (frente = (+1,+1))
            zoff = 0.0
            rflash = self.pflash
            dxn = dyn = 0.0
            ang = self.hd - HERO_FRONT
            ca_, sa_ = math.cos(ang), math.sin(ang)
            if self.moving:
                bank = max(-1.0, min(1.0, self.turn_v / 10.0)) * 0.06     # inclina para dentro da curva
                lean = [0.0707 - bank * 0.7071, 0.0707 + bank * 0.7071]
            else:
                sz = 1 + 0.015 * math.sin(self.t * 3)
            if self.lunge:
                dxn, dyn = math.cos(self.hd), math.sin(self.hd)
                lk = 0.25 if self.ranged_hero() else 1.0      # arqueira/maga quase não avançam ao atacar
                px += dxn * self.lunge * lk
                py += dyn * self.lunge * lk
                k = min(1.0, self.lunge / 0.55)
                lx, ly = dxn * 0.30 * k * (0.5 if lk < 1 else 1.0), dyn * 0.30 * k * (0.5 if lk < 1 else 1.0)
                lean = [lx * ca_ + ly * sa_, -lx * sa_ + ly * ca_]       # mundo -> espaço do modelo
                sz, sx, sy = 1 - 0.06 * k, 1 + 0.04 * k, 1 + 0.04 * k
            if self.rolling and ph_ in ("fight", "mp"):      # rolagem: gira, achata e brilha (imortal)
                kr = min(1.0, self.roll_t / self.ROLL_T)
                ang = (ang + kr * math.tau + math.pi) % math.tau - math.pi
                sz, sx, sy = 0.72, 1.12, 1.12
                zoff = 0.05
                rflash = (0.18 + 0.08 * math.sin(self.t * 40)) if self.roll_t <= self.ROLL_IFR else 0.0     # brilha só enquanto imortal
            if self.land_t > 0:
                k = self.land_t / 0.3
                sz, sx, sy = 1 - 0.24 * k, 1 + 0.14 * k, 1 + 0.14 * k
            if ph_ == "arrive":
                sz, sx, sy = 1.14, 0.94, 0.94
            if self.pflash > 0:
                px += math.sin(self.t * 80) * 0.04 * (self.pflash / 0.3)
                sz *= 0.95
            if ph_ == "killed":
                zoff = abs(math.sin(self.t * 7)) * 0.12
            if ph_ in ("dead", "gameover"):
                k = min(1.0, self.dtm / 0.8)
                sz, sx, sy = max(0.12, 1 - 0.88 * k), 1 + 0.5 * k, 1 + 0.5 * k
            pp = pose_parts(pp, sx, sy, sz, tuple(lean))
            hs_ = self.pscale * HERO_SCALE * (VILLAGE_HERO_K if getattr(self, "village", False) else 1.0)
            # ordem de desenho em relação a caixas, barris, pilares... e inimigos: separa por eixo (nunca "atravessa" visualmente)
            hkey = px + py
            lo, hi = -1e9, 1e9
            hx0, hy0, hx1, hy1 = px - HERO_R, py - HERO_R, px + HERO_R, py + HERO_R
            for (ox0, oy0, ox1, oy1, kmin, kmax) in objs:
                in_front = hx0 >= ox1 - 1e-6 or hy0 >= oy1 - 1e-6
                behind = ox0 >= hx1 - 1e-6 or oy0 >= hy1 - 1e-6
                if in_front and not behind:
                    lo = max(lo, kmax)
                elif behind and not in_front:
                    hi = min(hi, kmin)
            if lo < hi:
                hkey = min(max(hkey, lo + 0.002), hi - 0.002)
            items.append((hkey, self.pz + zoff, (px, py, self.pz + zoff, hs_, ang, 0.0,
                                                  scale_parts(pp, hs_, rflash), "hero", 0.0)))
            if self.lunge > 0.01 and dxn and not self.ranged_hero():  # rastro do golpe
                kk0 = min(1.0, self.trail_k)
                perp = (-dyn, dxn)
                for j in range(9):
                    kk = kk0 - j * 0.045
                    if kk <= 0:
                        continue
                    th = -1.2 + 2.4 * min(1.0, kk)
                    bx = px + dxn * 0.62 + perp[0] * math.sin(th) * 0.6
                    by = py + dyn * 0.62 + perp[1] * math.sin(th) * 0.6
                    bz = self.pz + 0.58 + math.cos(th) * 0.38
                    sq = 0.20 * (1 - j / 10)
                    col = mix(self.hero["color"], max(0.0, 0.8 - j * 0.08))
                    items.append((bx + by + sq, bz, (bx - sq / 2, by - sq / 2, bz, sq, sq, sq, col, False, 0.0)))
        self.mp_remote_items(items, objs)
        for p in self.particles:
            s = p["s"]
            items.append((p["x"] + p["y"] + s, p["z"], (p["x"], p["y"], p["z"], s, s, s, p["c"], False, 0.0)))
        for s_ in self.shots:
            self.shot_items(items, s_)
        for c_ in self.crystals:
            self.crystal_items(items, c_)
        for fo_ in self.foes:
            if fo_.get("ice_t", 0.0) > 0 and fo_["hp"] > 0 and fo_["scale"] > 0.02:
                self.ice_block_items(items, fo_)

        items.sort(key=lambda i: (round(i[0], 3), i[1]))
        for _, _, (x, y, z, w, d, h, c, o, g) in items:
            if g > 0 and (w < 2 * g and d < 2 * g and h < 2 * g):
                g = 0.0
            if o == "foe":     # w = escala, d = ângulo de giro, h = chave de cache (..., tipo, elite)
                # folha transparente + contorno; ordem guardada por faixa de ângulo (monstros grandes ficam leves)
                draw_foe(scr, c, x, y, z, d, cam, h, 0.008 * w, h[3], h[4], 2 if w >= 1.6 else 1)
                continue
            if o == "npc":     # w = escala, d = ângulo de giro, h = chave de cache
                draw_hero_rot(scr, c, x, y, z, d, cam, h, 0.008 * w)
                continue
            if o == "hero":    # w = escala, d = ângulo de giro
                draw_hero_rot(scr, c, x, y, z, d, cam, ("game", self.hero["id"], int(math.floor(d / 0.2)), self.moving, self.lunge > 0.01), 0.008 * w)
                continue
            draw_box(scr, x, y, z, w, d, h, c, cam, o, g)

        if self.lay.get("cave"):
            self.draw_motes(scr, cam)
        self.draw_embers(scr, cam)
        self.apply_lighting(scr, cam)        # dark fantasy: tudo escuro, só o fogo e o herói iluminam
        if self.lay.get("cave"):
            scr.blit(self.vig, (0, 0))       # caverna: mais escura (vinheta dupla)
        scr.blit(self.vig, (0, 0))
        # mira do Tiro Preciso: linha até o alvo enquanto a arqueira prepara o disparo
        if self.phase == "fight" and self.swinging and self.skill_cur and self.skill_cur["id"] == "tiro_preciso" \
                and self.enemy is not None and self.enemy["hp"] > 0:
            e_ = self.enemy
            a_ = proj(self.px, self.py, self.pz + 0.9, cam)
            b_ = proj(e_["x"], e_["y"], e_["z"] + 0.9 * e_["s"], cam)
            col_ = (255, 80, 60) if int(self.t * 20) % 2 == 0 else (255, 220, 120)
            pygame.draw.line(scr, col_, a_, b_, 2)
            pygame.draw.circle(scr, col_, (int(b_[0]), int(b_[1])), 12, 2)
            pygame.draw.circle(scr, col_, (int(b_[0]), int(b_[1])), 3)

    # ------------------------------------------------------------ cartas UI
    def bar(self, x, y, w, h, frac, color, label):
        pygame.draw.rect(self.screen, (20, 20, 30), (x - 2, y - 2, w + 4, h + 4), border_radius=6)
        pygame.draw.rect(self.screen, (60, 30, 30), (x, y, w, h), border_radius=5)
        if frac > 0:
            pygame.draw.rect(self.screen, color, (x, y, int(w * frac), h), border_radius=5)
        self.text(label, 24, (255, 255, 255), (x + w // 2, y + h // 2))

    def heart_img(self, full):
        key = ("heart", full)
        if key not in self.icons:
            im = self.icon("coracao", 30).copy()
            if not full:
                im.fill((60, 60, 72, 255), special_flags=pygame.BLEND_RGB_MULT)
                im.set_alpha(150)
            self.icons[key] = im
        return self.icons[key]

    def hp_color(self, frac):
        if frac > 0.5:
            return mix((240, 210, 60), (frac - 0.5) * 2, (90, 214, 104))
        return mix((226, 64, 64), frac * 2, (240, 210, 60))

    # ------------------------------------------------------- HUD (pixel art)
    def ptext(self, s, size, col, pos, k=2, ol=PX_OL, anchor="c", max_w=None):
        im = px_text(str(s), size, tuple(col), ol, k)
        if max_w and im.get_width() > max_w:
            im = pygame.transform.scale(im, (int(max_w), max(1, int(im.get_height() * max_w / im.get_width()))))
        r = im.get_rect()
        if anchor == "c":
            r.center = pos
        elif anchor == "l":
            r.midleft = pos
        else:
            r.midright = pos
        self.screen.blit(im, r)
        return r

    def draw_hud(self):
        scr, t = self.screen, self.t
        boss = self.enemy is not None and self.enemy.get("boss")
        brown = (78, 44, 40)

        # retrato do herói (silhueta com o cachecol na cor dele)
        hc = tuple(self.hero["color"])[:3]
        scr.blit(px_get(("portrait", hc), lambda: px_up(px_portrait(hc))), (12, 10))

        # vida: cada divisão da barra é um coração; pisca quando resta só 1
        pulse = abs(math.sin(t * 6)) if self.hp == 1 else 0.0
        scr.blit(px_bar(86, self.hp / max(1, self.maxhp), PX_RED, "heart", self.maxhp, glow=int(pulse * 4)), (84, 10))

        # fôlego
        fr = max(0.0, min(1.0, self.stam / self.STAM_MAX))
        q = int((1.0 - fr) * 6 + 0.5) / 6.0
        sc = (mix((150, 222, 255), q, (255, 200, 144)), mix((64, 150, 232), q, (236, 120, 60)), mix((36, 86, 176), q, (150, 60, 40)))
        scr.blit(px_bar(86, fr, sc, "drop", 0, warm=self.stam_delay > 0), (84, 46))

        # ouro + aviso de cura
        scr.blit(px_icon("pouch"), (12, 82))
        self.ptext(self.gold, 16, (255, 224, 120), (62, 104), 2, anchor="l")
        nxt = (self.floor // HEAL_EVERY + 1) * HEAL_EVERY
        self.ptext(f"CURA NO ANDAR {nxt}", 11, (150, 255, 180), (150, 104), 2, anchor="l")

        # loot equipado: 4 slots (A = arma, P = armadura, N = anel, M = amuleto), borda na cor da raridade
        for i_, sl_ in enumerate(LOOT_SLOTS):
            it_ = getattr(self, "gear", {}).get(sl_)
            r_ = pygame.Rect(12 + i_ * 32, 118, 28, 28)
            pygame.draw.rect(scr, (24, 18, 26), r_)
            if it_:
                c_ = RARITY_COLORS[it_["rarity"]]
                pygame.draw.rect(scr, shade(c_, 0.25), r_.inflate(-6, -6))
                pygame.draw.rect(scr, c_, r_, 3)
                self.ptext(LOOT_LETTER[sl_], 14, c_, r_.center, 2)
            else:
                pygame.draw.rect(scr, (70, 62, 76), r_, 2)
                self.ptext(LOOT_LETTER[sl_], 14, (80, 72, 88), r_.center, 2)
        nb_ = len(getattr(self, "bag", ()))
        self.ptext(f"[I] {nb_}" if nb_ else "[I]", 11, (255, 226, 130) if nb_ else (170, 170, 186), (12 + 4 * 32 + 4, 132), 2, anchor="l")

        # andar: placa de madeira pendurada por correntes
        sx = W // 2 - 30 - 90
        scr.blit(px_sign(bool(boss)), (sx, 0))
        self.ptext("VILAREJO" if getattr(self, "village", False) else f"ANDAR {self.floor}", 16, (255, 110, 100) if boss else (226, 192, 128), (sx + 90, 48), 2, max_w=150)

        # pontos: quadro escuro com correntes
        bx = sx + 180 + 12
        scr.blit(px_board(), (bx, 0))
        self.ptext("PONTOS", 10, (176, 196, 206), (bx + 54, 36), 2, max_w=78)
        self.ptext(self.score, 14, (255, 224, 120), (bx + 54, 54), 2, max_w=78)

        # inimigo: placa vermelha com chifres
        e = self.enemy
        if e is not None and (e["scale"] > 0.02 or self.phase in ("fight", "walk", "arrive")):
            name = ("ELITE " if e.get("elite") else "") + ENEMY_NAMES.get(e["kind"], e["kind"])
            px_ = W - 12 - 92 * PXS
            frac = max(0.0, e["hp"] / max(1, e["maxhp"]))
            ncol = (255, 120, 110) if e.get("boss") else ((255, 180, 80) if e.get("elite") else (255, 240, 220))
            self.ptext(name, 14, ncol, (px_ + 46 * PXS, 14), 2, max_w=270)
            base = self.hp_color(frac)
            cols = (mix(base, 0.35), base, shade(base, 0.60))
            scr.blit(px_enemy_plate(92, frac, cols), (px_, 24))
            self.ptext(f"{e['hp']}/{e['maxhp']}", 12, (255, 255, 255), (px_ + 46 * PXS, 24 + 11 * PXS), 2, max_w=150)

        if self.banner_t > 0:
            a = min(1.0, self.banner_t)
            txt = px_text(self.banner, 20, (255, 240, 226), PX_OL, 2)
            pw = txt.get_width() // PXS + 16
            plate = px_get(("pill", pw), lambda: px_up(px_frame(pw, 17, PX_CRIM, (74, 18, 38), t=2)))
            tmp = pygame.Surface(plate.get_size(), pygame.SRCALPHA)
            tmp.blit(plate, (0, 0))
            tmp.blit(txt, txt.get_rect(center=tmp.get_rect().center))
            tmp.set_alpha(int(255 * a))
            scr.blit(tmp, tmp.get_rect(center=(W // 2, 130)))
        for f in self.floaters:
            self.text(f["s"], 40, f["c"], self.view_map(f["x"], f["y"]))

    # ---------------------------------------------------- botão: voltar ao menu
    # ------------------------------------------------ menu: START / CRIAR SAVE, 5 slots e criação de personagem
    def save_progress(self):
        """Grava o recorde de andar no slot em uso."""
        i = self.slot
        if i is None or not (0 <= i < NSLOTS) or not self.saves[i]:
            return
        sv = self.saves[i]
        changed = False
        if self.best > sv.get("best", 1):
            sv["best"] = self.best
            changed = True
        for k_, v_ in (("gold", self.gold), ("weapon", self.weapon_lv), ("armor", self.armor_lv)):   # ouro e upgrades
            if sv.get(k_) != v_:
                sv[k_] = v_
                changed = True
        bag_ = [dict(it) for it in self.bag]                       # mochila (o mercado compra e vende dela)
        if sv.get("bag") != bag_:
            sv["bag"] = bag_
            changed = True
        if changed:
            write_saves(self.saves)

    def start_slot(self, i):
        sv = self.saves[i]
        ids = [h["id"] for h in HEROES]
        self.slot = i
        self.hero_index = ids.index(sv["hero"]) if sv["hero"] in ids else 0
        self.best = max(1, sv.get("best", 1))
        sv["runs"] = sv.get("runs", 0) + 1
        write_saves(self.saves)
        self.confirm = None
        self.play("card")
        self.new_run()

    def open_slots(self, mode):
        self.slot_mode = mode
        self.confirm = None
        want_filled = mode == "load"
        pick = next((i for i, sv in enumerate(self.saves) if bool(sv) == want_filled), 0)
        self.slot_sel = pick
        self.phase = "slots"

    def title_activate(self, idx):
        if idx == 3:
            self.open_settings()
        elif idx == 2:
            self.mp_open_menu()
        else:
            self.open_slots("load" if idx == 0 else "create")

    def slot_activate(self, i):
        self.slot_sel = i
        sv = self.saves[i]
        if self.slot_mode == "load":
            if sv:
                self.start_slot(i)
            else:
                self.begin_create(i)
        else:
            if sv:
                self.confirm = ("ow", i)      # sobrescrever pede confirmação
            else:
                self.begin_create(i)

    def begin_create(self, i):
        self.cr_slot = i
        self.cr_name = ""
        self.cr_cls = 0
        self.cr_race = 0
        self.cr_extra = [0] * len(ATTR_KEYS)         # pontos livres já gastos em cada atributo
        self.cr_attr = 0                             # atributo selecionado
        self.cr_tab = 0                              # aba atual: 0 classe | 1 raça | 2 atributos
        self.confirm = None
        self.cr_msg = ""
        self.phase = "create"

    def finish_create(self):
        name = self.cr_name.strip()
        if not name:
            self.cr_msg, self.cr_msg_until = "Digite um nome para o personagem!", self.t + 2.2
            self.cr_tab = 0
            self.play("bad")
            return
        self.saves[self.cr_slot] = {"name": name, "hero": HEROES[self.cr_cls]["id"], "best": 1, "runs": 0,
                                    "gold": 0, "weapon": 0, "armor": 0, "attrs": self.cr_attrs(),
                                    "race": RACES[self.cr_race]["id"]}
        write_saves(self.saves)
        self.start_slot(self.cr_slot)

    def cr_attrs(self):
        """Atributos finais da criação: base + classe + pontos livres."""
        cls = class_attrs(HEROES[self.cr_cls]["id"], RACES[self.cr_race]["id"])
        return {k: cls[k] + self.cr_extra[i] for i, k in enumerate(ATTR_KEYS)}

    def cr_cycle_race(self, d):
        self.cr_race = (self.cr_race + d) % len(RACES)
        self.play("card")

    def cr_free(self):
        return ATTR_POINTS - sum(self.cr_extra)

    def cr_adjust(self, i, d):
        if not (0 <= i < len(ATTR_KEYS)):
            return
        self.cr_attr = i
        cur = self.cr_attrs()[ATTR_KEYS[i]]
        if d > 0 and self.cr_free() > 0 and cur < ATTR_MAX:
            self.cr_extra[i] += 1
            self.play("ok")
        elif d < 0 and self.cr_extra[i] > 0:
            self.cr_extra[i] -= 1
            self.play("card")
        else:
            self.play("bad")

    def cr_clamp(self):
        """Depois de trocar classe/raça, tira pontos livres que estourariam o teto de um atributo."""
        for i, k in enumerate(ATTR_KEYS):
            while self.cr_extra[i] > 0 and self.cr_attrs()[k] > ATTR_MAX:
                self.cr_extra[i] -= 1

    def cr_set_tab(self, i):
        self.cr_tab = i % 3
        self.play("card")

    def cr_move(self, d):
        """↑ ↓: escolhe a classe, a raça ou o atributo, conforme a aba."""
        if self.cr_tab == 0:
            self.cr_cls = (self.cr_cls + d) % len(HEROES)
            self.cr_clamp()
        elif self.cr_tab == 1:
            self.cr_race = (self.cr_race + d) % len(RACES)
            self.cr_clamp()
        else:
            self.cr_attr = (self.cr_attr + d) % len(ATTR_KEYS)
        self.play("card")

    def cr_advance(self):
        """ENTER / botão: próxima aba; na última, cria o personagem."""
        if self.cr_tab == 0 and not self.cr_name.strip():
            self.cr_msg, self.cr_msg_until = "Digite um nome para o personagem!", self.t + 2.2
            self.play("bad")
            return
        if self.cr_tab < 2:
            self.cr_set_tab(self.cr_tab + 1)
        else:
            self.finish_create()

    def cr_back(self):
        if self.cr_tab > 0:
            self.cr_set_tab(self.cr_tab - 1)
        else:
            self.phase = "slots"

    def confirm_yes(self):
        if not self.confirm:
            return
        kind, i = self.confirm
        self.confirm = None
        if kind == "del":
            self.saves[i] = None
            if self.slot == i:
                self.slot = None
            write_saves(self.saves)
            self.play("bad")
        else:
            self.begin_create(i)

    # --- retângulos (usados no desenho, no clique e no hover)
    def title_btns(self):
        return [pygame.Rect(W // 2 - 190, 214 + i * 82, 380, 62) for i in range(4)]

    def slot_rect(self, i):
        return pygame.Rect(130, 196 + i * 62, W - 260, 54)

    def slot_del_rect(self, i):
        r = self.slot_rect(i)
        return pygame.Rect(r.right - 108, r.centery - 15, 96, 30)

    def back_rect(self):
        return pygame.Rect(40, 528, 150, 44)

    def cr_tab_rect(self, i):
        return pygame.Rect(60 + i * 284, 148, 272, 40)

    def cr_prev_rect(self):
        return pygame.Rect(60, 206, 300, 310)

    def cr_panel_rect(self):
        return pygame.Rect(380, 206, 520, 310)

    def name_rect(self):
        rp = self.cr_panel_rect()
        return pygame.Rect(rp.x + 16, rp.y + 30, rp.w - 32, 44)

    def class_row_rect(self, i):
        rp = self.cr_panel_rect()
        return pygame.Rect(rp.x + 16, rp.y + 96 + i * 42, 250, 36)

    def race_row_rect(self, i):
        rp = self.cr_panel_rect()
        return pygame.Rect(rp.x + 16, rp.y + 16 + i * 48, 250, 40)

    def attr_panel_rect(self):
        return self.cr_panel_rect()

    def attr_row_rect(self, i):
        ap = self.attr_panel_rect()
        return pygame.Rect(ap.x + 16, ap.y + 40 + i * 40, ap.w - 32, 36)

    def attr_minus_rect(self, i):
        r = self.attr_row_rect(i)
        return pygame.Rect(r.right - 104, r.centery - 14, 28, 28)

    def attr_plus_rect(self, i):
        r = self.attr_row_rect(i)
        return pygame.Rect(r.right - 34, r.centery - 14, 28, 28)

    def create_btn_rect(self):
        return pygame.Rect(W - 40 - 300, 528, 300, 44)

    # --- entrada
    def title_key(self, key, go):
        if key in (pygame.K_UP, pygame.K_w):
            self.menu_sel = (self.menu_sel - 1) % 4
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.menu_sel = (self.menu_sel + 1) % 4
        elif go:
            self.title_activate(self.menu_sel)

    def slots_key(self, key, go):
        if self.confirm:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                self.confirm_yes()
            elif key in (pygame.K_n, pygame.K_BACKSPACE, pygame.K_DELETE):
                self.confirm = None
            return
        if key in (pygame.K_UP, pygame.K_w):
            self.slot_sel = (self.slot_sel - 1) % NSLOTS
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.slot_sel = (self.slot_sel + 1) % NSLOTS
        elif key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            if self.saves[self.slot_sel]:
                self.confirm = ("del", self.slot_sel)
        elif go:
            self.slot_activate(self.slot_sel)

    def create_key(self, key, uni):
        tab = self.cr_tab
        shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
        if key == pygame.K_ESCAPE:
            self.cr_back()
        elif key == pygame.K_TAB:
            self.cr_set_tab(tab + (-1 if shift else 1))
        elif key == pygame.K_PAGEUP:
            self.cr_set_tab(tab - 1)
        elif key == pygame.K_PAGEDOWN:
            self.cr_set_tab(tab + 1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.cr_advance()
        elif key == pygame.K_UP:
            self.cr_move(-1)
        elif key == pygame.K_DOWN:
            self.cr_move(+1)
        elif tab == 2 and key == pygame.K_LEFT:
            self.cr_adjust(self.cr_attr, -1)
        elif tab == 2 and key == pygame.K_RIGHT:
            self.cr_adjust(self.cr_attr, +1)
        elif tab == 0:                                      # só a aba CLASSE tem o campo de nome
            if key == pygame.K_BACKSPACE:
                self.cr_name = self.cr_name[:-1]
            elif uni and uni.isprintable() and len(self.cr_name) < NAME_MAX:
                if uni == " " and not self.cr_name:
                    return
                self.cr_name += uni

    def menu_click(self, pos):
        ph = self.phase
        if ph == "mp_menu":
            self.mp_menu_click(pos)
            return
        if ph == "username":
            self.username_click(pos)
            return
        if ph == "title":
            for i, r in enumerate(self.title_btns()):
                if r.collidepoint(pos):
                    self.menu_sel = i
                    self.title_activate(i)
                    return
        elif ph == "slots":
            if self.back_rect().collidepoint(pos):
                self.phase, self.confirm = "title", None
                return
            for i in range(NSLOTS):
                r = self.slot_rect(i)
                if not r.collidepoint(pos):
                    continue
                if self.confirm and self.confirm[1] == i:
                    self.confirm_yes()
                    return
                self.confirm = None
                if self.saves[i] and self.slot_del_rect(i).collidepoint(pos):
                    self.slot_sel = i
                    self.confirm = ("del", i)
                    return
                self.slot_activate(i)
                return
            self.confirm = None
        elif ph == "create":
            for i in range(3):
                if self.cr_tab_rect(i).collidepoint(pos):
                    self.cr_set_tab(i)
                    return
            if self.back_rect().collidepoint(pos):
                self.cr_back()
                return
            if self.create_btn_rect().collidepoint(pos):
                self.cr_advance()
                return
            if self.cr_tab == 0:
                for i in range(len(HEROES)):
                    if self.class_row_rect(i).collidepoint(pos):
                        self.cr_cls = i
                        self.cr_clamp()
                        self.play("card")
                        return
            elif self.cr_tab == 1:
                for i in range(len(RACES)):
                    if self.race_row_rect(i).collidepoint(pos):
                        self.cr_race = i
                        self.cr_clamp()
                        self.play("card")
                        return
            else:
                for i in range(len(ATTR_KEYS)):
                    if self.attr_minus_rect(i).collidepoint(pos):
                        self.cr_adjust(i, -1)
                        return
                    if self.attr_plus_rect(i).collidepoint(pos):
                        self.cr_adjust(i, +1)
                        return
                    if self.attr_row_rect(i).collidepoint(pos):
                        self.cr_attr = i
                        return

    def menu_hover(self, pos):
        if self.phase == "title":
            for i, r in enumerate(self.title_btns()):
                if r.collidepoint(pos):
                    self.menu_sel = i
        elif self.phase == "slots" and not self.confirm:
            for i in range(NSLOTS):
                if self.slot_rect(i).collidepoint(pos):
                    self.slot_sel = i
        elif self.phase == "mp_menu":
            for i, r in enumerate(self.mp_rects()["rows"]):
                if r.collidepoint(pos):
                    self.mp_m["sel"] = i

    # --- desenho
    def big_btn(self, r, label, sel):
        pulse = 0.5 + 0.5 * math.sin(self.t * 4)
        rr = r.inflate(int(8 * pulse), int(2 * pulse)) if sel else r
        if sel:
            self.rrect(rr.inflate(24, 24), (255, 100, 20, int(18 + 18 * pulse)), 38)
        self.chunky(rr, (104, 38, 10) if sel else (8, 7, 7), (200, 120, 50) if sel else (64, 48, 38), 26, 4, 5 if sel else 3)
        self.otext(label, 36 if sel else 32, (244, 232, 214) if sel else (150, 140, 126), rr.center, ink=(120, 54, 12) if sel else self.INK, ow=3)

    def small_btn(self, r, label, fill=(24, 13, 12), edge=(120, 76, 50)):
        self.chunky(r, fill, edge, 14, 3, 3)
        self.otext(label, 26, (255, 255, 255), r.center, ow=2)

    def draw_pips(self, hero, x, y, w, col, step=20):
        crit_max = max(h["crit"] for h in HEROES)
        stats = (("vida", "VIDA", hero["hp"], 6),
                 ("crit", "CRÍT", max(1, int(round(hero["crit"] / crit_max * 6))), 6),
                 ("dano", "DANO", hero["damage"] + 1, 4))
        scr = self.screen
        for j, (ik, lab, filled, n) in enumerate(stats):
            by = y + j * step
            self.icon_vec(ik, x + 10, by + 7, 7, col)
            self.text(lab, 18, (168, 158, 144), (x + 28, by + 7), center=False, shadow=False)
            px0 = x + 78
            pw_ = (x + w - px0 - 3 * (n - 1)) // n
            for i in range(n):
                pr = pygame.Rect(px0 + i * (pw_ + 3), by + 2, pw_, 11)
                pygame.draw.rect(scr, self.INK, pr.inflate(4, 4), border_radius=5)
                if i < filled:
                    pygame.draw.rect(scr, col, pr, border_radius=4)
                    pygame.draw.line(scr, mix(col, 0.55), (pr.x + 3, pr.y + 2), (pr.right - 4, pr.y + 2), 1)
                else:
                    pygame.draw.rect(scr, (20, 17, 17), pr, border_radius=4)

    def draw_title_menu(self):
        btns = self.title_btns()
        self.big_btn(btns[0], "START", self.menu_sel == 0)
        self.big_btn(btns[1], "CRIAR SAVE", self.menu_sel == 1)
        self.big_btn(btns[2], "MULTIPLAYER", self.menu_sel == 2)
        self.big_btn(btns[3], "CONFIGURAÇÕES", self.menu_sel == 3)
        self.draw_keybar(597, (("↑ ↓", "escolher"), ("ENTER", "confirmar"), ("ESC", "sair")))

    def draw_slots(self):
        scr, t = self.screen, self.t
        pulse = 0.5 + 0.5 * math.sin(t * 4)
        create = self.slot_mode == "create"
        self.otext("ESCOLHA UM SLOT PARA CRIAR" if create else "ESCOLHA SEU SAVE", 32, (255, 232, 150), (W // 2, 170), ow=2)
        for i in range(NSLOTS):
            r = self.slot_rect(i)
            sv = self.saves[i]
            sel = i == self.slot_sel
            hero = next((h for h in HEROES if h["id"] == sv["hero"]), HEROES[0]) if sv else None
            col = hero["color"] if hero else (160, 134, 108)
            if sel:
                self.rrect(r.inflate(16, 16), (*col, 46), 24)
            self.chunky(r, (24, 17, 14) if sel else (10, 8, 8), None, 16, 4, 5 if sel else 3, alpha=240 if sel else 210)
            if sel:
                pygame.draw.rect(scr, mix(col, 0.3 * pulse), r, 3, border_radius=16)
            badge = pygame.Rect(r.x + 10, r.y + 8, 38, 38)
            self.chunky(badge, shade(col, 0.7) if sv else (26, 23, 23), None, 10, 3, 2)
            self.otext(str(i + 1), 28, (255, 255, 255), badge.center, ow=2)
            conf = self.confirm if (self.confirm and self.confirm[1] == i) else None
            if conf:
                msg = "Apagar este save?" if conf[0] == "del" else "Sobrescrever este save?"
                self.otext(msg, 28, (255, 140, 130), (r.x + 66, r.y + 6), ow=2, center=False)
                self.text("ENTER = sim    ESC = não", 20, (230, 230, 245), (r.x + 68, r.y + 34), center=False, shadow=False)
                continue
            if sv:
                self.draw_hero_iso(hero["id"], r.x + 100, r.bottom - 6, 0.85, sel, key=f"slot{i}", race=sv.get("race"))
                self.otext(sv["name"], 30, (255, 255, 255), (r.x + 140, r.y + 4), ow=2, center=False)
                self.text(f"{hero['name']}  •  Recorde: andar {sv['best']}  •  {sv['runs']} partida(s)", 19,
                          mix(col, 0.35), (r.x + 142, r.y + 34), center=False, shadow=False)
                dr = self.slot_del_rect(i)
                self.chunky(dr, (130, 40, 56), (220, 100, 110), 10, 2, 2)
                self.text("APAGAR", 18, (255, 235, 235), dr.center, shadow=False)
            else:
                self.text("— SLOT VAZIO —", 30, (120, 112, 104), (r.x + 70, r.centery), center=False, shadow=False)
                if sel:
                    self.text("ENTER: criar personagem", 20, (255, 226, 130), (r.right - 20 - self.font(20).size("ENTER: criar personagem")[0], r.centery), center=False, shadow=False)
        self.small_btn(self.back_rect(), "VOLTAR")
        self.draw_keybar(597, (("↑ ↓", "escolher"), ("ENTER", "criar" if create else "jogar"), ("DEL", "apagar"), ("ESC", "voltar")))

    def draw_create(self):
        scr, t = self.screen, self.t
        pulse = 0.5 + 0.5 * math.sin(t * 4)
        hero = HEROES[self.cr_cls]
        col = hero["color"]
        GREY = (168, 158, 144)
        self.otext(f"NOVO PERSONAGEM  •  SLOT {self.cr_slot + 1}", 30, (255, 232, 150), (W // 2, 122), ow=2)
        # --- abas
        for i, lab in enumerate(("CLASSE", "RAÇA", "ATRIBUTOS")):
            r = self.cr_tab_rect(i)
            sel = i == self.cr_tab
            self.chunky(r, shade(col, 0.5) if sel else (10, 8, 8), mix(col, 0.4) if sel else None, 14, 3, 4 if sel else 2,
                        alpha=245 if sel else 210)
            if sel:
                pygame.draw.rect(scr, mix(col, 0.3 * pulse), r, 3, border_radius=14)
            self.otext(f"{i + 1}   {lab}", 24, (255, 255, 255) if sel else (170, 166, 176), r.center, ow=1)
            if i < self.cr_tab and (i != 0 or self.cr_name.strip()):
                pygame.draw.circle(scr, (110, 220, 120), (r.right - 20, r.centery), 6)
        # --- prévia do personagem (sempre visível)
        pr = self.cr_prev_rect()
        self.chunky(pr, (11, 9, 9), None, 22, 4, 5, alpha=235)
        hdr = pygame.Rect(pr.x + 6, pr.y + 6, pr.w - 12, 190)
        self.rrect(hdr, (*shade(col, 0.16), 255), 16)
        self.rrect(pygame.Rect(hdr.x, hdr.y, hdr.w, 40), (*shade(col, 0.24), 120), 16)
        pcx, pcy = pr.centerx, hdr.y + 160
        fx_, by_ = pcx + 66, pcy + 14                        # a fogueira fica ao lado do herói
        scr.set_clip(hdr)
        scr.blit(self.fire_glow_s, (fx_ - 130, by_ - 70 - 130), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.ellipse(scr, (9, 8, 8), (pcx - 150, pcy - 2, 300, 62))          # chão
        pygame.draw.ellipse(scr, (22, 19, 18), (pcx - 128, pcy + 4, 256, 46))
        pygame.draw.ellipse(scr, (44, 38, 34), (fx_ - 40, by_ - 8, 80, 22))         # cinzas da fogueira
        pygame.draw.ellipse(scr, (66, 58, 52), (fx_ - 24, by_ - 6, 48, 13))
        self.draw_hero_sit(hero["id"], pcx - 62, pcy + 10, 2.7, key="create", race=RACES[self.cr_race]["id"])
        self.draw_fire(fx_, by_, 0.4)
        scr.blit(self.fire_sword_s, (fx_ - self.fire_sword_s.get_width() // 2, by_ - 52))
        for i in range(10):                                                          # brasas
            ph = (self.t * 0.2 + i * 0.1) % 1.0
            ex = fx_ + math.sin(self.t * 1.3 + i * 1.7) * (6 + ph * 20)
            ey = by_ - 14 - ph * 120
            a_ = 1.0 - ph
            pygame.draw.circle(scr, (int(255 * a_ ** 0.4), int((110 + 100 * a_) * a_), int(40 * a_)), (int(ex), int(ey)), 1 + (i % 3 == 0))
        scr.set_clip(None)
        pygame.draw.rect(scr, mix(col, 0.3 * pulse), pr, 3, border_radius=20)
        rb = pygame.Rect(pr.x + 20, hdr.bottom + 8, pr.w - 40, 30)
        self.chunky(rb, shade(col, 0.95), mix(col, 0.5), 10, 3, 2)
        nm = self.cr_name.strip()
        self.otext(nm if nm else "(sem nome)", 28, (255, 255, 255) if nm else (190, 170, 170), rb.center, ow=2)
        self.text(hero["title"], 19, mix(col, 0.25), (pr.centerx, rb.bottom + 18), shadow=False)
        self.text(f"{RACES[self.cr_race]['name']}  •  {hero['name']}", 20, (230, 226, 236), (pr.centerx, rb.bottom + 42), shadow=False)
        # --- painel da aba
        rp = self.cr_panel_rect()
        self.chunky(rp, (11, 9, 9), None, 22, 4, 5, alpha=235)
        if self.cr_tab == 0:
            self.draw_cr_class(rp, hero, col, pulse)
        elif self.cr_tab == 1:
            self.draw_cr_race(rp, col, pulse)
        else:
            self.draw_attr_panel(col)
        # --- botões
        if self.cr_msg and t < self.cr_msg_until:
            self.otext(self.cr_msg, 22, (255, 140, 130), (405, 550), ow=2)
        self.small_btn(self.back_rect(), "VOLTAR")
        self.big_btn(self.create_btn_rect(), "CRIAR E JOGAR" if self.cr_tab == 2 else "CONTINUAR  ►", True)
        if self.cr_tab == 0:
            mid = ("A-Z", "nome"), ("↑ ↓", "classe")
        elif self.cr_tab == 1:
            mid = (("↑ ↓", "raça"),)
        else:
            mid = ("↑ ↓", "atributo"), ("← →", "pontos")
        self.draw_keybar(597, (("TAB", "aba"),) + tuple(mid) + (("ENTER", "criar" if self.cr_tab == 2 else "continuar"), ("ESC", "voltar")))

    def draw_cr_class(self, rp, hero, col, pulse):
        scr, t = self.screen, self.t
        GREY = (168, 158, 144)
        self.text("NOME", 16, GREY, (rp.x + 18, rp.y + 12), center=False, shadow=False)
        fr = self.name_rect()
        self.chunky(fr, (6, 5, 5), None, 14, 4, 3)
        pygame.draw.rect(scr, mix((140, 98, 58), 0.4 * pulse), fr, 3, border_radius=14)
        f34 = self.font(34)
        ty = fr.centery - f34.get_height() // 2
        if self.cr_name:
            tr = self.otext(self.cr_name, 34, (255, 255, 255), (fr.x + 16, ty), ow=1, center=False)
            cx = tr.right + 4
        else:
            self.text("Digite o nome...", 30, (100, 92, 84), (fr.x + 16, fr.centery - self.font(30).get_height() // 2), center=False, shadow=False)
            cx = fr.x + 16
        if int(t * 2) % 2 == 0:
            pygame.draw.line(scr, (255, 226, 130), (cx, fr.y + 11), (cx, fr.bottom - 11), 3)
        self.text("CLASSE", 16, GREY, (rp.x + 18, rp.y + 82), center=False, shadow=False)
        for i, h in enumerate(HEROES):
            r = self.class_row_rect(i)
            sel = i == self.cr_cls
            hc = h["color"]
            self.chunky(r, shade(hc, 0.5) if sel else (10, 8, 8), mix(hc, 0.4) if sel else None, 12, 3, 3 if sel else 2, alpha=245 if sel else 210)
            if sel:
                pygame.draw.rect(scr, mix(hc, 0.3 * pulse), r, 3, border_radius=12)
            dot = pygame.Rect(r.x + 8, r.y + 4, 28, 28)
            self.chunky(dot, hc if sel else shade(hc, 0.65), mix(hc, 0.5), 8, 2, 0)
            self.otext(h["name"], 26, (255, 255, 255) if sel else (214, 216, 230), (r.x + 48, r.y + 5), ow=1, center=False)
        dx, dw = rp.x + 282, rp.w - 298
        self.text(hero["title"], 20, mix(col, 0.25), (dx, rp.y + 100), center=False, shadow=False)
        self.draw_pips(hero, dx, rp.y + 130, dw, col)
        self.text("BÔNUS DE CLASSE", 16, GREY, (dx, rp.y + 208), center=False, shadow=False)
        for j, (k, v) in enumerate(CLASS_ATTRS.get(hero["id"], {}).items()):
            self.text(f"+{v}  {ATTR_NAMES[k]}", 20, (150, 232, 170), (dx, rp.y + 230 + j * 22), center=False, shadow=False)

    def draw_cr_race(self, rp, col, pulse):
        scr = self.screen
        GREY = (168, 158, 144)
        for i, rc in enumerate(RACES):
            r = self.race_row_rect(i)
            sel = i == self.cr_race
            self.chunky(r, shade(col, 0.5) if sel else (10, 8, 8), mix(col, 0.4) if sel else None, 12, 3, 3 if sel else 2, alpha=245 if sel else 210)
            if sel:
                pygame.draw.rect(scr, mix(col, 0.3 * pulse), r, 3, border_radius=12)
            self.otext(rc["name"], 26, (255, 255, 255) if sel else (214, 216, 230), (r.x + 14, r.centery - 14), ow=1, center=False)
            sm = " ".join(f"+{v} {k.upper()}" for k, v in rc["bonus"].items())
            self.text(sm, 15, mix(col, 0.4) if sel else (130, 124, 118), (r.right - 10 - self.font(15).size(sm)[0], r.centery - 7), center=False, shadow=False)
        rc = RACES[self.cr_race]
        dx = rp.x + 282
        self.otext(rc["name"], 32, (255, 255, 255), (dx, rp.y + 18), ow=2, center=False)
        for j, ln in enumerate(RACE_DESC.get(rc["id"], ())):
            self.text(ln, 17, mix(col, 0.3), (dx, rp.y + 66 + j * 20), center=False, shadow=False)
        self.text("BÔNUS DE RAÇA", 16, GREY, (dx, rp.y + 146), center=False, shadow=False)
        for j, (k, v) in enumerate(rc["bonus"].items()):
            self.text(f"+{v}  {ATTR_NAMES[k]}", 20, (150, 232, 170), (dx, rp.y + 168 + j * 22), center=False, shadow=False)
        self.text("Soma com o bônus da classe.", 16, GREY, (dx, rp.y + 262), center=False, shadow=False)

    def draw_attr_panel(self, col):
        scr = self.screen
        pulse = 0.5 + 0.5 * math.sin(self.t * 4)
        ap = self.attr_panel_rect()
        free = self.cr_free()
        hid = HEROES[self.cr_cls]["id"]
        self.otext(f"DISTRIBUA SEUS PONTOS   (base {ATTR_BASE})", 20, (255, 232, 150), (ap.x + 18, ap.y + 10), ow=1, center=False)
        fl = f"Pontos livres: {free}"
        self.otext(fl, 22, (255, 226, 130) if free else (140, 132, 122), (ap.right - 18 - self.font(22).size(fl)[0], ap.y + 9), ow=1, center=False)
        cur = self.cr_attrs()
        for i, k in enumerate(ATTR_KEYS):
            r = self.attr_row_rect(i)
            sel = i == self.cr_attr
            self.chunky(r, shade(col, 0.4) if sel else (16, 13, 13), mix(col, 0.35) if sel else None, 10, 2, 2 if sel else 1, alpha=245 if sel else 200)
            if sel:
                pygame.draw.rect(scr, mix(col, 0.3 * pulse), r, 2, border_radius=10)
            self.otext(ATTR_NAMES[k], 22, (255, 255, 255) if sel else (214, 216, 230), (r.x + 10, r.centery - 12), ow=1, center=False)
            parts = []
            cb = CLASS_ATTRS.get(hid, {}).get(k, 0)
            rb = RACES[self.cr_race]["bonus"].get(k, 0)
            if cb:
                parts.append(f"classe +{cb}")
            if rb:
                parts.append(f"raça +{rb}")
            if self.cr_extra[i]:
                parts.append(f"livre +{self.cr_extra[i]}")
            self.text("  ·  ".join(parts), 15, mix(col, 0.4) if sel else (130, 124, 118), (r.x + 160, r.centery - 7), center=False, shadow=False)
            mi, pl = self.attr_minus_rect(i), self.attr_plus_rect(i)
            can_m = self.cr_extra[i] > 0
            can_p = free > 0 and cur[k] < ATTR_MAX
            self.chunky(mi, (60, 24, 20) if can_m else (14, 12, 12), (170, 80, 70) if can_m else None, 8, 2, 1)
            self.otext("-", 24, (255, 255, 255) if can_m else (80, 74, 70), mi.center, ow=1)
            self.chunky(pl, (24, 60, 28) if can_p else (14, 12, 12), (90, 170, 90) if can_p else None, 8, 2, 1)
            self.otext("+", 24, (255, 255, 255) if can_p else (80, 74, 70), pl.center, ow=1)
            vc = (255, 226, 130) if self.cr_extra[i] else (255, 255, 255)
            self.otext(str(cur[k]), 24, vc, ((mi.right + pl.x) // 2, r.centery), ow=1)
        self.text(ATTR_INFO[ATTR_KEYS[self.cr_attr]], 18, mix(col, 0.35), (ap.centerx, ap.bottom - 18), shadow=False)

    def menu_btn_rect(self):
        return pygame.Rect(W - 150, 96, 138, 39)

    def draw_menu_button(self):
        r = self.menu_btn_rect()
        self.screen.blit(px_get(("menubtn",), lambda: px_up(px_frame(46, 13, PX_CRIM, (92, 24, 52), t=1))), r.topleft)
        self.screen.blit(px_icon("house"), (r.x + 12, r.centery - 12))
        self.ptext("MENU [M]", 12, (255, 244, 232), (r.x + 88, r.centery), 2)

    def back_to_menu(self):
        """Volta para a tela de título (a próxima partida começa do zero ao apertar ENTER)."""
        if getattr(self, "mp_on", False):
            self.mp_leave()
            return
        self.save_progress()
        self.transition = None
        self.phase = "title"
        self.banner, self.banner_t = "", 0.0
        self.particles.clear()
        self.floaters.clear()
        self.flash_t = 0

    def draw_fight_btn(self, r, label, key, color, edge, frac, fs=44):
        ready = frac <= 0.001
        self.screen.blit(px_button(color, ready, frac), r.topleft)
        self.ptext(key, 16, (78, 44, 40), (r.x + 36, r.centery), 2, ol=None)
        self.ptext(label, 20, (255, 255, 255) if ready else (206, 206, 216), (r.centerx + 22, r.centery), 2)

    def draw_skill_btn(self, r, label, key, color, frac, cd):
        ready = frac <= 0.001
        q = int(min(1.0, max(0.0, frac)) * 20)
        img = px_get(("sbtn", tuple(color), ready, q, r.w, r.h),
                     lambda: pygame.transform.scale(px_button(color, ready, frac), (r.w, r.h)))
        self.screen.blit(img, r.topleft)
        self.ptext(key, 14, (78, 44, 40), (r.x + 27, r.centery), 2, ol=None)
        self.ptext(label if ready else "%.1fs" % cd, 14, (255, 255, 255) if ready else (206, 206, 216),
                   (r.centerx + 16, r.centery), 2, max_w=r.w - 62)

    def draw_fight_overlay(self):
        if self.phase != "fight":
            return
        many = len(self.alive_foes()) > 1
        for e in self.foes:
            if e["hp"] <= 0 or e["scale"] <= 0.02:
                continue
            x, y = self.view_map(*proj(e["x"], e["y"], e["z"] + 1.55 * e["s"]))
            winding = e.get("ai") == "wind"
            if winding:
                pulse = 0.5 + 0.5 * math.sin(self.t * 30)
                self.text("!", 78, mix((255, 70, 60), pulse * 0.45), (x, y - 14))
            if e is self.enemy:      # mira travada (TAB troca)
                my = y - (66 if winding else 36)
                pts = [(x - 10, my - 8), (x + 10, my - 8), (x, my + 10)]
                pygame.draw.polygon(self.screen, (20, 20, 30), [(a_ - 0, b_) for a_, b_ in pts], 0)
                pygame.draw.polygon(self.screen, (255, 236, 150), [(x - 7, my - 5), (x + 7, my - 5), (x, my + 6)], 0)
            elif many:               # barrinha de vida dos outros monstros
                frac = max(0.0, e["hp"] / max(1, e["maxhp"]))
                bw = 60
                pygame.draw.rect(self.screen, (16, 12, 22), (x - bw // 2 - 2, y - 22, bw + 4, 10), border_radius=5)
                pygame.draw.rect(self.screen, self.hp_color(frac), (x - bw // 2, y - 20, max(2, int(bw * frac)), 6), border_radius=3)

    def view_map(self, x, y):
        """Converte um ponto da cena (sem zoom) para a tela, considerando a câmera travada."""
        r = getattr(self, "view_rect", None)
        if r is None:
            return (x, y)
        return ((x - r.x) * W / r.w, (y - r.y) * H / r.h)

    def apply_fight_cam(self):
        """Câmera da luta: aproxima (zoom) e enquadra o herói e o alvo travado juntos, com transição suave."""
        self.view_rect = None
        k = self.fc_k
        e = self.enemy
        if e is not None and self.phase in ("fight", "killed"):
            ph_ = proj(self.px, self.py, self.pz + 0.8)
            pe = proj(e["x"], e["y"], e["z"] + 0.9 * e["s"])
            mid = ((ph_[0] + pe[0]) / 2, (ph_[1] + pe[1]) / 2)
            zt = max(1.0, min(1.45, 0.92 * W / (abs(ph_[0] - pe[0]) + 260), 0.92 * (H - 165) / (abs(ph_[1] - pe[1]) + 300)))
            if self.fc_focus is None:
                self.fc_focus = (mid, zt)
            else:
                (cx, cy), cz = self.fc_focus
                a_ = 1.0 - math.exp(-7.0 * getattr(self, "dt_last", 1.0 / 60.0))
                self.fc_focus = ((cx + (mid[0] - cx) * a_, cy + (mid[1] - cy) * a_), cz + (zt - cz) * a_)
        if k < 0.01 or self.fc_focus is None:
            return
        bs, zfull = self.fc_focus
        s = k * k * (3 - 2 * k)
        z = 1.0 + (zfull - 1.0) * s
        bf = (bs[0], bs[1] + 0.10 * H / zfull)          # um pouco acima do meio (o painel cobre embaixo)
        f = (W / 2 + (bf[0] - W / 2) * s, H / 2 + (bf[1] - H / 2) * s)
        cw, chh = max(1, int(W / z)), max(1, int(H / z))
        rect = pygame.Rect(int(f[0] - cw / 2), int(f[1] - chh / 2), cw, chh)
        rect.clamp_ip(self.screen.get_rect())
        if rect.w < W:
            self.screen.blit(pygame.transform.smoothscale(self.screen.subsurface(rect), (W, H)), (0, 0))
            self.view_rect = rect

    def handle_click(self, pos):
        if self.settings_open:
            return
        if self.smith_open:
            self.smith_click(pos)
            return
        if self.mk_open:
            self.mk_click(pos)
            return
        if self.inv_open:
            self.inv_click(pos)
            return
        if self.phase in MENU_PHASES:
            self.menu_click(pos)
            return
        if self.phase == "mp":
            self.mp_game_click(pos)
            return
        if self.inv_hud_rect().collidepoint(pos):          # clicar nos slots do HUD abre o inventário
            self.open_inv()
            return
        if self.phase == "stairs" and self.smith_hint is not None and self.smith_hint.collidepoint(pos) and self.smith_near():
            self.open_smith()
            return
        if self.phase == "stairs" and self.mk_hint is not None and self.mk_hint.collidepoint(pos) and self.market_near():
            self.open_market()
            return
        if self.phase != "fight":
            return
        for i_, r_ in enumerate(self.skill_btns()):
            if r_.collidepoint(pos):
                self.fight_skill(i_)
                return
        rb, ab, hb = self.fight_btns()
        if rb.collidepoint(pos):
            self.fight_roll()
        elif ab.collidepoint(pos):
            self.fight_attack()
        elif hb.collidepoint(pos):
            self.fight_heavy()
        elif pos[1] < H - 165 and not self.menu_btn_rect().collidepoint(pos):
            self.fight_attack()          # clique na cena = ataque leve

    def draw_panel(self):
        scr, t = self.screen, self.t
        top = H - 165
        pan = pygame.Surface((W, 165), pygame.SRCALPHA)
        for yy in range(165):
            pygame.draw.line(pan, (7 + yy // 30, 5 + yy // 36, 11 + yy // 22, 238), (0, yy), (W, yy))
        scr.blit(pan, (0, top))
        # moldura de aço com rebites no topo do painel
        for i, c in enumerate((PX_OL, PX_STEEL[0], PX_STEEL[1], PX_OL)):
            scr.fill(c, (0, top + i * 3, W, 3))
        for x in range(48, W, 96):
            scr.fill(PX_OL, (x - 6, top + 2, 12, 8))
            scr.fill(PX_STEEL[0], (x - 3, top + 4, 6, 3))
        if self.phase == "fight":
            r1 = pygame.Rect(18, top + 18, 231, 36)
            scr.blit(px_chip(77, 12, PX_TAN, (58, 40, 48)), r1.topleft)
            scr.blit(px_get(("iconx", "sword9"), lambda: px_up(px_build_icon("sword9"))), (r1.x + 9, r1.y + 3))
            self.ptext(f"Dano: {self.dmg_value()}", 14, (255, 232, 130), (r1.x + 138, r1.centery), 2)
            sq = pygame.Rect(W - 249, top + 18, 231, 36)
            scr.blit(px_chip(77, 12, PX_TAN, (40, 62, 52)), sq.topleft)
            self.ptext("Seq.", 12, (150, 255, 190), (sq.x + 40, sq.centery), 2)
            for i in range(5):
                on = i < min(self.streak, 5)
                cx, cy = sq.x + 96 + i * 26, sq.centery
                scr.fill(PX_OL, (cx - 7, cy - 7, 15, 15))
                scr.fill((255, 190, 60) if on else (46, 84, 66), (cx - 4, cy - 4, 9, 9))
                if on:
                    scr.fill((255, 238, 160), (cx - 4, cy - 4, 9, 3))
            winding = any(f_["hp"] > 0 and f_.get("ai") in ("wind", "strike") for f_ in self.foes)
            if self.hurt_t > 0:
                st, sc = "Ai! Você foi atingido!", (255, 120, 100)
            elif self.rolling and self.roll_t <= self.ROLL_IFR:
                st, sc = "IMORTAL!", (130, 225, 255)
            elif winding:
                st, sc = "CUIDADO! Role na hora do golpe!", (255, 120, 100)
            elif self.stam <= 0.5:
                st, sc = "Sem fôlego! Espere recuperar...", (255, 190, 110)
            else:
                st, sc = self.fight_hint(), (225, 228, 245)
            self.ptext(st, 18, sc, (W // 2, top + 62), 2, max_w=W - 40)
            rb, ab, hb = self.fight_btns()
            ok = self.stam > 0
            rf = 1.0 if (self.rolling or not ok) else self.roll_cd / self.ROLL_CD
            af = (1.0 - self.rt / self.SWING_T) if (self.swinging and not self.heavy) else (0.0 if ok else 1.0)
            hf = (1.0 - self.rt / self.HEAVY_T) if (self.swinging and self.heavy and not self.skill_cur) else (0.0 if ok else 1.0)
            self.draw_fight_btn(rb, "ROLAR", "K", (50, 110, 190), (170, 215, 255), rf, 38)
            self.draw_fight_btn(ab, "ATACAR", "J", (190, 70, 50), (255, 190, 150), af, 38)
            self.draw_fight_btn(hb, "FORTE", "L", (150, 60, 160), (230, 170, 255), hf, 38)
            for i_, r_ in enumerate(self.skill_btns()):
                d_ = SKILLS[self.hero["id"]][i_]
                self.draw_skill_btn(r_, d_["name"], d_["key"], d_["color"], self.sk_cd[i_] / d_["cd"], self.sk_cd[i_])
        else:
            msg = {"arrive": "Descendo para a masmorra...", "walk": "O herói avança sozinho até o inimigo...",
                   "killed": "Inimigo derrotado!", "stairs": "Indo para a escada...",
                   "descend": "Descendo mais fundo...", "dead": "O herói desmaiou..."}.get(self.phase, "")
            if self.manual():
                msg = {"walk": "Mova o herói até um inimigo  (WASD / setas)", "stairs": "Vá até a escada para descer!"}.get(self.phase, msg)
            dots = "." * (int(t * 3) % 4)
            self.ptext(msg.rstrip(".") + (dots if msg.endswith("...") else ""), 20, (230, 230, 245), (W // 2, top + 82), 2, max_w=W - 40)

    # ---------------------------------------------------------- MENU / TÍTULO
    def title_backdrop(self, rng):
        """Fundo estilo BONFIRE (Dark Souls): ruínas escuras na névoa e chão de cinzas.
        Devolve (céu opaco, paisagem transparente). O fogo e as brasas são animados em draw_bonfire_bg."""
        sky = pygame.Surface((W, H))
        for y in range(H):
            sky.fill(mix((2, 3, 6), (y / H) ** 1.9, (24, 11, 6)), (0, y, W, 1))
        sky.blit(make_glow(160, (11, 12, 17)), (730 - 160, 70 - 160), special_flags=pygame.BLEND_RGB_ADD)   # lua fraca

        def ruins(col, base, hmin, hmax):
            x = -30
            while x < W + 40:
                w, h = rng.randint(30, 96), rng.randint(hmin, hmax)
                k = rng.random()
                if k < 0.35:        # torre quebrada
                    pygame.draw.polygon(sky, col, [(x, base), (x, base - h), (x + w * 0.3, base - h - rng.randint(0, 14)),
                                                   (x + w * 0.55, base - h + rng.randint(4, 18)),
                                                   (x + w, base - h * rng.uniform(0.5, 0.9)), (x + w, base)])
                elif k < 0.65:      # arco em ruína
                    pygame.draw.rect(sky, col, (x, base - h, 11, h))
                    pygame.draw.rect(sky, col, (x + w - 11, base - int(h * 0.8), 11, int(h * 0.8)))
                    pygame.draw.arc(sky, col, pygame.Rect(x, base - h - w // 2, w, w), 0, math.pi * 0.62, 11)
                else:               # muralha com ameias quebradas
                    pts = [(x, base)]
                    for i in range(5):
                        top = base - h + rng.randint(-14, 10)
                        pts += [(x + w * i / 5, top), (x + w * (i + 0.6) / 5, top)]
                    pts += [(x + w, base)]
                    pygame.draw.polygon(sky, col, pts)
                x += w + rng.randint(-14, 46)

        ruins((11, 10, 14), 470, 70, 170)
        band = pygame.Surface((W, 140), pygame.SRCALPHA)           # névoa entre as camadas
        for y in range(140):
            band.fill((40, 26, 20, int(56 * math.sin(math.pi * y / 140))), (0, y, W, 1))
        sky.blit(band, (0, 360))
        ruins((5, 5, 7), 500, 40, 120)

        land = pygame.Surface((W, H), pygame.SRCALPHA)
        gy = 524
        pts = [(0, H), (0, gy + 16)]
        for x in range(0, W + 40, 40):
            pts.append((x, gy + rng.randint(-8, 10) + int(14 * math.sin(x / 130.0))))
        pts.append((W, H))
        pygame.draw.polygon(land, (7, 6, 6), pts)
        for _ in range(700):                                         # textura de terra e cinza
            x, y = rng.randint(0, W - 1), rng.randint(gy + 6, H - 1)
            v = rng.randint(16, 34)
            land.fill((v, v - 2, v - 3, 255), (x, y, rng.randint(1, 3), 1))
        for cx in (60, 150, 820, 905, 300, 650):                     # pedras e lápides quebradas
            w, h = rng.randint(16, 34), rng.randint(14, 34)
            by = gy + rng.randint(26, 70)
            pygame.draw.polygon(land, (7, 6, 7), [(cx, by), (cx + 3, by - h), (cx + w // 2, by - h - 6), (cx + w, by - h + 4), (cx + w, by)])
        def branch(x, y, ang, ln, wd, d):
            if d == 0 or ln < 6:
                return
            x2, y2 = x + math.cos(ang) * ln, y - math.sin(ang) * ln
            pygame.draw.line(land, (6, 5, 6), (x, y), (x2, y2), max(1, int(wd)))
            for da in (-0.5, 0.45):
                branch(x2, y2, ang + da + rng.uniform(-0.25, 0.25), ln * rng.uniform(0.62, 0.78), wd * 0.68, d - 1)
        branch(92, gy + 34, math.pi / 2 + 0.12, 74, 9, 6)            # árvores mortas
        branch(872, gy + 28, math.pi / 2 - 0.12, 84, 10, 6)
        # montinho de cinzas da fogueira
        fx, fy = W // 2, 524
        pygame.draw.ellipse(land, (30, 27, 26), (fx - 118, fy + 6, 236, 54))
        pygame.draw.ellipse(land, (52, 47, 44), (fx - 96, fy + 2, 192, 40))
        pygame.draw.ellipse(land, (70, 62, 56), (fx - 62, fy - 2, 124, 26))
        for _ in range(90):
            x = fx + int(rng.gauss(0, 46)); y = fy + 8 + int(rng.gauss(0, 7))
            v = rng.randint(36, 96)
            land.fill((v, v - 4, v - 8, 255), (x, y, 2, 1))
        for _ in range(26):                                          # brasas apagadas/acesas no chão
            x = fx + int(rng.gauss(0, 54)); y = fy + 10 + int(rng.gauss(0, 8))
            land.fill((rng.randint(150, 230), rng.randint(50, 90), 12, 255), (x, y, 2, 2))
        return sky, land

    def build_bonfire(self, rng):
        """Recursos do fogo animado: brilhos, névoa rolante e a espada em espiral cravada nas cinzas."""
        self.fire_x, self.fire_y = W // 2, 524
        self.fire_glows = [make_glow(320, (int(118 * k), int(50 * k), int(9 * k))) for k in (0.5, 0.75, 1.0)]
        self.fire_core = make_glow(110, (150, 80, 16))
        self.fire_floor = pygame.transform.smoothscale(make_glow(230, (66, 26, 5)), (460, 96))
        self.menu_dim = pygame.Surface((W, H), pygame.SRCALPHA)
        self.menu_dim.fill((0, 0, 0, 96))
        fog = pygame.Surface((W * 2, 150), pygame.SRCALPHA)
        for _ in range(24):
            cx, cy = rng.randint(0, W * 2), rng.randint(50, 100)
            rw, rh = rng.randint(160, 320), rng.randint(30, 60)
            blob = pygame.Surface((rw, rh), pygame.SRCALPHA)
            for k in range(7):
                pygame.draw.ellipse(blob, (100, 90, 82, 2 + k * 2), pygame.Rect(0, 0, rw, rh).inflate(-k * rw // 9, -k * rh // 9))
            for dx in (0, -W * 2):
                fog.blit(blob, (cx - rw // 2 + dx, cy - rh // 2))
        self.fire_fog = fog
        sw = pygame.Surface((90, 136), pygame.SRCALPHA)
        cx = 45
        pygame.draw.polygon(sw, (84, 86, 96), [(cx - 5, 60), (cx + 5, 60), (cx + 4, 136), (cx - 4, 136)])   # lâmina cravada
        pygame.draw.line(sw, (168, 168, 178), (cx - 1, 60), (cx - 1, 136), 1)
        pygame.draw.rect(sw, (54, 46, 42), (cx - 27, 50, 54, 10), border_radius=4)                            # guarda
        pygame.draw.line(sw, (132, 108, 84), (cx - 24, 52), (cx + 24, 52), 1)
        pygame.draw.rect(sw, (40, 28, 24), (cx - 4, 22, 8, 28))                                               # empunhadura
        for y in range(24, 50, 5):
            pygame.draw.line(sw, (96, 70, 52), (cx - 4, y), (cx + 4, y + 3), 1)
        pygame.draw.circle(sw, (66, 56, 48), (cx, 16), 8)                                                     # pomo
        pygame.draw.circle(sw, (130, 112, 92), (cx - 2, 14), 2)
        for i in range(5):                                                                                    # espiral (coil)
            y = 66 + i * 13
            pygame.draw.arc(sw, (214, 112, 40), pygame.Rect(cx - 15, y, 30, 9), math.pi, 2 * math.pi, 2)
            pygame.draw.arc(sw, (60, 40, 30), pygame.Rect(cx - 15, y + 3, 30, 9), 0, math.pi, 2)
        self.bonfire_sword = sw
        self.fire_sword_s = pygame.transform.smoothscale(sw, (36, 54))
        self.fire_glow_s = make_glow(130, (120, 52, 9))

    def build_title_art(self):
        rng = random.Random(7)
        self.title_sky, self.title_land = self.title_backdrop(rng)
        self.build_bonfire(rng)
        self.title_stars = []
        self.title_windows = []

        # título em degradê com contorno (cache)
        def grad_text(s, size, c1, c2, outline=4, with_base=False):
            f = self.title_font(size)
            while size > 24 and f.size(s)[0] > W - 80:      # fontes largas: ajusta para caber na tela
                size -= 4
                f = self.title_font(size)
            txt = f.render(s, True, (255, 255, 255))
            w, h = txt.get_size()
            out = pygame.Surface((w + outline * 2 + 8, h + outline * 2 + 14), pygame.SRCALPHA)
            ink = f.render(s, True, (24, 12, 40))
            for ox in range(-outline, outline + 1):
                for oy in range(-outline, outline + 1):
                    if ox * ox + oy * oy <= outline * outline + 1:
                        out.blit(ink, (outline + 4 + ox, outline + 4 + oy))
            out.blit(f.render(s, True, (10, 6, 20)), (outline + 4, outline + 10))
            g = pygame.Surface((w, h), pygame.SRCALPHA)
            for yy in range(h):
                g.fill(mix(c1, yy / max(1, h - 1), c2), (0, yy, w, 1))
            g.blit(txt, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            out.blit(g, (outline + 4, outline + 4))
            if with_base:
                return out, outline + 4 + txt.get_bounding_rect().bottom
            return out


        def red_cap(ch, size, outline=6):
            """Letra capitular no estilo do 'D' do logo de D&D: vermelha em degradê, contorno preto grosso,
            brilho de metal na borda de cima e sombra projetada. Devolve (imagem recortada, linha de base)."""
            f = self.title_font(size)
            txt = f.render(ch, True, (255, 255, 255))
            w, h = txt.get_size()
            bb = txt.get_bounding_rect()
            pad = outline + 12
            out = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
            ink = f.render(ch, True, (22, 4, 10))
            for ox in range(-outline, outline + 1):
                for oy in range(-outline, outline + 1):
                    if ox * ox + oy * oy <= outline * outline + 1:
                        out.blit(ink, (pad + ox, pad + oy))
            out.blit(ink, (pad, pad + outline + 4))                                  # sombra
            out.blit(f.render(ch, True, (255, 228, 216)), (pad - 1, pad - 2))        # brilho de metal
            g = pygame.Surface((w, h), pygame.SRCALPHA)
            span = max(1, bb.height - 1)
            for yy in range(h):
                k = min(1.0, max(0.0, (yy - bb.top) / span))
                col = (mix((255, 118, 100), k / 0.5, (212, 30, 46)) if k < 0.5
                       else mix((212, 30, 46), (k - 0.5) / 0.5, (116, 8, 26)))
                g.fill(col, (0, yy, w, 1))
            g.blit(txt, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            out.blit(g, (pad, pad))
            r = out.get_bounding_rect()
            return out.subsurface(r).copy(), pad + bb.bottom - r.top

        def make_title1(word, size):
            """'M' grande e vermelho (como o D do logo) + resto da palavra, com um rabo em lâmina por baixo."""
            while True:
                m_img, m_gb = red_cap(word[0], int(size * 1.34))
                r_img, r_gb = grad_text(word[1:], size, (240, 112, 84), (174, 42, 48), with_base=True)
                rc = r_img.get_bounding_rect()
                r_gb -= rc.top
                r_img = r_img.subsurface(rc).copy()
                gap = -int(size * 0.05)
                m_w = m_img.get_width()
                tw = m_w + gap + r_img.get_width()
                if (m_gb <= 90 and tw <= W - 230) or size <= 40:
                    break
                size -= 4
            cv = pygame.Surface((tw, m_gb + 32), pygame.SRCALPHA)
            cv.blit(r_img, (m_w + gap, m_gb - r_gb))
            cv.blit(m_img, (0, 0))
            return cv, m_gb

        self.title_l1, self.title_l1_base = make_title1("OBSCURITY", 118)
        self.title_l2 = pygame.Surface((2, 2), pygame.SRCALPHA)       # sem subtítulo: só o nome do jogo
        self.build_title_logo()
        self.title_syms = []
        for i, sym in enumerate("+-×÷=?+×÷-+×÷=?"):
            self.title_syms.append((sym, rng.randint(20, W - 20), rng.uniform(10, 28), rng.randint(34, 70), rng.random()))
        self.title_sym_img = {}
        for sym, _, _, size, _ in self.title_syms:
            if (sym, size) not in self.title_sym_img:
                im = self.font(size).render(sym, True, (250, 232, 200)).convert_alpha()
                im.fill((255, 255, 255, 70), special_flags=pygame.BLEND_RGBA_MULT)
                self.title_sym_img[(sym, size)] = im
        self.title_glows = {h["id"]: make_glow(96, tuple(int(c * 0.42) for c in h["color"])) for h in HEROES}

    def rrect(self, rect, color, radius=14, border=0, bcolor=None):
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
        if border and bcolor:
            pygame.draw.rect(s, bcolor, s.get_rect(), border, border_radius=radius)
        self.screen.blit(s, rect.topleft)

    # ------------------------------------------------ HUD do menu (estilo Hora de Aventura)
    INK = (7, 5, 9)

    def chunky(self, rect, fill, edge=None, radius=16, lw=4, drop=5, ink=INK, alpha=255):
        """Painel 'cartoon': contorno grosso escuro, cor chapada, brilho no topo e sombra projetada."""
        if drop:
            self.rrect(rect.move(0, drop).inflate(lw * 2, lw * 2), (*ink, 120), radius + lw)
        self.rrect(rect.inflate(lw * 2, lw * 2), (*ink, 255), radius + lw)
        self.rrect(rect, (*fill, alpha), radius)
        if edge:
            pygame.draw.line(self.screen, edge, (rect.x + radius, rect.y + 3), (rect.right - radius, rect.y + 3), 2)

    def otext(self, s, size, color, pos, ink=INK, ow=2, center=True):
        """Texto com contorno grosso."""
        f = self.font(size)
        img = f.render(s, True, color)
        r = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
        sh = f.render(s, True, ink)
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if (dx or dy) and dx * dx + dy * dy <= ow * ow + 1:
                    self.screen.blit(sh, r.move(dx, dy))
        self.screen.blit(img, r)
        return r

    def ink_poly(self, pts, col, lw=3, ink=INK):
        pts = [(int(x), int(y)) for x, y in pts]
        pygame.draw.polygon(self.screen, ink, pts)
        n = len(pts)
        for i in range(n):
            pygame.draw.line(self.screen, ink, pts[i], pts[(i + 1) % n], lw * 2)
            pygame.draw.circle(self.screen, ink, pts[i], lw)
        pygame.draw.polygon(self.screen, col, pts)

    def draw_crown(self, cx, cy, col):
        pts = [(cx - 10, cy + 7), (cx + 10, cy + 7), (cx + 12, cy - 7), (cx + 5, cy - 1), (cx, cy - 10), (cx - 5, cy - 1), (cx - 12, cy - 7)]
        self.ink_poly(pts, col, 2)

    def icon_vec(self, kind, cx, cy, s, col):
        scr, ink = self.screen, self.INK
        if kind == "vida":          # coração
            for g, c in ((2, ink), (0, col)):
                pygame.draw.circle(scr, c, (int(cx - 0.5 * s), int(cy - 0.3 * s)), int(0.55 * s) + g)
                pygame.draw.circle(scr, c, (int(cx + 0.5 * s), int(cy - 0.3 * s)), int(0.55 * s) + g)
                pygame.draw.polygon(scr, c, [(int(cx - 1.02 * s - g), int(cy - 0.05 * s)), (int(cx + 1.02 * s + g), int(cy - 0.05 * s)),
                                             (int(cx), int(cy + 1.05 * s + g))])
        elif kind == "crit":        # estrela
            pts = []
            for i in range(10):
                rr = s if i % 2 == 0 else s * 0.45
                a = -math.pi / 2 + i * math.pi / 5
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            self.ink_poly(pts, col, 2)
        else:                       # espadinha
            p0, p1 = (int(cx - s * 0.7), int(cy + s * 0.7)), (int(cx + s * 0.8), int(cy - s * 0.8))
            g0, g1 = (int(cx - s * 0.7), int(cy - s * 0.1)), (int(cx + s * 0.1), int(cy + s * 0.7))
            pygame.draw.line(scr, ink, p0, p1, 7)
            pygame.draw.line(scr, ink, g0, g1, 7)
            pygame.draw.circle(scr, ink, p0, 4)
            pygame.draw.line(scr, col, p0, p1, 3)
            pygame.draw.line(scr, (255, 214, 90), g0, g1, 3)

    def draw_glint(self, x, y, size, k):
        if k < 0.04:
            return
        a, b = size, size * 0.2
        pts = [(x, y - a), (x + b, y - b), (x + a, y), (x + b, y + b), (x, y + a), (x - b, y + b), (x - a, y), (x - b, y - b)]
        pygame.draw.polygon(self.screen, (255, 255, 255), [(int(px), int(py)) for px, py in pts])
        pygame.draw.circle(self.screen, (255, 255, 255), (int(x), int(y)), max(1, int(size * 0.25)))

    def draw_sword_glints(self, bob):
        info = getattr(self, "title_sword", None)
        if not info:
            return
        t = self.t
        k2 = max(0.0, math.sin(t * 2.0 + 1.0)) ** 3       # brilho na ponta da espada
        self.draw_glint(info["tip"][0], info["tip"][1] + bob, 6 + 14 * k2, k2)
        self.draw_glint(W - 62, 44, 13 + 5 * math.sin(t * 3.0), 1.0)    # estrelinha no canto do céu (como na abertura)

    def make_sword(self, cols):
        """Espada em pixel art na horizontal (ponta para a direita), com a paleta da referência: contorno quase preto,
        lâmina ciano/branca (lado iluminado) e azul-acinzentada (lado da sombra) separadas por um fio escuro,
        guarda laranja/dourada com contorno vinho, cabo vermelho e pomo dourado. A lâmina se estica até `cols` colunas."""
        R, c = 17, 8
        D, Cy, Wh, Sl, Lb = (33, 32, 44), (163, 224, 234), (255, 255, 255), (75, 81, 114), (122, 175, 199)
        Gd, Or, Dk, Mr, Cr = (245, 176, 83), (221, 115, 49), (174, 63, 40), (76, 22, 30), (251, 239, 205)
        Rd, Rr, Kk = (192, 25, 33), (142, 26, 45), (39, 17, 33)
        surf = pygame.Surface((cols, R), pygame.SRCALPHA)
        cross = [D, Cy, Cy, Wh, Wh, D, Sl, Lb, Lb, Sl, D]       # corte da lâmina (de cima para baixo)
        for x in range(22, cols):
            k = cols - 1 - x                                    # distância até a ponta
            half = min(5, k // 2)
            for dr in range(-half, half + 1):
                idx = 5 + dr
                col = cross[idx]
                if abs(dr) == half:
                    col = D
                elif idx == 4 and (x * 5 // 7) % 6 == 0:
                    col = Cy
                elif idx == 3 and x % 19 < 3:
                    col = Cy
                elif idx == 2 and x % 23 == 0:
                    col = Wh
                elif idx == 7 and x % 9 < 2:
                    col = Sl
                surf.set_at((x, c + dr), col)
        for x in range(8, 20):                                  # cabo com tiras diagonais
            for y in range(5, 12):
                surf.set_at((x, y), Kk if y in (5, 11) else (Rd if (x + y) % 4 < 2 else Rr))
        for y in range(R):                                      # guarda
            for x in range(20, 26):
                if y in (0, R - 1) and x in (20, 25):
                    continue
                if y in (0, R - 1) or x in (20, 25):
                    col = Mr
                else:
                    col = Gd if x <= 22 else (Or if x == 23 else Dk)
                surf.set_at((x, y), col)
        for y in (3, 4):
            surf.set_at((21, y), Cr)
        for x in range(0, 9):                                   # pomo redondo
            for y in range(R):
                dx, dy = x - 4, y - c
                d = math.hypot(dx, dy)
                if d <= 3.7:
                    tt = (dx + dy) / 7.4
                    surf.set_at((x, y), Gd if tt < -0.3 else (Dk if tt > 0.3 else Or))
                elif d <= 4.8:
                    surf.set_at((x, y), Mr)
        surf.set_at((2, c - 2), Cr)
        surf.set_at((3, c - 3), Cr)
        return pygame.transform.scale(surf, (cols * 5, R * 5))

    def build_title_logo(self):
        """Pré-monta o logo: a espada fica atrás das letras (como na abertura da série), com o cabo e a ponta saindo
        dos dois lados do nome."""
        LH = 200
        l1, l2 = self.title_l1, self.title_l2
        l1w = l1.get_width()
        lx, ly = (W - l1w) // 2, 96 - self.title_l1_base
        l2r = l2.get_rect(center=(W // 2, 130))
        sw = self.make_sword(int(min(W - 40, l1w + 240) // 5))
        sx, sy = (W - sw.get_width()) // 2, 104 - sw.get_height() // 2
        logo = pygame.Surface((W, LH), pygame.SRCALPHA)
        logo.blit(sw, (sx, sy))
        logo.blit(l2, l2r)
        logo.blit(l1, (lx, ly))
        try:
            logo = logo.convert_alpha()
        except Exception:
            pass
        self.title_logo = logo
        self.title_sword = {"tip": (sx + sw.get_width() - 6, sy + sw.get_height() // 2)}

    def draw_keybar(self, cy, items=None):
        items = items or (("ENTER", "jogar"), ("C", "config."), ("T", "auto/manual"), ("F11", "tela cheia"), ("ESC", "sair"))
        f = self.font(19)
        gap, pad = 16, 20
        widths = [(max(28, f.size(k)[0] + 16), f.size(lab)[0]) for k, lab in items]
        total = sum(kw + 7 + lw for kw, lw in widths) + gap * (len(items) - 1)
        bar = pygame.Rect(0, 0, total + pad * 2, 36)
        bar.center = (W // 2, cy)
        self.chunky(bar, (7, 6, 6), None, 18, 3, 3, alpha=240)
        x = bar.x + pad
        for (k, lab), (kw, lw) in zip(items, widths):
            kr = pygame.Rect(x, cy - 12, kw, 24)
            self.chunky(kr, (150, 142, 128), (190, 180, 164), 7, 2, 2)
            self.text(k, 19, (34, 24, 22), kr.center, shadow=False)
            self.text(lab, 19, (168, 158, 144), (x + kw + 7 + lw // 2, cy), shadow=False)
            x += kw + 7 + lw + gap

    # ------------------------------------------------ cutscene de chefe (estilo apresentação de boss de D&D)
    BI_DUR = 7.2
    BOSS_EPITHETS = {
        "goblin_chief": "O Saqueador das Cavernas", "dragon": "Terror das Chamas Eternas",
        "werewolf": "A Fera da Lua Cheia", "bat_queen": "Soberana da Noite Sem Fim",
        "orc_chief": "Senhor da Guerra", "goblin_king": "O Tirano Esmeralda",
        "beholder": "O Olho que Tudo Vê", "minotaur": "Guardião do Labirinto",
        "lich": "Mestre dos Mortos", "mind_flayer": "Pesadelo dos Sábios",
    }

    def start_boss_intro(self):
        self.phase = "bossintro"
        self.bi_t = 0.0
        self.bi_roared = False
        self.moving = False
        self.banner_t = 0.0
        self.play("boom")

    def update_boss_intro(self, dt):
        self.bi_t += dt
        e = self.enemy
        if not self.bi_roared and self.bi_t >= 3.3 and e is not None:     # o chefe ruge
            self.bi_roared = True
            self.shake = 16
            self.flash_t = 0.3
            self.play("roar")
            self.spawn(e["x"], e["y"], e["z"] + 0.1, (200, 190, 176), 36, 3.2)
            self.spawn(e["x"], e["y"], e["z"] + 0.3, (255, 120, 70), 18, 2.4)
        if self.bi_t >= self.BI_DUR:
            self.phase = "walk"

    def boss_card(self, kind):
        """Nome do chefe em letras grandes (vermelho em degradê, contorno grosso e sombra) — fica em cache."""
        cache = self.__dict__.setdefault("_boss_cards", {})
        if kind in cache:
            return cache[kind]
        name = ENEMY_NAMES.get(kind, kind).upper()
        size = 88
        while True:
            f = self.title_font(size)
            if f.size(name)[0] <= W - 120 or size <= 36:
                break
            size -= 4
        outline = 5
        txt = f.render(name, True, (255, 255, 255))
        w, h = txt.get_size()
        out = pygame.Surface((w + outline * 2 + 16, h + outline * 2 + 20), pygame.SRCALPHA)
        ink = f.render(name, True, (18, 4, 10))
        ox0, oy0 = outline + 8, outline + 4
        for dx in range(-outline, outline + 1):
            for dy in range(-outline, outline + 1):
                if dx * dx + dy * dy <= outline * outline + 1:
                    out.blit(ink, (ox0 + dx, oy0 + dy))
        out.blit(ink, (ox0, oy0 + outline + 5))
        out.blit(f.render(name, True, (255, 230, 220)), (ox0 - 1, oy0 - 2))
        g = pygame.Surface((w, h), pygame.SRCALPHA)
        bb = txt.get_bounding_rect()
        span = max(1, bb.height - 1)
        for yy in range(h):
            k = min(1.0, max(0.0, (yy - bb.top) / span))
            col = (mix((255, 150, 110), k / 0.5, (210, 30, 44)) if k < 0.5
                   else mix((210, 30, 44), (k - 0.5) / 0.5, (110, 8, 24)))
            g.fill(col, (0, yy, w, 1))
        g.blit(txt, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        out.blit(g, (ox0, oy0))
        cache[kind] = out
        return out

    def atext(self, s, size, color, pos, alpha, ink=INK, ow=2):
        """Texto com contorno e transparência (para fades)."""
        if alpha <= 3:
            return
        f = self.font(size)
        img, sh = f.render(s, True, color), f.render(s, True, ink)
        img.set_alpha(alpha)
        sh.set_alpha(alpha)
        r = img.get_rect(center=pos)
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if (dx or dy) and dx * dx + dy * dy <= ow * ow + 1:
                    self.screen.blit(sh, r.move(dx, dy))
        self.screen.blit(img, r)

    def draw_boss_intro(self):
        """Câmera de cinema sobre a cena já desenhada: herói -> panorâmica até o chefe -> zoom -> rugido -> nome."""
        scr, t, D = self.screen, self.bi_t, self.BI_DUR
        e = self.enemy
        if e is None:
            return

        def cl(x):
            return max(0.0, min(1.0, x))

        def sm(x):
            x = cl(x)
            return x * x * (3 - 2 * x)

        def lerp(a, b, k):
            return a + (b - a) * k

        hs = proj(self.px, self.py, self.pz + 0.9)
        bs = proj(e["x"], e["y"], e["z"] + 0.9 * e["s"])
        zhold = max(1.5, min(2.1, 2.1 - 0.35 * (e["s"] - 1.0)))
        zend = zhold + 0.12
        center = (W / 2, H / 2)

        def boss_focus(z):          # o chefe fica um pouco acima do meio (sobra espaço para o nome)
            return (bs[0], bs[1] + 0.08 * H / z)

        if t < 0.8:
            f, z = hs, 1.7
        elif t < 3.0:
            k = sm((t - 0.8) / 2.2)
            z = lerp(1.7, 1.3, k)
            bf = boss_focus(z)
            f = (lerp(hs[0], bf[0], k), lerp(hs[1], bf[1], k))
        elif t < 4.2:
            z = lerp(1.3, zhold, sm((t - 3.0) / 1.2))
            f = boss_focus(z)
        elif t < 6.2:
            z = lerp(zhold, zend, (t - 4.2) / 2.0)
            f = boss_focus(z)
        else:
            k = sm((t - 6.2) / 1.0)
            fh = boss_focus(zend)
            z = lerp(zend, 1.0, k)
            f = (lerp(fh[0], center[0], k), lerp(fh[1], center[1], k))
        if self.bi_roared and t >= 3.3:
            z += 0.18 * math.exp(-(t - 3.3) * 7.0)       # soco de zoom no rugido

        cw, chh = max(1, int(W / z)), max(1, int(H / z))
        rect = pygame.Rect(int(f[0] - cw / 2), int(f[1] - chh / 2), cw, chh)
        rect.clamp_ip(scr.get_rect())
        if z > 1.001 and rect.w < W:
            scr.blit(pygame.transform.smoothscale(scr.subsurface(rect), (W, H)), (0, 0))
        zx, zy = (W / rect.w), (H / rect.h)
        bpx, bpy = (bs[0] - rect.x) * zx, (bs[1] - rect.y) * zy

        scr.blit(self.vig, (0, 0))
        if 3.0 <= t < 6.6:
            scr.blit(self.vig, (0, 0))
        # brasas subindo
        if t > 2.4:
            for i in range(40):
                x = (i * 83 + math.sin(self.t * 0.9 + i) * 40) % W
                y = H - ((self.t * (40 + i % 6 * 14) + i * 61) % (H + 20))
                kk = 0.5 + 0.5 * math.sin(self.t * 5 + i)
                pygame.draw.circle(scr, (255, int(120 + 90 * kk), 60), (int(x), int(y)), 1 + i % 3 // 2)
        # tom vermelho + onda de choque do rugido
        ov = self.__dict__.get("_bi_ov")
        if ov is None:
            ov = self._bi_ov = pygame.Surface((W, H), pygame.SRCALPHA)
        tint = sm((t - 3.0) / 0.8) * (1 - sm((t - 6.2) / 0.8))
        ring = self.bi_roared and 3.3 <= t < 4.3
        if tint > 0.01 or ring:
            ov.fill((140, 10, 20, int(26 * tint)))
            if ring:
                u = (t - 3.3) / 1.0
                pygame.draw.circle(ov, (255, 96, 72, int(200 * (1 - u))), (int(bpx), int(bpy)), int(40 + u * 520), max(2, int(10 * (1 - u))))
            scr.blit(ov, (0, 0))
        # nome do chefe
        if 3.5 <= t < 6.9:
            a_in = sm((t - 3.5) / 0.55)
            a_out = 1 - sm((t - 6.2) / 0.6)
            a = a_in * a_out
            card = self.boss_card(e["kind"])
            sc = 1.12 - 0.12 * a_in
            im = card if abs(sc - 1) < 0.01 else pygame.transform.smoothscale(card, (int(card.get_width() * sc), int(card.get_height() * sc)))
            im.set_alpha(int(255 * a))
            scr.blit(im, im.get_rect(center=(W // 2, 448 + int(14 * (1 - a_in)))))
            self.atext(f"—  CHEFE DO ANDAR {self.floor}  —", 26, (255, 130, 110), (W // 2, 388), int(255 * a))
            lw = int(520 * sm((t - 3.7) / 0.6) * a_out)
            if lw > 4:
                pygame.draw.line(scr, (255, 70, 60), (W // 2 - lw // 2, 506), (W // 2 + lw // 2, 506), 4)
                pygame.draw.polygon(scr, (255, 214, 120), [(W // 2, 498), (W // 2 + 8, 506), (W // 2, 514), (W // 2 - 8, 506)])
            ep = self.BOSS_EPITHETS.get(e["kind"], "")
            self.atext(ep, 34, (255, 226, 160), (W // 2, 534), int(255 * sm((t - 4.1) / 0.5) * a_out))
        # barras de cinema
        kb = sm(t / 0.8) * (1 - sm((t - (D - 0.9)) / 0.9))
        bh = int(0.13 * H * kb)
        if bh > 0:
            scr.fill((0, 0, 0), (0, 0, W, bh))
            scr.fill((0, 0, 0), (0, H - bh, W, bh))
            if kb > 0.9:
                pygame.draw.line(scr, (120, 20, 30), (0, bh), (W, bh), 2)
                pygame.draw.line(scr, (120, 20, 30), (0, H - bh), (W, H - bh), 2)
                self.text("ENTER  pular", 20, (190, 190, 206), (W - 86, H - bh // 2), shadow=False)
        # entrada em fade a partir do preto + clarão do rugido
        if t < 0.8:
            ov.fill((0, 0, 0, int(255 * (1 - sm(t / 0.8)))))
            scr.blit(ov, (0, 0))
        if self.flash_t > 0:
            ov.fill((255, 255, 255, min(200, int(500 * self.flash_t))))
            scr.blit(ov, (0, 0))

    def flame_tongue(self, surf, cx, by, h, w, sway, col):
        left, right = [], []
        n = 12
        for i in range(n + 1):
            u = i / n
            hw = w * (math.sin(math.pi * min(1.0, u * 0.92 + 0.04)) ** 0.9) * ((1 - u) ** 0.35)
            x, y = cx + sway * u * u, by - h * u
            left.append((x - hw, y))
            right.append((x + hw, y))
        pygame.draw.polygon(surf, col, left + right[::-1])

    FLAMES = ((-40, 112, 26, 0.0), (-18, 152, 32, 1.3), (0, 188, 38, 2.1), (20, 146, 32, 3.4),
              (42, 106, 26, 4.2), (-8, 122, 22, 5.0), (10, 96, 20, 5.9))

    def draw_fire(self, cx, by, k=1.0):
        """Chamas animadas (camadas: brasa -> laranja -> amarelo -> núcleo) com base em (cx, by), escala k."""
        t = self.t
        fs = pygame.Surface((int(300 * k), int(260 * k)), pygame.SRCALPHA)
        layers = (((190, 46, 8, 175), 1.0, 1.0), ((246, 112, 22, 220), 0.78, 0.84),
                  ((255, 196, 76, 240), 0.52, 0.64), ((255, 244, 200, 255), 0.26, 0.38))
        for col, wk, hk in layers:
            for dx, h, w, ph in self.FLAMES:
                hh = h * (0.84 + 0.15 * math.sin(t * 9 + ph) + 0.08 * math.sin(t * 17 + ph * 2))
                self.flame_tongue(fs, (150 + dx * 0.9) * k, 240 * k, hh * hk * k, w * wk * k, 15 * k * math.sin(t * 5 + ph), col)
        self.screen.blit(fs, (cx - 150 * k, by - 4 * k - 240 * k))

    def draw_bonfire_bg(self):
        scr, t = self.screen, self.t
        gx, gy = self.fire_x, self.fire_y
        scr.blit(self.title_sky, (0, 0))
        fl = 0.5 + 0.25 * math.sin(t * 11) + 0.15 * math.sin(t * 23 + 1.3) + 0.10 * math.sin(t * 7.7 + 2)
        g = self.fire_glows[max(0, min(2, int(fl * 3)))]
        scr.blit(g, (gx - g.get_width() // 2, gy - 70 - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
        scr.blit(self.title_land, (0, 0))
        scr.blit(self.menu_dim, (0, 0))          # escurece tudo; só o fogo ilumina
        scr.blit(self.fire_floor, (gx - 230, gy - 26), special_flags=pygame.BLEND_RGB_ADD)
        off = int(t * 14) % (W * 2)                                     # névoa rolando devagar
        scr.blit(self.fire_fog, (-off, 410))
        scr.blit(self.fire_fog, (W * 2 - off, 410))
        self.draw_fire(gx, gy, 1.0)
        scr.blit(self.fire_core, (gx - 110, gy - 120 - 110), special_flags=pygame.BLEND_RGB_ADD)
        scr.blit(self.bonfire_sword, (gx - 45, gy - 108))
        for i in range(40):                                             # brasas subindo
            ph = (t * (0.10 + (i * 37 % 50) / 400.0) + i * 0.137) % 1.0
            rise = ph * (250 + (i % 7) * 44)
            x = gx + math.sin(t * (0.8 + i % 5 * 0.2) + i) * (16 + rise * 0.26) + (i % 9 - 4) * 6
            y = gy - 20 - rise
            a = 1.0 - ph
            if a > 0.05:
                pygame.draw.circle(scr, (int(255 * a ** 0.4), int((120 + 100 * a) * a), int((30 + 60 * a * a) * a)),
                                   (int(x), int(y)), 1 + (i % 3 == 0))
        for i in range(12):                                             # cinzas flutuando pelo ar
            x = (i * 131 + t * (5 + i % 4 * 3) + math.sin(t * 0.5 + i) * 20) % W
            y = (i * 71 + t * (6 + i % 5 * 2)) % H
            v = 46 + 30 * (0.5 + 0.5 * math.sin(t * 1.3 + i))
            scr.fill((int(v), int(v * 0.9), int(v * 0.8)), (int(x), int(y), 2, 2))
        scr.blit(self.vig, (0, 0))
        scr.blit(self.vig, (0, 0))
        scr.blit(self.vig, (0, 0))

    def draw_title(self):
        if not hasattr(self, "title_sky"):
            self.build_title_art()
        scr, t = self.screen, self.t
        self.draw_bonfire_bg()

        # título (logo pré-montado: nome + espada atravessando as letras)
        bob = math.sin(t * 1.6) * 4
        scr.blit(self.title_logo, (0, int(bob)))
        self.draw_sword_glints(bob)


        if self.phase == "slots":
            self.draw_slots()
        elif self.phase == "create":
            self.draw_create()
        elif self.phase == "mp_menu":
            self.draw_mpmenu()
        elif self.phase == "username":
            self.draw_username()
        else:
            self.draw_title_menu()

    def draw_hero_sit(self, hid, cx, cy, s, key=None, race=None):
        parts = sit_parts(parts_player(self.t, False, hid, (0.7071, 0.7071), 0.0, race))
        draw_parts_iso(self.screen, parts, cx, cy, s, soft=True, key=key or hid)

    def draw_hero_iso(self, hid, cx, cy, s, active, key=None, race=None):
        parts = parts_player(self.t, active, hid, (0.7071, 0.7071), 0.0, race)
        draw_parts_iso(self.screen, parts, cx, cy, s, soft=True, key=key or hid)

    def draw_transition(self):
        if self.transition is None:
            return
        t = min(1.0, self.transition["time"] / self.transition["duration"])
        cover = pygame.Surface((W, H), pygame.SRCALPHA)
        color = (10, 12, 18) if self.transition["kind"] == "dark" else (150, 18, 18)
        for i in range(16):
            radius = 100 + i * 54 + t * 380
            cx = W // 2 + (i % 3 - 1) * 110
            cy = H + i * 18 - (t * (H + 140))
            alpha = 130 + int(t * 100)
            pygame.draw.circle(cover, (color[0], color[1], color[2], alpha), (cx, int(cy)), int(radius))
        self.screen.blit(cover, (0, 0))

    def draw(self):
        self.draw_main()
        if self.smith_open:
            self.draw_smith()
        if self.mk_open:
            self.draw_market()
        if self.inv_open:
            self.draw_inventory()
        if self.settings_open:
            self.draw_settings()

    def draw_main(self):
        if self.phase in MENU_PHASES:
            self.draw_title()
            self.draw_transition()
            return
        if self.phase == "mp":
            self.view_rect = None
            self.draw_scene()
            self.draw_mp_overlay()
            self.draw_smith_hint()
            self.draw_market_hint()
            self.draw_menu_button()
            return
        self.draw_scene()
        ph = self.phase
        self.view_rect = None
        if ph != "bossintro":
            self.apply_fight_cam()
        if ph == "bossintro":
            self.draw_boss_intro()
            self.draw_transition()
            return
        self.draw_hud()
        self.draw_smith_hint()
        self.draw_market_hint()
        self.draw_panel()
        if ph == "fight":
            self.draw_fight_overlay()
        if ph == "descend":
            a = int(255 * min(1, max(0, (self.dt_ - 0.4) / 0.6)))
            ov = pygame.Surface((W, H))
            ov.fill((0, 0, 0))
            ov.set_alpha(a)
            self.screen.blit(ov, (0, 0))
        if ph == "gameover":
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((20, 0, 0, 190))
            self.screen.blit(ov, (0, 0))
            box = pygame.Rect(0, 0, 560, 360)
            box.center = (W // 2, H // 2)
            pulse = 0.5 + 0.5 * math.sin(self.t * 4)
            self.rrect(box.inflate(16, 16), (200, 40, 40, 50), 34)
            self.rrect(box, (18, 10, 24, 245), 28, 4, (220, 70, 70, 255))
            self.text("GAME OVER", 96, (255, 110, 110), (W // 2, box.y + 70))
            if self.slot is not None and self.saves[self.slot]:
                self.text(f"{self.saves[self.slot]['name']}  •  {self.hero['name']}", 22, (200, 190, 215), (W // 2, box.y + 18), shadow=False)
            pygame.draw.line(self.screen, (120, 50, 60), (box.x + 60, box.y + 128), (box.right - 60, box.y + 128), 2)
            self.text("PONTUAÇÃO", 22, (190, 180, 200), (W // 2, box.y + 156), shadow=False)
            self.text(str(self.score), 64, (255, 224, 120), (W // 2, box.y + 195))
            self.text(f"Andar alcançado: {self.floor}   •   Melhor andar: {self.best}", 26, (240, 240, 255), (W // 2, box.y + 250))
            if self.floor >= self.best and self.floor > 1:
                self.text("NOVO RECORDE!", 30, mix((255, 214, 90), pulse * 0.5), (W // 2, box.y + 285))
            self.text("ENTER  para voltar ao menu", 28, mix((200, 205, 235), pulse * 0.6), (W // 2, box.bottom - 30))
        if getattr(self, "flash_t", 0) > 0:
            fo = pygame.Surface((W, H), pygame.SRCALPHA)
            fo.fill((255, 255, 255, int(110 * self.flash_t / 0.22)))
            self.screen.blit(fo, (0, 0))
        self.draw_menu_button()
        self.draw_badges()
        self.draw_transition()

    # ------------------------------------------------------------- entrada
    def handle_key(self, key, uni=""):
        if self.settings_open:
            self.settings_key(key)
            return
        if self.smith_open:
            self.smith_key(key)
            return
        if self.mk_open:
            self.mk_key(key)
            return
        if self.inv_open:
            self.inv_key(key)
            return
        if key == pygame.K_F11:
            self.toggle_fs()
            return
        ph = self.phase
        if ph == "mp_menu":
            self.mpmenu_key(key, uni)
            return
        if ph == "username":
            self.username_key(key, uni)
            return
        if ph == "mp" and self.mp_key(key, uni):
            return
        if ph == "create":          # digitando o nome: as teclas de atalho viram texto
            self.create_key(key, uni)
            return
        if key == pygame.K_i and ph not in MENU_PHASES:
            self.open_inv()
            return
        if key == pygame.K_ESCAPE:
            if ph == "slots":
                if self.confirm:
                    self.confirm = None
                else:
                    self.phase = "title"
                return
            pygame.quit()
            sys.exit()
        go = key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
        if key == pygame.K_n:
            self.toggle_music()
            return
        if key == pygame.K_c:
            self.open_settings()
            return
        if key == pygame.K_t:
            self.cycle_mode()
            return
        if key == pygame.K_m and ph not in MENU_PHASES:
            self.back_to_menu()
            return
        if ph == "title":
            self.title_key(key, go)
        elif ph == "slots":
            self.slots_key(key, go)
        elif ph == "stairs":
            if key in (pygame.K_e, pygame.K_f, pygame.K_RETURN, pygame.K_KP_ENTER) and self.smith_near():
                self.open_smith()
            elif key in (pygame.K_e, pygame.K_f, pygame.K_RETURN, pygame.K_KP_ENTER) and self.market_near():
                self.open_market()
        elif ph == "bossintro":
            if go:      # pula a cutscene (vai direto para a parte em que a câmera volta ao normal)
                self.bi_t = max(self.bi_t, self.BI_DUR - 0.7)
        elif ph == "fight":
            if key in (pygame.K_j, pygame.K_z, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.fight_attack()
            elif key in (pygame.K_l, pygame.K_e):
                self.fight_heavy()
            elif key in (pygame.K_k, pygame.K_x, pygame.K_SPACE):
                self.fight_roll()
            elif key == pygame.K_TAB:
                self.pick_lock(cycle=True)
            elif key == pygame.K_q:
                self.fight_skill(0)
            elif key == pygame.K_r:
                self.fight_skill(1)
        elif ph == "gameover" and go:
            self.save_progress()
            self.transition = None
            self.phase = "title"
            self.banner, self.banner_t = "", 0.0
            self.particles.clear()
            self.floaters.clear()

    def run(self):
        while True:
            try:
                dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
                self.ui_t += dt
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit()
                    if ev.type == pygame.KEYDOWN:
                        self.handle_key(ev.key, ev.unicode)
                    elif ev.type == pygame.MOUSEMOTION and self.phase in MENU_PHASES and not self.settings_open:
                        self.menu_hover(ev.pos)
                    elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                        self.handle_click(ev.pos)
                    elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3 and not self.settings_open and not self.smith_open and not self.mk_open and not self.inv_open and self.phase not in MENU_PHASES:
                        self.fight_roll()
                self.music_tick()
                try:
                    if self.phase not in MENU_PHASES:
                        ov_ = self.settings_open or self.smith_open or self.mk_open or self.inv_open
                        if self.phase == "mp":                      # multiplayer: o mundo não pausa (a rede continua)
                            self.mp_tick(dt, ov_)
                        elif not ov_:                               # configurações, loja e inventário pausam a partida
                            self.update(dt)
                    else:
                        self.t += dt
                        if self.phase == "mp_menu":
                            self.mpmenu_tick(dt)
                except Exception:
                    # erro na lógica: mostra no console e segue sem sair da partida
                    traceback.print_exc()
                    self.errs = getattr(self, "errs", 0) + 1
                    if self.errs > 30:
                        self.errs = 0
                        self.phase = "title"
                        self.new_run(title=True)
                try:
                    self.draw()
                except Exception:
                    # erro só de desenho: pula o frame, o estado do jogo não muda
                    if not getattr(self, "draw_err", False):
                        traceback.print_exc()
                        self.draw_err = True
                pygame.display.flip()
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    if "--server" in sys.argv or "--public" in sys.argv:
        run_dedicated_server(sys.argv)
        sys.exit(0)
    g = Game()
    if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit():
        g.forced_seed = int(sys.argv[1])
        g.new_run(title=True)
    g.run()
