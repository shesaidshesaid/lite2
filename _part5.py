#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Estado, servidor de controle e renderização de HTML."""

from __future__ import annotations

from string import Template

import json
import os
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import _part1 as P1
import _part2 as P2
import _part4 as P4
from _html_fallback import HTML_TPL

import contextlib

_CLIENT_ABORT_EXC = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


# =========================================================
# Alarm State (SIMPLIFICADO)
# =========================================================

ALARM_CONFIRM_SEC = 5.0
ALARM_SILENCE_SEC = 11 * 60.0  # 11 minutos


# =========================================================
# LIVE VIEW (estado em memória para o painel HTTP + /data.json)
# =========================================================

_LIVE_LOCK = threading.Lock()
_LIVE_VIEW: Dict[str, Any] = {
    "last_epoch_ms": int(time.time() * 1000),
    "rot": "⚠ SEM DADOS",
    "status_cor": "amarelo",
    "pitch_txt": "---",
    "pitch_cor": "amarelo",
    "roll_txt": "---",
    "roll_cor": "amarelo",
    "vento_med_txt": "---",
    "vento_cor": "verde",
    "rajada_txt": "---",
    "rajada_cor": "verde",
    "wdir_aj": "---",
    "wdir_lbl": "---",
    "barometro": "---",
    "hora_html": "---",
}

WRITE_HTML_FILE = False  # <- desliga geração do pitch_roll.html



def _get_live_view() -> Dict[str, Any]:
    with _LIVE_LOCK:
        return dict(_LIVE_VIEW)


def _set_live_view(**kv) -> None:
    with _LIVE_LOCK:
        _LIVE_VIEW.update(kv)


# =========================================================
# Alarm confirmation helpers
# =========================================================

def _coletar_est_para_confirmacao():
    """Coleta uma leitura 'agora' para confirmar nível (sem depender do loop de 20s)."""
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = P2.coletar_wind_com_fallback(tentativas=1, timeout=5)

        dados = merge_dados(d_pr, d_wind)
        if not dados:
            return None

        return P4.avaliar_de_json(dados)
    except Exception:
        P1.log.exception("Falha ao confirmar leitura de alarme")
        return None


def _tocar_alarme_pitch_roll(nivel: int, est: dict) -> None:
    cond = []
    if est.get("pitch_nivel", 0) >= 2 and est.get("pitch_rot") != "NIVELADA":
        cond.append(est["pitch_rot"])
    if est.get("roll_nivel", 0) >= 2 and est.get("roll_rot") != "NIVELADA":
        cond.append(est["roll_rot"])

    P1.log_event(
        "ALARM_PITCHROLL",
        level=nivel,
        pitch=est.get("pitch_val"),
        roll=est.get("roll_val"),
        dirs=",".join(cond) if cond else "NONE",
    )

    def _seq():
        P1.tocar_alerta(nivel)
        P1.falar_wavs(cond, incluir_atencao=(nivel >= 3), use_v2=(nivel >= 3))

    P1.run_audio_sequence(_seq, nome="pitch_roll")


class AlarmState:
    """
    Regras:
    - L0/L1: nunca toca
    - L2/L3/L4/L5: só toca quando subir (nivel_atual > nivel_anterior)
    - Após tocar nível N: silêncio por 11min para qualquer nível <= N
    - Confirmação dupla: 5s + 5s (duas recoletas) antes de tocar
    """

    def __init__(self):
        self.nivel_anterior = 0

        # silêncio "até" (por níveis <= silence_level)
        self.silence_level = 0
        self.silence_until = 0.0

        # confirmação em 2 estágios
        self.confirm_stage = 0  # 0=nenhuma, 1=aguardando 1a confirmação, 2=aguardando 2a confirmação
        self._confirm_timer1 = None
        self._confirm_timer2 = None

        self._lock = threading.Lock()

        # compat
        self.ultimo_alarme_l2 = 0.0
        self.ultimo_alarme_l3 = 0.0
        self.ultimo_alarme_l4 = 0.0
        self.ultimo_alarme_l5 = 0.0
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
        elif nivel == 5:
            self.ultimo_alarme_l5 = now

    def _log_alarm_skip(self, reason: str, level: int, prev: int | None = None) -> None:
        P1.log_event("ALARM_SUPPRESS", reason=reason, level=level, prev=prev)

    def maybe_schedule(self, est: dict) -> None:
        """Chamado no loop principal a cada atualização 'normal'."""
        nivel = self.nivel_combinado(est)
        now = self._now()

        with self._lock:
            prev = self.nivel_anterior
            self.nivel_anterior = nivel

            # L0/L1 nunca tocam
            if nivel < 2:
                return

            # Só dispara quando SUBIR
            if nivel <= prev:
                return

            # Respeita silêncio (11 min) para <= nível silenciado
            if self._is_silenced_locked(nivel, now):
                self._log_alarm_skip("silenced", nivel, prev)
                return

            # Mantém mute manual L2/L3
            if nivel <= 3 and is_muted_L23():
                self._log_alarm_skip("muted_L23", nivel, prev)
                return

            # Se já existe confirmação em andamento, não empilha
            if self.confirm_stage != 0:
                self._log_alarm_skip("confirm_pending", nivel, prev)
                return

            # Agenda 1ª confirmação (5s)
            self.confirm_stage = 1
            self._confirm_timer1 = threading.Timer(ALARM_CONFIRM_SEC, self._confirm_stage1)
            self._confirm_timer1.daemon = True
            self._confirm_timer1.start()

    def _confirm_stage1(self) -> None:
        try:
            if P1._quit_evt and P1._quit_evt.is_signaled():
                self._log_alarm_skip("quit_signal", level=0)
                return

            est2 = _coletar_est_para_confirmacao()
            if not est2:
                self._log_alarm_skip("confirm1_no_data", level=0)
                return

            nivel2 = self.nivel_combinado(est2)
            if nivel2 < 2:
                self._log_alarm_skip("confirm1_low_level", level=nivel2)
                return

            if nivel2 <= 3 and is_muted_L23():
                self._log_alarm_skip("confirm1_muted_L23", level=nivel2)
                return

            now = self._now()
            with self._lock:
                if self._is_silenced_locked(nivel2, now):
                    self._log_alarm_skip("confirm1_silenced", level=nivel2)
                    return

                # Agenda 2ª confirmação
                self.confirm_stage = 2
                self._confirm_timer2 = threading.Timer(ALARM_CONFIRM_SEC, self._confirm_stage2)
                self._confirm_timer2.daemon = True
                self._confirm_timer2.start()

        finally:
            # se não avançou para estágio 2, libera
            with self._lock:
                if self.confirm_stage == 1:
                    self.confirm_stage = 0
                self._confirm_timer1 = None

    def _confirm_stage2(self) -> None:
        try:
            if P1._quit_evt and P1._quit_evt.is_signaled():
                self._log_alarm_skip("quit_signal", level=0)
                return

            est3 = _coletar_est_para_confirmacao()
            if not est3:
                self._log_alarm_skip("confirm2_no_data", level=0)
                return

            nivel3 = self.nivel_combinado(est3)
            if nivel3 < 2:
                self._log_alarm_skip("confirm2_low_level", level=nivel3)
                return

            if nivel3 <= 3 and is_muted_L23():
                self._log_alarm_skip("confirm2_muted_L23", level=nivel3)
                return

            now = self._now()
            with self._lock:
                if self._is_silenced_locked(nivel3, now):
                    self._log_alarm_skip("confirm2_silenced", level=nivel3)
                    return

                # aplica silêncio ANTES de tocar
                self._apply_silence_locked(nivel3, now)

            _tocar_alarme_pitch_roll(nivel3, est3)

        finally:
            with self._lock:
                self.confirm_stage = 0
                self._confirm_timer1 = None
                self._confirm_timer2 = None




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
# Merge helpers
# =========================================================

def merge_dados(d_pr: Optional[Dict[str, Any]], d_wind: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d_pr and not d_wind:
        P1.log.warning("Sem dados de pitch/roll ou vento para mesclar.")
        P1.log_event("MERGE_EMPTY", pitch_roll=False, wind=False)
        return None

    dados: Dict[str, Any] = {}
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

    if not dados:
        P1.log.warning(
            "Merge retornou vazio apesar de entradas existirem (pr=%s, wind=%s).",
            bool(d_pr),
            bool(d_wind),
        )
        P1.log_event("MERGE_EMPTY", pitch_roll=bool(d_pr), wind=bool(d_wind))
        return None

    return dados


def refresh_html_now():
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = P2.coletar_wind_com_fallback(tentativas=1, timeout=5)
        dados = merge_dados(d_pr, d_wind)
        if not dados:
            P1.log_event("HTML_REFRESH_SKIP", reason="no_data")
            return False
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
        return True
    except Exception:
        return False


# =========================================================
# HTTP server
# =========================================================

class _ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def address_string(self):
        return "127.0.0.1"

    def _reply_json(self, obj: dict, code=200):
        data = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except _CLIENT_ABORT_EXC:
            # cliente (browser) cancelou/fechou/abortou: ignora
            return
        except Exception:
            # se der erro real aqui, não tente responder novamente (pode gerar loop de erro)
            P1.log.debug("Falha ao responder JSON", exc_info=True)
            return

   


    def _reply_html(self, html: str, code: int = 200):
        data = html.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except _CLIENT_ABORT_EXC:
            return
        except Exception:
            P1.log.debug("Falha ao responder HTML", exc_info=True)
            return


    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query or "")

            # Painel HTTP principal
            if path in ("/", "/index.html"):
                view = _get_live_view()
                html = Template(HTML_TPL).safe_substitute(
                    refresh_ms=int(P1.HTML_REFRESH_SEC * 1000),
                    stale_sec=int(P1.HTML_STALE_MAX_AGE_SEC),
                    port=int(P1.MUTE_CTRL_PORT),
                    last_epoch_ms=view.get("last_epoch_ms", int(time.time() * 1000)),
                    rot=view.get("rot", "⚠ SEM DADOS"),
                    status_cor=view.get("status_cor", "amarelo"),
                    pitch_txt=view.get("pitch_txt", "---"),
                    pitch_cor=view.get("pitch_cor", "amarelo"),
                    roll_txt=view.get("roll_txt", "---"),
                    roll_cor=view.get("roll_cor", "amarelo"),
                    vento_med_txt=view.get("vento_med_txt", "---"),
                    vento_cor=view.get("vento_cor", "verde"),
                    rajada_txt=view.get("rajada_txt", "---"),
                    rajada_cor=view.get("rajada_cor", "verde"),
                    wdir_aj=view.get("wdir_aj", "---"),
                    wdir_lbl=view.get("wdir_lbl", "---"),
                    barometro=view.get("barometro", "---"),
                    hora=view.get("hora_html", "---"),
                )
                self._reply_html(html, 200)
                return

            # Dados do painel (polling JS)
            if path == "/data.json":
                view = _get_live_view()
                view = {"ok": True, **view}
                self._reply_json(view, 200)
                return

            # Endpoints existentes
            if path == "/mute":
                mins = float(qs.get("mins", ["360"])[0])
                until = _set_mute_L23_for_minutes(mins)
                P1.log_event("MUTE", minutes=mins, until=until)
                self._reply_json({"ok": True, "muted": True, "muted_until": until})
                return

            if path == "/unmute":
                _clear_mute_L23()
                P1.log_event("UNMUTE")
                self._reply_json({"ok": True, "muted": False})
                return

            if path == "/mute_status":
                self._reply_json({"ok": True, "muted": is_muted_L23(), "muted_until": MUTE_L23_UNTIL_TS})
                return

            if path == "/wind_pref":
                prev = P1.WIND_PREF
                if qs.get("host"):
                    val = qs.get("host", ["auto"])[0]
                    if val == "auto":
                        P1.WIND_PREF = None
                    else:
                        P1.WIND_PREF = val
                if P1.WIND_PREF != prev:
                    P1.log_event("WIND_PREF", host=P1.WIND_PREF)
                self._reply_json({"ok": True, "host": P1.WIND_PREF})
                return

            self._reply_json({"ok": False, "error": "unknown"}, 404)
        except _CLIENT_ABORT_EXC:
            return
        except Exception:
            # Evita tentar responder numa conexão já quebrada
            P1.log.debug("Exceção em do_GET", exc_info=True)
            self._reply_json({"ok": False, "error": "exception"}, 500)

            return



def start_control_server(port: int = P1.MUTE_CTRL_PORT):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _ControlHandler)
    except Exception:
        return None
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    return srv





# =========================================================
# HTML writer + live state update
# =========================================================

def _fmt_or_dash(val, fmt: str) -> str:
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
    """
    Atualiza:
    1) Estado em memória (_LIVE_VIEW) -> painel HTTP (blindado)
    2) Arquivo HTML (opcional). Se travar por OneDrive/lock, não derruba o painel HTTP.
    """
    last_epoch_ms = int(time.time() * 1000)

    # textos já formatados (exibição)
    wdir_txt = _fmt_or_dash(wdir_aj, "{:.1f}")
    baro_txt = _fmt_or_dash(barometro, "{:.2f}")
    lbl_txt = "---" if (wdir_lbl is None or str(wdir_lbl).strip() == "") else str(wdir_lbl)
    vento_txt = _fmt_or_dash(vento_med, "{:.1f}")
    pitch_txt = _fmt_or_dash(p, "{:.1f}")
    roll_txt = _fmt_or_dash(r, "{:.1f}")
    rajada_txt = _fmt_or_dash(raj, "{:.1f}")

    dt = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    dt_show = dt if not wind_source else f'{dt} <span style="font-size:.85em;opacity:.75">(vento: {wind_source})</span>'

    # Atualiza estado do painel HTTP (/data.json)
    _set_live_view(
        last_epoch_ms=last_epoch_ms,
        rot=rot,
        status_cor=status,
        pitch_txt=pitch_txt,
        pitch_cor=pc,
        roll_txt=roll_txt,
        roll_cor=rc,
        vento_med_txt=vento_txt,
        vento_cor=vento_cor,
        rajada_txt=rajada_txt,
        rajada_cor=rcor,
        wdir_aj=wdir_txt,
        wdir_lbl=lbl_txt,
        barometro=baro_txt,
        hora_html=dt_show,
    )

    # Mantém gravação do HTML em disco (1 arquivo)
    try:
        html = Template(HTML_TPL).safe_substitute(
            refresh_ms=int(P1.HTML_REFRESH_SEC * 1000),
            stale_sec=int(P1.HTML_STALE_MAX_AGE_SEC),
            last_epoch_ms=last_epoch_ms,
            port=int(P1.MUTE_CTRL_PORT),

            rot=rot,
            status_cor=status,

            pitch_cor=pc,
            roll_cor=rc,
            rajada_cor=rcor,
            vento_cor=vento_cor,

            pitch_txt=pitch_txt,
            roll_txt=roll_txt,
            rajada_txt=rajada_txt,
            vento_med_txt=vento_txt,

            wdir_aj=wdir_txt,
            wdir_lbl=lbl_txt,
            barometro=baro_txt,

            hora=dt_show,
        )

        if WRITE_HTML_FILE:
            try:
                out_dir = os.path.dirname(P1.FILES["html"]) or "."
                os.makedirs(out_dir, exist_ok=True)
                with open(P1.FILES["html"], "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                P1.log.exception("Falha ao gravar HTML em %s", P1.FILES.get("html"))

    except Exception:
        P1.log.exception("Falha ao gravar HTML em %s", P1.FILES.get("html"))


def abrir_html_no_navegador():
    """Abre o painel HTTP (mais blindado, sem file:// e sem reload)."""
    try:
        url = f"http://127.0.0.1:{P1.MUTE_CTRL_PORT}/"
        webbrowser.open(url, new=0, autoraise=True)
    except Exception:
        pass


def abrir_html_file_no_navegador():
    """Opcional: abre o HTML por file:// (fallback/manual)."""
    try:
        uri = Path(P1.FILES["html"]).resolve().as_uri()
        webbrowser.open(uri, new=0, autoraise=True)
    except Exception:
        pass

import os
import subprocess
import sys
from pathlib import Path

def _desktop_dir() -> Path:
    """
    Tenta achar o Desktop real (muitas vezes é redirecionado para OneDrive).
    """
    userprofile = os.environ.get("USERPROFILE") or str(Path.home())
    candidates = []

    # Desktop “normal”
    candidates.append(Path(userprofile) / "Desktop")

    # Desktop redirecionado para OneDrive (corporativo)
    odc = os.environ.get("OneDriveCommercial")
    if odc:
        candidates.append(Path(odc) / "Desktop")

    od = os.environ.get("OneDrive")
    if od:
        candidates.append(Path(od) / "Desktop")

    for d in candidates:
        try:
            if d.exists():
                return d
        except Exception:
            pass

    # fallback
    return Path(userprofile) / "Desktop"


def _side_dir() -> Path:
    """
    Diretório 'ao lado' do executável/entrypoint.
    - Se empacotado com PyInstaller (`sys.frozen`), usa `sys.executable`.
    - Caso contrário, tenta usar `sys.argv[0]` ou o diretório deste arquivo.
    Fallback: `Path.cwd()`.
    """
    try:
        # PyInstaller / cx_Freeze executável
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent

        # Se invocado como script, tenta argv[0]
        if len(sys.argv) > 0 and sys.argv[0]:
            try:
                p = Path(sys.argv[0]).resolve()
                if p.exists():
                    return p.parent
            except Exception:
                pass

        # Usa o diretório deste módulo como última opção
        try:
            return Path(__file__).resolve().parent
        except Exception:
            return Path.cwd()
    except Exception:
        return Path.cwd()


def ensure_http_shortcut(port: int = 8765) -> None:
    """
    Cria um atalho .url (InternetShortcut) para o painel HTTP.
    Não usa PowerShell => não pisca console.
    """
    try:
        url = f"http://127.0.0.1:{int(port)}/"

        # Cria ao lado do executável (prioritário)
        try:
            side = _side_dir()
            side.mkdir(parents=True, exist_ok=True)
            url_path_side = side / "Lite2 - Painel.url"
            content = "[InternetShortcut]\n" f"URL={url}\n"
            if not url_path_side.exists():
                url_path_side.write_text(content, encoding="utf-8")
        except Exception:
            pass

        # Mantém fallback para Desktop
        try:
            desktop = _desktop_dir()
            desktop.mkdir(parents=True, exist_ok=True)
            url_path = desktop / "Lite2 - Painel.url"
            content = "[InternetShortcut]\n" f"URL={url}\n"
            if not url_path.exists():
                url_path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    except Exception:
        # não pode quebrar o app
        try:
            import _part1 as P1
            P1.log.debug("Falha ao criar atalho do painel", exc_info=True)
        except Exception:
            pass


def ensure_log_shortcut(log_path: str) -> None:
    """
    Cria um .lnk no Desktop que abre o log no Notepad.
    O atalho final NÃO pisca console ao abrir.
    A criação usa PowerShell escondido para gerar o .lnk sem depender de pywin32.
    """
    try:
        lp = Path(log_path)
        # Garante pasta do log
        lp.parent.mkdir(parents=True, exist_ok=True)

        # Primeiro: cria .lnk ao lado do executável (prioritário)
        try:
            side = _side_dir()
            side.mkdir(parents=True, exist_ok=True)
            lnk_side = side / "Lite2 - Log.lnk"
            if not lnk_side.exists():
                ps_side = rf"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{str(lnk_side)}")
$Shortcut.TargetPath = "$env:WINDIR\system32\notepad.exe"
$Shortcut.Arguments = '"{str(lp)}"'
$Shortcut.WorkingDirectory = "{str(lp.parent)}"
$Shortcut.IconLocation = "$env:WINDIR\system32\notepad.exe,0"
$Shortcut.Save()
"""
                CREATE_NO_WINDOW = 0x08000000
                subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", ps_side],
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        except Exception:
            pass

        # Mantém comportamento antigo: cria no Desktop também
        try:
            desktop = _desktop_dir()
            desktop.mkdir(parents=True, exist_ok=True)
            lnk = desktop / "Lite2 - Log.lnk"
            if lnk.exists():
                return

            ps = rf"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{str(lnk)}")
$Shortcut.TargetPath = "$env:WINDIR\system32\notepad.exe"
$Shortcut.Arguments = '"{str(lp)}"'
$Shortcut.WorkingDirectory = "{str(lp.parent)}"
$Shortcut.IconLocation = "$env:WINDIR\system32\notepad.exe,0"
$Shortcut.Save()
"""

            CREATE_NO_WINDOW = 0x08000000
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", ps],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

    except Exception:
        try:
            import _part1 as P1
            P1.log.debug("Falha ao criar atalho do log", exc_info=True)
        except Exception:
            pass







__all__ = [
    "AlarmState",
    "alarm_state",
    "processar_alarme_pitch_roll",
    "is_muted_L23",
    "start_control_server",
    "merge_dados",
    "ensure_http_shortcut",
    "refresh_html_now",
    "gerar_html",
    "abrir_html_no_navegador",
    "abrir_html_file_no_navegador",
]
