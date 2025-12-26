#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, argparse, logging, re, ctypes, webbrowser, math, atexit, threading, json
from ctypes import wintypes
from datetime import datetime, timedelta
from heapq import nlargest
from pathlib import Path

try:
    import pygame
except Exception:
    pygame = None

try:
    import requests
except Exception:
    requests = None

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# =========================
# Constantes (originais)
# =========================
HTML_REFRESH_SEC, HTML_STALE_MAX_AGE_SEC = 20, 40
HTML_WIN_PITCH = HTML_WIN_ROLL = 39
COLETA_INTERVAL = 20

COOLDOWN_L2_MIN = 11
COOLDOWN_L3_MIN = 10
COOLDOWN_L4_MIN = 9
INIBICAO_L3_SOBRE_L2_MIN = 11
INIBICAO_L4_SOBRE_L23_MIN = 10
RESET_ESTAVEL_CICLOS = 3
OSCILACAO_MAX_MUDANCAS = 5
OSCILACAO_JANELA_MIN = 10
AUTO_MUTE_OSCILACAO_MIN = 15

RANDOM_INTERVAL_HOURS = 5
RANDOM_SILENCE_PERIOD_MIN = 50

VOLUMES = {'beep_l2': 0.07, 'beep_l3': 0.09, 'beep_l4': 0.15, 'voz': 100, 'beep_fallback': 0.07}
FATOR_CORRECAO_PITCH = FATOR_CORRECAO_ROLL = 0.7
AA_PITCH, AA_ROLL = 0.08, -0.08
NIVELADA_POS, NIVELADA_NEG = 0.34, -0.34

L2_LEVELS = [0.50, -0.50, 0.50, -0.50]
L3_LEVELS = [1.10, -1.10, 1.10, -1.10]
OFFSET_L4 = 0.35
L4_LEVELS = [L3_LEVELS[0] + OFFSET_L4, L3_LEVELS[1] - OFFSET_L4, L3_LEVELS[2] + OFFSET_L4, L3_LEVELS[3] - OFFSET_L4]

JANELA_WIND_SEC, TOP_N_WIND = 120, 4
LOG_RETENCAO_HRS, VENTO_ALARME_CHECK_INTERVAL_MIN = 48, 15
VENTO_ALARME_THRESHOLD, VENTO_REARME_MIN = 21.0, 76
MUTE_CTRL_PORT = 8765

URL_SMP_PITCH_ROLL = "http://smp18ocn01:8509/get/data?missingvalues=null"
WIND_HOSTS_ORDER = ["smp18ocn01", "smp19ocn02", "smp35ocn01", "smp53ocn01"]
WIND_PREF = None
GET_PATH = "/get/data?missingvalues=null"
KEYS_PR = ("ptchwnd", "rollwnd")
KEYS_WIND = ("windwnd", "winddirmeanv", "airpresslmeanv", "windsplv", "winddirmean",
             "airpresmeanv", "airpresslmean", "airpresmean", "windspdauxmeanv", "windspdauxmaxv")

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
WAIT_OBJECT_0, EVENT_MODIFY_STATE = 0x00000000, 0x0002
QUIT_EVENT_NAME = "Global\\PitchRollMonitorQuitEvent"

BASE_DIR = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))
RESOURCE_ROOT = getattr(sys, '_MEIPASS', BASE_DIR) if getattr(sys, 'frozen', False) else BASE_DIR
AUDIO_DIR = os.path.join(RESOURCE_ROOT, "audioss")

FILES = {
    'log': os.path.join(BASE_DIR, "pitch_roll_log.txt"),
    'html': os.path.join(BASE_DIR, "pitch_roll.html"),
    'refresh_js': os.path.join(BASE_DIR, "refresh_token.js"),
    # template externo (a ser entregue como pitch_roll_template.html)
    'html_template': os.path.join(RESOURCE_ROOT, "pitch_roll_template.html"),
}

logging.basicConfig(filename="monitor.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("painel")

REGEX = {
    'wind_src': re.compile(r"Usando\s+vento\s+(?:de|do|da)\s+([A-Za-z0-9._:\-]+)", re.IGNORECASE),
    'log_keep': re.compile(r"^\s*(\d{2}:\d{2})\s+(\d{2}/\d{2}/\d{4});"),
    'log_values': re.compile(
        r"^\s*\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4};\s*([-+]?\d*\.?\d+);\s*([-+]?\d*\.?\d+);\s*([-+]?\d*\.?\d+)")
}

# =========================
# Screen awake
# =========================
def keep_screen_on(enable: bool = True):
    try:
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if enable else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass

# =========================
# Windows API (event/mutex)
# =========================
kernel32 = None
if os.name == "nt":
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _api_funcs = {
        'CreateEventW': ([wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'OpenEventW': ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetEvent': ([wintypes.HANDLE], wintypes.BOOL),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'CreateMutexW': ([wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
    }

    for name, (args, ret_type) in _api_funcs.items():
        func = getattr(kernel32, name)
        func.argtypes, func.restype = args, ret_type

def signal_quit(name: str = QUIT_EVENT_NAME) -> bool:
    if not kernel32:
        return False
    h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not h:
        return False
    try:
        return bool(kernel32.SetEvent(h))
    finally:
        kernel32.CloseHandle(h)

class QuitEvent:
    __slots__ = ("name", "handle")

    def __init__(self, name: str = QUIT_EVENT_NAME):
        self.name, self.handle = name, None

    def create(self):
        if not kernel32:
            raise OSError("kernel32 indisponível (não Windows?)")
        h = kernel32.CreateEventW(None, True, False, self.name)
        if not h:
            raise OSError(ctypes.get_last_error())
        self.handle = h
        return h

    def is_signaled(self) -> bool:
        if not kernel32:
            return False
        return bool(self.handle) and kernel32.WaitForSingleObject(self.handle, 0) == WAIT_OBJECT_0

    def close(self):
        if not kernel32:
            return
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

_quit_evt = None
_mutex_handle = None
WIND_PREF = None

def obter_mutex():
    global _mutex_handle
    if not kernel32:
        return False, None
    ctypes.set_last_error(0)
    _mutex_handle = kernel32.CreateMutexW(None, False, "PitchRollMonitorMutex")
    if not _mutex_handle:
        return False, None
    return (ctypes.get_last_error() == 183), _mutex_handle

# =========================
# Audio
# =========================
audio_ok, CHANNELS, _SND = True, {}, {}

if pygame is None:
    audio_ok = False
else:
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        pygame.mixer.set_num_channels(4)
        CHANNELS = {name: pygame.mixer.Channel(i) for i, name in enumerate(['voz', 'beep', 'vento'])}
    except Exception:
        audio_ok = False

def _carregar_wav(nome_base: str):
    if not audio_ok:
        return None
    path = os.path.join(AUDIO_DIR, f"{nome_base}.wav")
    try:
        snd = pygame.mixer.Sound(path)
        _SND[nome_base] = snd
        return snd
    except Exception:
        return None

def _init_audios():
    audio_files = ("l2", "l3", "l4", "atencao", "proa", "popa", "boreste", "bombordo",
                   "proabombordo", "proaboreste", "popabombordo", "popaboreste", "av1", "av2", "av3", "random")
    for nm in audio_files:
        _carregar_wav(nm)

_init_audios()

def _esperar_canal(canal, timeout_s=10.0):
    if not audio_ok or canal is None:
        return
    t0 = time.monotonic()
    while canal.get_busy():
        try:
            pygame.time.delay(10)
        except Exception:
            time.sleep(0.01)
        if time.monotonic() - t0 > timeout_s:
            break

def tocar_alerta(nivel_num: int):
    if not audio_ok or not CHANNELS.get('beep'):
        return

    nome = f"l{min(nivel_num, 4)}" if nivel_num >= 2 else "l2"
    snd = _SND.get(nome) or _carregar_wav(nome)
    if not snd:
        for fallback in ["l3", "l2"]:
            snd = _SND.get(fallback) or _carregar_wav(fallback)
            if snd:
                break
    if not snd:
        return

    try:
        vol = VOLUMES.get(f'beep_l{min(nivel_num, 4)}', VOLUMES['beep_fallback'])
        CHANNELS['beep'].set_volume(max(0.0, min(1.0, vol)))
        CHANNELS['beep'].play(snd)
        _esperar_canal(CHANNELS['beep'], max(1.5, snd.get_length() + 0.5))
    except Exception:
        pass

_COMBO_MAP = {
    frozenset(["PROA", "BOMBORDO"]): "proabombordo",
    frozenset(["PROA", "BORESTE"]): "proaboreste",
    frozenset(["POPA", "BOMBORDO"]): "popabombordo",
    frozenset(["POPA", "BORESTE"]): "popaboreste"
}

def _combo_key(direcoes_upper: set):
    for combo_set, key in _COMBO_MAP.items():
        if combo_set.issubset(direcoes_upper):
            return key
    return None

def _tocar_em_canal(nome_base: str, vol01: float):
    if not audio_ok or not CHANNELS.get('voz'):
        return
    snd = _SND.get(nome_base) or _carregar_wav(nome_base)
    if not snd:
        return

    try:
        CHANNELS['voz'].set_volume(max(0.0, min(1.0, vol01)))
        CHANNELS['voz'].play(snd)
        _esperar_canal(CHANNELS['voz'], max(1.5, snd.get_length() + 1.0))
    except Exception:
        pass

def falar_wavs(direcoes, incluir_atencao: bool):
    if not audio_ok:
        return

    vol01 = max(0.0, min(1.0, VOLUMES['voz'] / 100.0))
    validos = {"PROA", "POPA", "BORESTE", "BOMBORDO"}
    dirs = [d.strip().upper() for d in (direcoes or []) if d and d.strip().upper() in validos]

    if CHANNELS.get('voz'):
        try:
            CHANNELS['voz'].stop()
        except Exception:
            pass

    if incluir_atencao:
        if _quit_evt and _quit_evt.is_signaled():
            return
        _tocar_em_canal("atencao", vol01)
        time.sleep(0.12)

    if not dirs:
        return

    combo = _combo_key(set(dirs))
    if combo and (_SND.get(combo) or _carregar_wav(combo)):
        if _quit_evt and _quit_evt.is_signaled():
            return
        _tocar_em_canal(combo, vol01)
    else:
        for d in dirs:
            if _quit_evt and _quit_evt.is_signaled():
                return
            _tocar_em_canal(d.lower(), vol01)
            time.sleep(0.12)

    time.sleep(0.25)

def tocar_alarme_vento():
    if not audio_ok:
        return

    canal = CHANNELS.get('vento') or CHANNELS.get('beep') or CHANNELS.get('voz')
    if canal is None:
        return

    for nm in ("av1", "av2", "av3"):
        if _quit_evt and _quit_evt.is_signaled():
            return
        snd = _SND.get(nm) or _carregar_wav(nm)
        if not snd:
            continue

        try:
            canal.set_volume(1.0)
            canal.play(snd)
            _esperar_canal(canal, max(1.2, snd.get_length() + 0.3))
        except Exception:
            pass
        time.sleep(1.0)

def tocar_random():
    if not audio_ok:
        return

    canal = CHANNELS.get('voz') or CHANNELS.get('beep')
    if canal is None:
        return

    snd = _SND.get('random') or _carregar_wav('random')
    if not snd:
        return

    try:
        canal.set_volume(1.0)
        canal.play(snd)
        _esperar_canal(canal, max(2.0, snd.get_length() + 0.5))
    except Exception:
        pass

# =========================
# HTTP / Requests session
# =========================
session = None
if requests is not None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

def coletar_json(url: str, tentativas=3, timeout=10):
    if session is None:
        return None
    for i in range(tentativas):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == tentativas - 1:
                return None
            time.sleep(0.5)
    return None
