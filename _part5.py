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
from typing import Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse

import _part1 as P1
import _part2 as P2
import _part4 as P4
from _html_fallback import HTML_TPL


# =========================================================
# Alarm State (SIMPLIFICADO)
# =========================================================

ALARM_CONFIRM_SEC = 5.0
ALARM_SILENCE_SEC = 8 * 60.0  # 8 minutos


def _coletar_est_para_confirmacao():
    """Coleta uma leitura 'agora' para confirmar nível (sem depender do loop de 20s)."""
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = P2.coletar_wind_com_fallback(tentativas=1, timeout=5)

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

        return P4.avaliar_de_json(dados)
    except Exception:
        P1.log.exception("Falha ao confirmar leitura de alarme")
        return None


def _tocar_alarme_pitch_roll(nivel: int, est: dict) -> None:
    """Toca beep + voz conforme direções ativas (>=L2)."""
    cond = []
    if est.get("pitch_nivel", 0) >= 2 and est.get("pitch_rot") != "NIVELADA":
        cond.append(est["pitch_rot"])
    if est.get("roll_nivel", 0) >= 2 and est.get("roll_rot") != "NIVELADA":
        cond.append(est["roll_rot"])

    P1.tocar_alerta(nivel)
    P1.falar_wavs(cond, incluir_atencao=(nivel >= 3))
    # força refresh imediato no navegador (token)
    gravar_refresh_token()


class AlarmState:
    """
    Regras:
    - L0/L1: nunca toca
    - L2/L3/L4: só toca quando subir (nivel_atual > nivel_anterior)
    - Após tocar nível N: silêncio por 8min para qualquer nível <= N
    - Antes de tocar: confirmação após 5s (recoleta); toca nível confirmado (>=2)
    """

    def __init__(self):
        self.nivel_anterior = 0

        # silêncio "até" (por níveis <= silence_level)
        self.silence_level = 0
        self.silence_until = 0.0

        # confirmação pendente
        self.confirm_pending = False
        self._confirm_timer = None
        self._lock = threading.Lock()

        # mantém compatibilidade com o resto do runtime (random)
        self.ultimo_alarme_l2 = 0.0
        self.ultimo_alarme_l3 = 0.0
        self.ultimo_alarme_l4 = 0.0
        self.ultimo_random = 0.0

    def nivel_combinado(self, est: dict) -> int:
        return max(est.get("pitch_nivel", 0), est.get("roll_nivel", 0))

    def _now(self) -> float:
        return time.monotonic()

    def _is_silenced_locked(self, nivel: int, now: float) -> bool:
        return (nivel >= 2) and (nivel <= self.silence_level) and (now < self.silence_until)

    def _apply_silence_locked(self, nivel: int, now: float) -> None:
        self.silence_level = int(nivel)
        self.silence_until = now + ALARM_SILENCE_SEC
        if nivel == 2:
            self.ultimo_alarme_l2 = now
        elif nivel == 3:
            self.ultimo_alarme_l3 = now
        elif nivel == 4:
            self.ultimo_alarme_l4 = now

    def maybe_schedule(self, est: dict) -> None:
        """Chamado no loop principal a cada atualização 'normal'."""
        nivel = self.nivel_combinado(est)
        now = self._now()

        with self._lock:
            prev = self.nivel_anterior
            self.nivel_anterior = nivel  # sempre atualiza a referência anterior

            # L0/L1 nunca tocam
            if nivel < 2:
                return

            # Só dispara quando SUBIR
            if nivel <= prev:
                return

            # Se já existe confirmação em andamento, não empilha
            if self.confirm_pending:
                return

            # Respeita silêncio (8 min) para <= nível silenciado
            if self._is_silenced_locked(nivel, now):
                return

            # Mantém sua lógica atual de mute manual L2/L3 (L4 continua podendo tocar)
            if nivel <= 3 and is_muted_L23():
                return

            # Agenda confirmação (5s)
            self.confirm_pending = True
            self._confirm_timer = threading.Timer(ALARM_CONFIRM_SEC, self._confirm_and_alarm)
            self._confirm_timer.daemon = True
            self._confirm_timer.start()

    def _confirm_and_alarm(self) -> None:
        try:
            # se estiver encerrando, não toca nada
            if P1._quit_evt and P1._quit_evt.is_signaled():
                return

            est2 = _coletar_est_para_confirmacao()
            if not est2:
                return

            nivel2 = self.nivel_combinado(est2)

            # confirmação caiu para L0/L1 -> não toca
            if nivel2 < 2:
                return

            # respeita mute manual L2/L3 na confirmação também
            if nivel2 <= 3 and is_muted_L23():
                return

            now = self._now()
            with self._lock:
                # silêncio é sagrado
                if self._is_silenced_locked(nivel2, now):
                    return

                # aplica silêncio ANTES de tocar, para evitar duplicidade enquanto toca
                self._apply_silence_locked(nivel2, now)

            _tocar_alarme_pitch_roll(nivel2, est2)

        finally:
            with self._lock:
                self.confirm_pending = False
                self._confirm_timer = None


alarm_state = AlarmState()


def processar_alarme_pitch_roll(est: dict) -> None:
    """Entry-point simples para o runtime chamar."""
    alarm_state.maybe_schedule(est)



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
    pitch_txt = _fmt_or_dash(p, "{:.1f}")
    roll_txt = _fmt_or_dash(r, "{:.1f}")
    rajada_txt = _fmt_or_dash(raj, "{:.2f}")


    

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
                pitch_txt=pitch_txt,
                roll_txt=roll_txt,
                rajada_txt=rajada_txt,

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
