#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
from heapq import nlargest

import _part1 as P1


# =========================================================
# Util: somente floats finitos
# =========================================================
def _only_finite(seq):
    result = []
    for x in (seq or []):
        try:
            v = float(x)
            if math.isfinite(v):
                result.append(v)
        except (TypeError, ValueError):
            continue
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
    return _soma_max_min_param(
        arr,
        P1.HTML_WIN_PITCH if n is None else n,
        P1.AA_PITCH,
        P1.FATOR_CORRECAO_PITCH,
    )


def soma_max_min_roll(arr, n=None):
    return _soma_max_min_param(
        arr,
        P1.HTML_WIN_ROLL if n is None else n,
        P1.AA_ROLL,
        P1.FATOR_CORRECAO_ROLL,
    )


# =========================================================
# Vento (cálculos)
# =========================================================
def rajada(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return 0.0
    tail = w[-max(P1.JANELA_WIND_SEC, P1.TOP_N_WIND):]
    top = nlargest(min(P1.TOP_N_WIND, len(tail)), tail)
    return (sum(top) / len(top)) if top else 0.0


def vento_medio(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return None
    tail = w[-120:] if len(w) >= 120 else w
    return (sum(tail) / len(tail)) if tail else None


def _valor_auxiliar(d, chave_imediata, chave_dict, fallback_fn):
    try:
        v = d.get(chave_imediata, None)
        if v is not None and math.isfinite(float(v)):
            return float(v)
    except Exception:
        pass

    try:
        spl = d.get("windsplv") or "med. 2 min"
        m = d.get(chave_dict)
        if isinstance(m, dict) and m.get(spl) is not None:
            v = float(m[spl])
            return v if math.isfinite(v) else fallback_fn(d)
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
def coletar_wind_com_fallback(tentativas=1, timeout=10):
    wind_pref = getattr(P1, "WIND_PREF", None)

    ordem = (
        ([wind_pref] + [h for h in P1.WIND_HOSTS_ORDER if h != wind_pref])
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
                return float(d[key])

        spl = d.get("windsplv") or "med. 2 min"
        for key in ["airpresslmean", "airpresmean"]:
            val = d.get(key)
            if isinstance(val, dict) and val.get(spl) is not None:
                return float(val[spl])
    except Exception:
        pass
    return None


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
    elif vv > 24.9:
        return "laranja"
    elif vv > 20.9:
        return "amarelo"
    else:
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
    pitch_val, roll_val,  # mantidos por compatibilidade (não usados)
    pitch_rot, pitch_cor, pitch_hint, pitch_nivel,
    roll_rot, roll_cor, roll_hint, roll_nivel,
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
                f'<span class="nivelada-preta">NIVELADA</span>'
                f'<span class="subrotulo">({"<br>".join(hints)})</span>'
            )
        else:
            rot = '<span class="verde">NIVELADA</span>'

    status_cor = pior_cor(pitch_cor, roll_cor)
    return rot, status_cor


def avaliar_por_valores(pitch_val, roll_val, raj_val):
    pitch_rot, pitch_cor, pitch_hint, pitch_nivel = classif2(
        pitch_val,
        P1.L4_LEVELS[1], P1.L3_LEVELS[1], P1.L2_LEVELS[1],
        P1.NIVELADA_NEG, P1.NIVELADA_POS,
        P1.L2_LEVELS[0], P1.L3_LEVELS[0], P1.L4_LEVELS[0],
        ("PROA", "POPA"),
    )

    roll_rot, roll_cor, roll_hint, roll_nivel = classif2(
        roll_val,
        P1.L4_LEVELS[3], P1.L3_LEVELS[3], P1.L2_LEVELS[3],
        P1.NIVELADA_NEG, P1.NIVELADA_POS,
        P1.L2_LEVELS[2], P1.L3_LEVELS[2], P1.L4_LEVELS[2],
        ("BORESTE", "BOMBORDO"),
    )

    rot, status_cor = _montar_rotulo_e_status(
        pitch_val, roll_val,
        pitch_rot, pitch_cor, pitch_hint, pitch_nivel,
        roll_rot, roll_cor, roll_hint, roll_nivel,
    )

    return {
        "pitch_val": pitch_val, "roll_val": roll_val,
        "pitch_rot": pitch_rot, "pitch_cor": pitch_cor, "pitch_hint": pitch_hint, "pitch_nivel": pitch_nivel,
        "roll_rot": roll_rot, "roll_cor": roll_cor, "roll_hint": roll_hint, "roll_nivel": roll_nivel,
        "rot": rot, "status_cor": status_cor,
        "raj": raj_val, "raj_cor": cor_raj(raj_val),
    }


def avaliar_de_json(dados: dict):
    pitch_val = soma_max_min_pitch(dados.get("ptchwnd", []), P1.HTML_WIN_PITCH)
    roll_val = soma_max_min_roll(dados.get("rollwnd", []), P1.HTML_WIN_ROLL)

    src = (dados.get("_wind_source") or "").lower()
    if src == "smp53ocn01":
        vento_val = vento_medio_ui_aux(dados)
        raj_val = rajada_ui_aux(dados)
    else:
        vento_val = vento_medio(dados)
        raj_val = rajada(dados)

    out = avaliar_por_valores(pitch_val, roll_val, raj_val)

    wdir_adj = dir_vento_ajustada(dados)
    out.update({
        "wdir_adj": wdir_adj,
        "wdir_lbl": rosa_16_pontos(wdir_adj) if wdir_adj is not None else None,
        "barometro": barometro_hpa(dados),
        "vento_med": vento_val,
        "vento_cor": cor_raj(vento_val),
    })
    return out
