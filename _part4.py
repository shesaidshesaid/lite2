#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Motor de avaliação de níveis e montagem de rótulos/cores."""

from __future__ import annotations

import _part1 as P1
import _part2 as P2


# =========================================================
# Classificação / cores
# =========================================================

def cor_raj(v):
    if v is None:
        return "verde"
    try:
        vv = float(v)
    except Exception:
        return "verde"

    if vv > 29.9:
        return "vermelho"
    if vv > 24.9:
        return "laranja"
    if vv > 20.9:
        return "amarelo"
    return "verde"


def classif2(v, n4, n3, n2, niv_n, niv_p, p2, p3, p4, nomes):
    if v >= p4:
        return nomes[0], "vermelho", None, 4
    if v >= p3:
        return nomes[0], "vermelho", None, 3
    if v >= p2:
        return nomes[0], "laranja", None, 2
    if v <= n4:
        return nomes[1], "vermelho", None, 4
    if v <= n3:
        return nomes[1], "vermelho", None, 3
    if v <= n2:
        return nomes[1], "laranja", None, 2
    if niv_n <= v <= niv_p:
        return "NIVELADA", "verde", None, 0
    return "NIVELADA_HINT", "verde", (nomes[0] if v > niv_p else nomes[1]), 1


def pior_cor(*cores):
    if "vermelho" in cores:
        return "vermelho"
    if "laranja" in cores:
        return "laranja"
    if "amarelo" in cores:
        return "amarelo"
    return "verde"


def _montar_rotulo_e_status(
    pitch_val,
    roll_val,
    pitch_rot,
    pitch_cor,
    pitch_hint,
    pitch_nivel,
    roll_rot,
    roll_cor,
    roll_hint,
    roll_nivel,
):
    ha_alarme = (pitch_nivel >= 2) or (roll_nivel >= 2)

    if ha_alarme:
        partes = []
        if pitch_nivel >= 2 and pitch_rot != "NIVELADA":
            partes.append(f'<span class="{pitch_cor}">{pitch_rot.replace(" ", "<br>")}</span>')
        if roll_nivel >= 2 and roll_rot != "NIVELADA":
            partes.append(f'<span class="{roll_cor}">{roll_rot.replace(" ", "<br>")}</span>')
        if pitch_nivel >= 2 and roll_nivel == 1 and roll_hint:
            partes.append(f'<span class="preto">{roll_hint.replace(" ", "<br>")}</span>')
        if roll_nivel >= 2 and pitch_nivel == 1 and pitch_hint:
            partes.append(f'<span class="preto">{pitch_hint.replace(" ", "<br>")}</span>')
        rot = "<br>".join(partes) if partes else '<span class="verde">NIVELADA</span>'
    else:
        hints = [h.replace(" ", "<br>") for h in [pitch_hint, roll_hint] if h]
        if hints:
            rot = (
                '<span class="nivelada-preta">NIVELADA</span>'
                f'<span class="subrotulo">({"<br>".join(hints)})</span>'
            )
        else:
            rot = '<span class="verde">NIVELADA</span>'

    status_cor = pior_cor(pitch_cor, roll_cor)
    return rot, status_cor


def avaliar_por_valores(pitch_val, roll_val, raj_val):
    pitch_rot, pitch_cor, pitch_hint, pitch_nivel = classif2(
        pitch_val,
        P1.L4_LEVELS[1],
        P1.L3_LEVELS[1],
        P1.L2_LEVELS[1],
        P1.NIVELADA_NEG,
        P1.NIVELADA_POS,
        P1.L2_LEVELS[0],
        P1.L3_LEVELS[0],
        P1.L4_LEVELS[0],
        ("PROA", "POPA"),
    )

    roll_rot, roll_cor, roll_hint, roll_nivel = classif2(
        roll_val,
        P1.L4_LEVELS[3],
        P1.L3_LEVELS[3],
        P1.L2_LEVELS[3],
        P1.NIVELADA_NEG,
        P1.NIVELADA_POS,
        P1.L2_LEVELS[2],
        P1.L3_LEVELS[2],
        P1.L4_LEVELS[2],
        ("BORESTE", "BOMBORDO"),
    )

    rot, status_cor = _montar_rotulo_e_status(
        pitch_val,
        roll_val,
        pitch_rot,
        pitch_cor,
        pitch_hint,
        pitch_nivel,
        roll_rot,
        roll_cor,
        roll_hint,
        roll_nivel,
    )

    return {
        "pitch_val": pitch_val,
        "roll_val": roll_val,
        "pitch_rot": pitch_rot,
        "pitch_cor": pitch_cor,
        "pitch_hint": pitch_hint,
        "pitch_nivel": pitch_nivel,
        "roll_rot": roll_rot,
        "roll_cor": roll_cor,
        "roll_hint": roll_hint,
        "roll_nivel": roll_nivel,
        "rot": rot,
        "status_cor": status_cor,
        "raj": raj_val,
        "raj_cor": cor_raj(raj_val),
    }


def avaliar_de_json(dados: dict):
    pitch_val = P2.soma_max_min_pitch(dados.get("ptchwnd", []), P1.HTML_WIN_PITCH)
    roll_val  = P2.soma_max_min_roll(dados.get("rollwnd", []), P1.HTML_WIN_ROLL)

    # =========================
    # VENTO – PyHMS (média 2 min REAL)
    # =========================
    vento_val = P2.vento_medio(dados)

    # =========================
    # RAJADA – PyHMS (gust max REAL)
    # =========================
    raj_val = P2.rajada(dados)

    out = avaliar_por_valores(pitch_val, roll_val, raj_val)

    wdir_adj = P2.dir_vento_ajustada(dados)

    out.update(
        {
            "wdir_adj": wdir_adj,
            "wdir_lbl": P2.rosa_16_pontos(wdir_adj) if wdir_adj is not None else None,
            "barometro": P2.barometro_hpa(dados),
            "vento_med": vento_val,
            "vento_cor": cor_raj(vento_val),
            "wind_source": dados.get("_wind_source"),
        }
    )
    return out



__all__ = [
    "cor_raj",
    "classif2",
    "pior_cor",
    "avaliar_por_valores",
    "avaliar_de_json",
]
