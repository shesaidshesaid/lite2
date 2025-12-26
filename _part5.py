#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from string import Template
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import _part1 as P1
from _part4 import (
    coletar_wind_com_fallback,
    avaliar_de_json,
)

# garante existência (se você não quiser mexer no _part1.py)
if not hasattr(P1, "WIND_PREF"):
    P1.WIND_PREF = None


# =========================================================
# Alarm State
# =========================================================
class AlarmState:
    def __init__(self):
        self.historico_niveis = []
        self.nivel_anterior = 0
        self.ultimo_alarme_l2 = 0.0
        self.ultimo_alarme_l3 = 0.0
        self.ultimo_alarme_l4 = 0.0
        self.ultimo_l3_inibe_l2 = 0.0
        self.ultimo_l4_inibe_l23 = 0.0
        self.mudancas_recentes = []
        self.auto_mute_until = 0.0
        self.ciclos_estaveis = 0
        self.ultimo_random = 0.0

    def nivel_combinado(self, est):
        return max(est.get("pitch_nivel", 0), est.get("roll_nivel", 0))

    def detectar_direcao(self, nivel_atual):
        if nivel_atual > self.nivel_anterior:
            return "SUBINDO"
        elif nivel_atual < self.nivel_anterior:
            return "DESCENDO"
        else:
            return "ESTAVEL"

    def eh_alarme_imediato(self, nivel_atual):
        direcao = self.detectar_direcao(nivel_atual)
        return bool(direcao == "SUBINDO" and nivel_atual >= 2)

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
        elif nivel == 3:
            return (agora - self.ultimo_l4_inibe_l23) < (P1.INIBICAO_L4_SOBRE_L23_MIN * 60)

        return False

    def verificar_auto_mute(self):
        return time.monotonic() < self.auto_mute_until

    def detectar_oscilacao(self, nivel_atual):
        agora = time.monotonic()

        if nivel_atual != self.nivel_anterior:
            self.mudancas_recentes.append((agora, nivel_atual))

        janela_s = P1.OSCILACAO_JANELA_MIN * 60
        self.mudancas_recentes = [(t, n) for t, n in self.mudancas_recentes if (agora - t) <= janela_s]

        if len(self.mudancas_recentes) >= P1.OSCILACAO_MAX_MUDANCAS:
            self.auto_mute_until = agora + (P1.AUTO_MUTE_OSCILACAO_MIN * 60)
            self.mudancas_recentes.clear()
            return True

        return False

    def atualizar_historico(self, nivel_atual):
        agora = time.monotonic()
        self.historico_niveis.append((agora, nivel_atual))

        if len(self.historico_niveis) > 10:
            self.historico_niveis = self.historico_niveis[-10:]

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

        eh_imediato = self.eh_alarme_imediato(nivel_atual)
        motivo = f"IMEDIATO (escalada {self.nivel_anterior}→{nivel_atual})" if eh_imediato else f"Normal L{nivel_atual}"

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
# Merge + refresh_token + refresh html now
# =========================================================
def _merge_dados(d_pr, d_wind):
    if not d_pr and not d_wind:
        return None

    dados = {}
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


def _gravar_refresh_token():
    try:
        tok = str(int(time.time() * 1000))
        with open(P1.FILES["refresh_js"], "w", encoding="utf-8") as f:
            f.write(f"window.__REFRESH_TOKEN__='{tok}';")
        return tok
    except Exception:
        return None


def _refresh_html_now():
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = coletar_wind_com_fallback(tentativas=1, timeout=5)

        if not d_pr and not d_wind:
            _gravar_refresh_token()
            return False

        dados = _merge_dados(d_pr, d_wind)
        est = avaliar_de_json(dados)

        gerar_html(
            est["pitch_val"], est["roll_val"], est["pitch_cor"], est["roll_cor"],
            est["rot"], est["raj"], est["raj_cor"], est["status_cor"],
            est.get("wdir_adj"), est.get("barometro"), est.get("wdir_lbl"),
            vento_med=est.get("vento_med"), vento_cor=est.get("vento_cor", "verde"),
        )

        _gravar_refresh_token()
        return True
    except Exception:
        _gravar_refresh_token()
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
                self._reply_json({"muted": is_muted_L23(), "muted_until": MUTE_L23_UNTIL_TS})

            elif path == "/wind_pref":
                hv = qs.get("host", [None])[0]
                if hv is None:
                    self._reply_json({"ok": True, "host": (P1.WIND_PREF or "auto")})
                    return

                v = (hv or "").strip().lower()
                host_set = set(P1.WIND_HOSTS_ORDER)

                if v in ("", "auto", "none", "null"):
                    P1.WIND_PREF = None
                    ok = _refresh_html_now()
                    self._reply_json({"ok": ok, "host": "auto"})
                elif v in host_set:
                    P1.WIND_PREF = v
                    ok = _refresh_html_now()
                    self._reply_json({"ok": ok, "host": v})
                else:
                    self._reply_json({"ok": False, "error": "host inválido"}, code=400)

            elif path == "/wind_pref_status":
                self._reply_json({"ok": True, "pref": (P1.WIND_PREF or "auto"), "options": P1.WIND_HOSTS_ORDER})

            else:
                self._reply_json({"error": "not found"}, code=404)

        except Exception as e:
            self._reply_json({"ok": False, "error": str(e)}, code=500)


def start_control_server(port: int = None):
    try:
        p = int(P1.MUTE_CTRL_PORT if port is None else port)
        srv = ThreadingHTTPServer(("127.0.0.1", p), _ControlHandler)
    except Exception:
        return None

    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    return srv


# =========================================================
# HTML rendering (preferencialmente via pitch_roll_template.html em $...)
# =========================================================
def _fmt_num(val, spec):
    try:
        if val is None:
            return "---"
        v = float(val)
        if not (v == v):  # NaN
            return "---"
        return format(v, spec)
    except Exception:
        return "---"


def _template_path():
    # compatível com as 2 chaves:
    # - P1.FILES["tpl"] (padrão do que eu te entreguei)
    # - P1.FILES["html_template"] (se você preferir)
    p = None
    try:
        p = P1.FILES.get("tpl") or P1.FILES.get("html_template")
    except Exception:
        p = None
    return Path(p) if p else None


def _wind_source_tail():
    src = None
    try:
        log_path = os.path.join(P1.BASE_DIR, "monitor.log")
        with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
            tail = lf.readlines()[-800:]
        for li in reversed(tail):
            m = P1.REGEX["wind_src"].search(li)
            if m:
                src = m.group(1)
                break
    except Exception:
        src = None
    return src


def gerar_html(
    p, r, pc, rc, rot, raj, rcor, status,
    wdir_aj, barometro, wdir_lbl,
    vento_med=None, vento_cor="verde",
):
    dt = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    src = _wind_source_tail()
    dt_show = dt if not src else f"""{dt} <span style="font-size:.85em;opacity:.75">(vento: {src})</span>"""

    pitch_txt = _fmt_num(p, ".1f")
    roll_txt = _fmt_num(r, ".1f")
    raj_txt = _fmt_num(raj, ".2f")
    vento_txt = _fmt_num(vento_med, ".1f")

    wdir_txt = _fmt_num(wdir_aj, ".1f")
    baro_txt = _fmt_num(barometro, ".2f")
    lbl_txt = "---" if (wdir_lbl is None or str(wdir_lbl).strip() == "") else str(wdir_lbl)

    last_epoch_ms = int(time.time() * 1000)

    tpl_path = _template_path()
    tpl_text = None
    if tpl_path and tpl_path.exists():
        try:
            tpl_text = tpl_path.read_text(encoding="utf-8")
        except Exception:
            tpl_text = None

    if not tpl_text:
        # fallback mínimo (não “gigante”), só para não quebrar caso o template suma
        tpl_text = """<!doctype html><html><head><meta charset="utf-8">
<title>Pitch&Roll</title></head><body>
<h1>$rot</h1>
<p>Pitch: $pitch_txt | Roll: $roll_txt</p>
<p>Vento: $vento_med_txt nós | Rajada: $rajada_txt nós</p>
<p>Atualizado: $hora</p>
</body></html>"""

    html = Template(tpl_text).safe_substitute(
        refresh_ms=str(int(P1.HTML_REFRESH_SEC * 1000)),
        stale_sec=str(int(P1.HTML_STALE_MAX_AGE_SEC)),
        last_epoch_ms=str(int(last_epoch_ms)),
        port=str(int(P1.MUTE_CTRL_PORT)),

        hora=str(dt_show),
        status_cor=str(status),
        rot=str(rot),

        pitch_cor=str(pc),
        roll_cor=str(rc),
        pitch_txt=str(pitch_txt),
        roll_txt=str(roll_txt),

        rajada_txt=str(raj_txt),
        rajada_cor=str(rcor),

        vento_med_txt=str(vento_txt),
        vento_cor=str(vento_cor),

        wdir_aj=str(wdir_txt),
        wdir_lbl=str(lbl_txt),
        barometro=str(baro_txt),
    )

    Path(P1.FILES["html"]).write_text(html, encoding="utf-8")


def abrir_html_no_navegador():
    try:
        uri = Path(P1.FILES["html"]).resolve().as_uri()
        webbrowser.open(uri, new=0, autoraise=True)
    except Exception:
        pass
