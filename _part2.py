#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Aquisição de dados e matemática básica (pitch/roll/vento)."""

from __future__ import annotations

import math
from heapq import nlargest
from typing import Iterable, List, Optional

import _part1 as P1


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
# Vento (cálculos)
# =========================================================

def rajada(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return 0.0
    tail = w[-max(P1.JANELA_WIND_SEC, P1.TOP_N_WIND) :]
    top = nlargest(min(P1.TOP_N_WIND, len(tail)), tail)
    return (sum(top) / len(top)) if top else 0.0


def vento_medio(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return None
    tail = w[-120:] if len(w) >= 120 else w
    return (sum(tail) / len(tail)) if tail else None


def _valor_auxiliar(d, chave_imediata, chave_dict, fallback_fn):
    v = P1.safe_float(d.get(chave_imediata))
    if v is not None:
        return v
    try:
        spl = d.get("windsplv") or "med. 2 min"
        m = d.get(chave_dict)
        if isinstance(m, dict) and m.get(spl) is not None:
            v2 = P1.safe_float(m[spl])
            return v2 if v2 is not None else fallback_fn(d)
    except Exception:
        pass
    return fallback_fn(d)


def vento_medio_ui_aux(d):
    return _valor_auxiliar(d, "windspdauxmeanv", "windspdauxmean", vento_medio)


def rajada_ui_aux(d):
    return _valor_auxiliar(d, "windspdauxmaxv", "windspdauxmax", rajada)


# =========================================================
# Wind coletor com fallback (depende de P1.coletar_json)
# =========================================================

def coletar_wind_com_fallback(tentativas: int = 1, timeout: int = 10):
    wind_pref = getattr(P1, "WIND_PREF", None)
    ordem = (
        [wind_pref] + [h for h in P1.WIND_HOSTS_ORDER if h != wind_pref]
        if wind_pref and wind_pref in P1.WIND_HOSTS_ORDER
        else list(P1.WIND_HOSTS_ORDER)
    )

    for host in ordem:
        d = P1.coletar_json(f"http://{host}:8509{P1.GET_PATH}", tentativas, timeout)
        if not d:
            continue
        serie = _only_finite(d.get("windwnd", []))
        if not serie:
            continue
        try:
            vm, rj = vento_medio(d), rajada(d)
            if vm and rj and float(vm) > 0 and float(rj) > 0:
                d["_wind_source"] = host
                P1.log.info("Usando vento de %s (vm=%s, raj=%s).", host, vm, rj)
                return d
        except Exception:
            continue
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
