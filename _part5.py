#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Estado, servidor de controle e renderização de HTML."""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse

import _part1 as P1
import _part2 as P2
import _part4 as P4
from _html_fallback import HTML_TPL


# =========================================================
# Alarm State
# =========================================================
class AlarmState:
    def __init__(self):
        self.historico_niveis: Deque = deque(maxlen=10)
        self.nivel_anterior = 0
        self.ultimo_alarme_l2 = 0.0
        self.ultimo_alarme_l3 = 0.0
        self.ultimo_alarme_l4 = 0.0
        self.ultimo_l3_inibe_l2 = 0.0
        self.ultimo_l4_inibe_l23 = 0.0
        self.mudancas_recentes: Deque = deque()
        self.auto_mute_until = 0.0
        self.ciclos_estaveis = 0
        self.ultimo_random = 0.0

    def nivel_combinado(self, est):
        return max(est.get("pitch_nivel", 0), est.get("roll_nivel", 0))

    def detectar_direcao(self, nivel_atual):
        if nivel_atual > self.nivel_anterior:
            return "SUBINDO"
        if nivel_atual < self.nivel_anterior:
            return "DESCENDO"
        return "ESTAVEL"

    def eh_alarme_imediato(self, nivel_atual):
        return self.detectar_direcao(nivel_atual) == "SUBINDO" and nivel_atual >= 2

    def verificar_cooldown(self, nivel):
        agora = time.monotonic()
        if nivel <= 2:
            if (agora - self.ultimo_alarme_l2) < (P1.COOLDOWN_L2_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l3) < (P1.COOLDOWN_L3_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True
        if nivel <= 3:
            if (agora - self.ultimo_alarme_l3) < (P1.COOLDOWN_L3_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True
        if nivel <= 4:
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True
        return False

    def verificar_inibicao(self, nivel):
        agora = time.monotonic()
        if nivel == 2:
            inibido_l3 = (agora - self.ultimo_l3_inibe_l2) < (P1.INIBICAO_L3_SOBRE_L2_MIN * 60)
            inibido_l4 = (agora - self.ultimo_l4_inibe_l23) < (P1.INIBICAO_L4_SOBRE_L23_MIN * 60)
            return inibido_l3 or inibido_l4
        if nivel == 3:
            return (agora - self.ultimo_l4_inibe_l23) < (P1.INIBICAO_L4_SOBRE_L23_MIN * 60)
        return False

    def verificar_auto_mute(self):
        return time.monotonic() < self.auto_mute_until

    def detectar_oscilacao(self, nivel_atual):
        agora = time.monotonic()
        if nivel_atual != self.nivel_anterior:
            self.mudancas_recentes.append((agora, nivel_atual))
        janela_s = P1.OSCILACAO_JANELA_MIN * 60
        self.mudancas_recentes = deque([(t, n) for t, n in self.mudancas_recentes if (agora - t) <= janela_s], maxlen=25)
        if len(self.mudancas_recentes) >= P1.OSCILACAO_MAX_MUDANCAS:
            self.auto_mute_until = agora + (P1.AUTO_MUTE_OSCILACAO_MIN * 60)
            self.mudancas_recentes.clear()
            return True
        return False

    def atualizar_historico(self, nivel_atual):
        agora = time.monotonic()
        self.historico_niveis.append((agora, nivel_atual))
        if nivel_atual <= 1:
            self.ciclos_estaveis += 1
            if self.ciclos_estaveis >= P1.RESET_ESTAVEL_CICLOS:
                self._reset_estado()
        else:
            self.ciclos_estaveis = 0
        self.nivel_anterior = nivel_atual

    def _reset_estado(self):
        self.historico_niveis.clear()
        self.mudancas_recentes.clear()
        self.ciclos_estaveis = 0

    def registrar_alarme_tocado(self, nivel):
        agora = time.monotonic()
        if nivel == 2:
            self.ultimo_alarme_l2 = agora
        elif nivel == 3:
            self.ultimo_alarme_l3 = agora
            self.ultimo_l3_inibe_l2 = agora
        elif nivel == 4:
            self.ultimo_alarme_l4 = agora
            self.ultimo_l4_inibe_l23 = agora

    def deve_tocar_alarme(self, est):
        nivel_atual = self.nivel_combinado(est)
        if nivel_atual <= 1:
            self.atualizar_historico(nivel_atual)
            return False, None, "Nível baixo (L0/L1)"
        if self.verificar_auto_mute():
            self.atualizar_historico(nivel_atual)
            return False, None, "Auto-mute ativo (oscilação)"
        if self.detectar_oscilacao(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, "Auto-mute ativado (oscilação detectada)"
        if self.verificar_cooldown(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, f"Cooldown L{nivel_atual} ativo"
        if self.verificar_inibicao(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, f"L{nivel_atual} inibido por nível superior"
        motivo = "IMEDIATO (escalada %s→%s)" % (self.nivel_anterior, nivel_atual) if self.eh_alarme_imediato(nivel_atual) else f"Normal L{nivel_atual}"
        self.atualizar_historico(nivel_atual)
        return True, motivo, None


alarm_state = AlarmState()


# =========================================================
# Mute L2/L3 state + lock
# =========================================================
MUTE_L23_UNTIL_TS = 0.0
_mute_lock = threading.Lock()


def is_muted_L23() -> bool:
    with _mute_lock:
        return time.time() < MUTE_L23_UNTIL_TS


def _set_mute_L23_for_minutes(mins: float):
    global MUTE_L23_UNTIL_TS
    until = time.time() + max(0, float(mins)) * 60.0
    with _mute_lock:
        MUTE_L23_UNTIL_TS = until
    return until


def _clear_mute_L23():
    global MUTE_L23_UNTIL_TS
    with _mute_lock:
        MUTE_L23_UNTIL_TS = 0.0


# =========================================================
# Merge + refresh_token
# =========================================================

def merge_dados(d_pr: Optional[Dict], d_wind: Optional[Dict]):
    if not d_pr and not d_wind:
        return None
    dados: Dict = {}
    if d_pr:
        for k in P1.KEYS_PR:
            if k in d_pr:
                dados[k] = d_pr[k]
    if d_wind:
        for k in P1.KEYS_WIND:
            if k in d_wind:
                dados[k] = d_wind[k]
        if d_wind.get("_wind_source"):
            dados["_wind_source"] = d_wind["_wind_source"]
    return dados


def gravar_refresh_token():
    try:
        tok = str(int(time.time() * 1000))
        Path(P1.FILES["refresh_js"]).write_text(f"window.__REFRESH_TOKEN__='{tok}';", encoding="utf-8")
        return tok
    except Exception:
        return None


def refresh_html_now():
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = P2.coletar_wind_com_fallback(tentativas=1, timeout=5)
        if not d_pr and not d_wind:
            gravar_refresh_token()
            return False
        dados = merge_dados(d_pr, d_wind)
        est = P4.avaliar_de_json(dados)
        gerar_html(
            est["pitch_val"],
            est["roll_val"],
            est["pitch_cor"],
            est["roll_cor"],
            est["rot"],
            est["raj"],
            est["raj_cor"],
            est["status_cor"],
            est.get("wdir_adj"),
            est.get("barometro"),
            est.get("wdir_lbl"),
            est.get("vento_med"),
            est.get("vento_cor", "verde"),
            est.get("wind_source"),
        )
        gravar_refresh_token()
        return True
    except Exception:
        gravar_refresh_token()
        return False


# =========================================================
# Control server
# =========================================================
class _ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def address_string(self):
        return "127.0.0.1"

    def _reply_json(self, obj: dict, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query or "")
            if path == "/mute":
                mins = float(qs.get("mins", ["360"])[0])
                until = _set_mute_L23_for_minutes(mins)
                self._reply_json({"ok": True, "muted": True, "muted_until": until})
            elif path == "/unmute":
                _clear_mute_L23()
                self._reply_json({"ok": True, "muted": False})
            elif path == "/mute_status":
                self._reply_json({"ok": True, "muted": is_muted_L23(), "muted_until": MUTE_L23_UNTIL_TS})
            elif path == "/wind_pref":
                if qs.get("host"):
                    val = qs.get("host", ["auto"])[0]
                    if val == "auto":
                        P1.WIND_PREF = None
                    else:
                        P1.WIND_PREF = val
                self._reply_json({"ok": True, "host": P1.WIND_PREF})
            else:
                self._reply_json({"ok": False, "error": "unknown"}, 404)
        except Exception:
            self._reply_json({"ok": False, "error": "exception"}, 500)


def start_control_server(port: int = P1.MUTE_CTRL_PORT):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _ControlHandler)
    except Exception:
        return None
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    return srv


def _fmt_or_dash(val, fmt):
    try:
        return fmt.format(float(val))
    except Exception:
        return "---"


def gerar_html(
    p,
    r,
    pc,
    rc,
    rot,
    raj,
    rcor,
    status,
    wdir_aj,
    barometro,
    wdir_lbl,
    vento_med=None,
    vento_cor="verde",
    wind_source: Optional[str] = None,
):
    dt = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    dt_show = dt if not wind_source else f"{dt} <span style=\"font-size:.85em;opacity:.75\">(vento: {wind_source})</span>"

    wdir_txt = _fmt_or_dash(wdir_aj, "{:.1f}")
    baro_txt = _fmt_or_dash(barometro, "{:.2f}")
    lbl_txt = "---" if (wdir_lbl is None or str(wdir_lbl).strip() == "") else str(wdir_lbl)
    vento_txt = _fmt_or_dash(vento_med, "{:.1f}")
    last_epoch_ms = int(time.time() * 1000)

    template_path = Path(P1.FILES.get("html_template", ""))
    if template_path and template_path.exists():
        try:
            txt = template_path.read_text(encoding="utf-8")
            if "$refresh_ms" in txt or "$stale_sec" in txt or "$last_epoch_ms" in txt:
                tpl = Template(txt)
                html = tpl.substitute(
                    refresh_ms=P1.HTML_REFRESH_SEC * 1000,
                    stale_sec=P1.HTML_STALE_MAX_AGE_SEC,
                    last_epoch_ms=last_epoch_ms,
                    port=P1.MUTE_CTRL_PORT,
                    hora=dt_show,
                    status_cor=status,
                    rot=rot,
                    pitch=_fmt_or_dash(p, "{:.1f}"),
                    roll=_fmt_or_dash(r, "{:.1f}"),
                    pitch_cor=pc,
                    roll_cor=rc,
                    rajada=_fmt_or_dash(raj, "{:.2f}"),
                    rajada_cor=rcor,
                    vento_med_txt=vento_txt,
                    vento_cor=vento_cor,
                    wdir_aj=wdir_txt,
                    wdir_lbl=lbl_txt,
                    barometro=baro_txt,
                )
                Path(P1.FILES["html"]).write_text(html, encoding="utf-8")
                return
        except Exception:
            P1.log.warning("Template externo inválido; usando fallback interno.", exc_info=True)

    with open(P1.FILES["html"], "w", encoding="utf-8") as f:
        f.write(
            HTML_TPL.format(
                refresh_ms=P1.HTML_REFRESH_SEC * 1000,
                stale_sec=P1.HTML_STALE_MAX_AGE_SEC,
                last_epoch_ms=last_epoch_ms,
                rot=rot,
                pitch=p,
                roll=r,
                pitch_cor=pc,
                roll_cor=rc,
                rajada=raj,
                rajada_cor=rcor,
                vento_med_txt=vento_txt,
                vento_cor=vento_cor,
                status_cor=status,
                wdir_aj=wdir_txt,
                barometro=baro_txt,
                wdir_lbl=lbl_txt,
                hora=dt_show,
                port=P1.MUTE_CTRL_PORT,
            )
        )


def abrir_html_no_navegador():
    try:
        uri = Path(P1.FILES["html"]).resolve().as_uri()
        webbrowser.open(uri, new=0, autoraise=True)
    except Exception:
        pass


__all__ = [
    "AlarmState",
    "alarm_state",
    "is_muted_L23",
    "start_control_server",
    "merge_dados",
    "gravar_refresh_token",
    "refresh_html_now",
    "gerar_html",
    "abrir_html_no_navegador",
]
