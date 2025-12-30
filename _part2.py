#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Aquisição de dados e matemática básica (pitch/roll/vento)."""

from __future__ import annotations

import math
from heapq import nlargest
from typing import Iterable, List, Optional

import _part1 as P1

_LAST_WIND_HOST = None


# =========================================================
# Helpers
# =========================================================

def _only_finite(seq: Optional[Iterable]) -> List[float]:
    result: List[float] = []
    for x in seq or []:
        v = P1.safe_float(x)
        if v is not None:
            result.append(v)
    return result


# =========================================================
# Pitch/Roll math
# =========================================================

def _soma_max_min_param(arr, n, aa, fator):
    arr = _only_finite(arr)
    if not arr:
        return 0.0
    janela = arr[-n:] if n and n > 0 else arr
    return (max(janela) + min(janela) + aa) * fator if janela else 0.0


def soma_max_min_pitch(arr, n=None):
    return _soma_max_min_param(arr, P1.HTML_WIN_PITCH if n is None else n, P1.AA_PITCH, P1.FATOR_CORRECAO_PITCH)


def soma_max_min_roll(arr, n=None):
    return _soma_max_min_param(arr, P1.HTML_WIN_ROLL if n is None else n, P1.AA_ROLL, P1.FATOR_CORRECAO_ROLL)


# =========================================================
# Vento (cálculos)  <-- AGORA USANDO OS CAMPOS DA UI (PyHMS)
# =========================================================

def rajada(d):
    """
    Rajada máxima (gust max) como a UI do PyHMS apresenta.

    Prioridade:
      1) gustspdmaxv (quando o backend preenche)
      2) gustspdmax["instantaneo op."]
      3) cálculo antigo via windwnd (fallback final)
    """
    # 1) valor "v" (quando existir)
    v = P1.safe_float(d.get("gustspdmaxv"))
    if v is not None:
        return v

    # 2) valor principal do dicionário completo
    g = d.get("gustspdmax")
    if isinstance(g, dict):
        if g.get("instantaneo op.") is not None:
            v2 = P1.safe_float(g.get("instantaneo op."))
            if v2 is not None:
                return v2

    # 3) fallback antigo (se nada vier do PyHMS)
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return 0.0
    tail = w[-max(P1.JANELA_WIND_SEC, P1.TOP_N_WIND) :]
    top = nlargest(min(P1.TOP_N_WIND, len(tail)), tail)
    return (sum(top) / len(top)) if top else 0.0


def vento_medio(d):
    """
    Vento médio 2 min como a UI do PyHMS apresenta.

    Prioridade:
      1) windspdmean["med. 2 min"]
      2) windspdmeanv (valor já escolhido no sistema)
      3) cálculo antigo via windwnd (fallback)
    """
    m = d.get("windspdmean")
    if isinstance(m, dict) and m.get("med. 2 min") is not None:
        v = P1.safe_float(m.get("med. 2 min"))
        if v is not None:
            return v

    v2 = P1.safe_float(d.get("windspdmeanv"))
    if v2 is not None:
        return v2

    # fallback antigo
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return None
    tail = w[-120:] if len(w) >= 120 else w
    return (sum(tail) / len(tail)) if tail else None


def vento_medio_ui_aux(d):
    """
    Mantive o nome pra não quebrar o projeto.
    Agora, este AUX também aponta para a leitura correta do PyHMS.
    """
    return vento_medio(d)


def rajada_ui_aux(d):
    """
    Mantive o nome pra não quebrar o projeto.
    Agora, este AUX também aponta para a leitura correta do PyHMS.
    """
    return rajada(d)


# =========================================================
# Wind coletor com fallback (depende de P1.coletar_json)
# =========================================================

def coletar_wind_com_fallback(tentativas: int = 1, timeout: int = 10):
    global _LAST_WIND_HOST
    wind_pref = getattr(P1, "WIND_PREF", None)
    ordem = P1.ordered_wind_hosts(wind_pref)

    algum_host_ok = False
    rejeicoes = []
    for host in ordem:
        url = f"http://{host}:8509{P1.GET_PATH}"
        d = P1.coletar_json(url, tentativas, timeout)
        if not d:
            P1.log.warning("Host %s (%s) sem dados de vento (falha HTTP/JSON).", host, url)
            continue
        try:
            vm, rj = vento_medio(d), rajada(d)
        except Exception:
            P1.log.exception("Erro interpretando vento de %s", host)
            continue

        if vm is None or rj is None:
            P1.log.debug("Rejeitando vento de %s: valores ausentes (vm=%s, raj=%s)", host, vm, rj)
            rejeicoes.append((host, "valores ausentes"))
            continue

        try:
            vm_num, rj_num = float(vm), float(rj)
        except Exception:
            P1.log.debug("Rejeitando vento de %s: valores não numéricos (vm=%s, raj=%s)", host, vm, rj)
            rejeicoes.append((host, "valores não numéricos"))
            continue

        if not (math.isfinite(vm_num) and math.isfinite(rj_num)):
            P1.log.debug("Rejeitando vento de %s: valores não finitos (vm=%s, raj=%s)", host, vm, rj)
            rejeicoes.append((host, "valores não finitos"))
            continue

        if vm_num <= 0 or rj_num <= 0:
            P1.log.debug("Rejeitando vento de %s: valores não positivos (vm=%s, raj=%s)", host, vm, rj)
            rejeicoes.append((host, "valores não positivos"))
            continue

        algum_host_ok = True
        d["_wind_source"] = host
        P1.log.info("Usando vento de %s (vm=%s, raj=%s).", host, vm, rj)
        if host != _LAST_WIND_HOST:
            P1.log_event("WIND_HOST", host=host, vm=vm_num, raj=rj_num, prev=_LAST_WIND_HOST)
            _LAST_WIND_HOST = host
        return d

    if not algum_host_ok:
        if rejeicoes:
            resumo = ", ".join(f"{h} ({motivo})" for h, motivo in rejeicoes)
            P1.log.info("Hosts com dados de vento rejeitados: %s", resumo)
        P1.log.warning("Nenhum host de vento válido após tentar %s.", ", ".join(ordem))
        P1.log_event("WIND_FAIL", hosts=",".join(ordem), rejected=len(rejeicoes))
    return None


# =========================================================
# Direção / barômetro
# =========================================================
_ROSA16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def rosa_16_pontos(graus):
    if graus is None:
        return None
    q = graus / 22.5
    idx = int(math.floor(q + 0.5 + 1e-12)) % 16
    return _ROSA16[idx]


def _dir_vento_media(d):
    spl = d.get("windsplv") or "med. 2 min"
    wm = d.get("winddirmean")

    if isinstance(wm, dict) and wm.get(spl) is not None:
        try:
            return float(wm[spl])
        except Exception:
            pass

    if d.get("winddirmeanv") is not None:
        try:
            return float(d["winddirmeanv"])
        except Exception:
            pass
    return None


def dir_vento_ajustada(d):
    base = _dir_vento_media(d)
    return (float(base) - 23.0) % 360.0 if base is not None else None


def barometro_hpa(d):
    try:
        for key in ["airpresslmeanv", "airpresmeanv"]:
            if d.get(key) is not None:
                val = P1.safe_float(d[key])
                if val is not None:
                    return val

        spl = d.get("windsplv") or "med. 2 min"
        for key in ["airpresslmean", "airpresmean"]:
            val = d.get(key)
            if isinstance(val, dict) and val.get(spl) is not None:
                val2 = P1.safe_float(val[spl])
                if val2 is not None:
                    return val2
    except Exception:
        pass
    return None


__all__ = [
    "_only_finite",
    "soma_max_min_pitch",
    "soma_max_min_roll",
    "rajada",
    "vento_medio",
    "vento_medio_ui_aux",
    "rajada_ui_aux",
    "coletar_wind_com_fallback",
    "rosa_16_pontos",
    "dir_vento_ajustada",
    "barometro_hpa",
]
