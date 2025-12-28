#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Núcleo de constantes, utilidades estáveis e inicializações globais."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import logging
import math
import os
import re
import sys
import time
from ctypes import wintypes
from typing import Optional
from logging.handlers import RotatingFileHandler


# =========================
# Dependências opcionais
# =========================
requests_spec = importlib.util.find_spec("requests")
requests = importlib.import_module("requests") if requests_spec else None

pygame_spec = importlib.util.find_spec("pygame")
pygame = importlib.import_module("pygame") if pygame_spec else None

# =========================
# Constantes
# =========================
HTML_REFRESH_SEC, HTML_STALE_MAX_AGE_SEC = 10, 40
HTML_WIN_PITCH = HTML_WIN_ROLL = 39
COLETA_INTERVAL = 9




RANDOM_INTERVAL_HOURS = 4
RANDOM_SILENCE_PERIOD_MIN = 40

VOLUMES = {"beep_l2": 0.07, "beep_l3": 0.09, "beep_l4": 0.15, "voz": 100, "beep_fallback": 0.07}

FATOR_CORRECAO_PITCH = FATOR_CORRECAO_ROLL = 0.74
AA_PITCH, AA_ROLL = 0.08, -0.08
NIVELADA_POS, NIVELADA_NEG = 0.34, -0.34

L2_LEVELS = [0.01, -0.01, 0.01, -0.01]
L3_LEVELS = [0.10, -0.10, 0.10, -0.10]

OFFSET_L4 = 0.45
L4_LEVELS = [
    L3_LEVELS[0] + OFFSET_L4,
    L3_LEVELS[1] - OFFSET_L4,
    L3_LEVELS[2] + OFFSET_L4,
    L3_LEVELS[3] - OFFSET_L4,
]

JANELA_WIND_SEC, TOP_N_WIND = 120, 4
LOG_RETENCAO_HRS, VENTO_ALARME_CHECK_INTERVAL_MIN = 48, 15
VENTO_ALARME_THRESHOLD, VENTO_REARME_MIN = 21.0, 76
MUTE_CTRL_PORT = 8765

URL_SMP_PITCH_ROLL = "http://smp18ocn01:8509/get/data?missingvalues=null"
WIND_HOSTS_ORDER = ["smp18ocn01", "smp19ocn02", "smp35ocn01", "smp53ocn01"]
WIND_PREF: Optional[str] = None
GET_PATH = "/get/data?missingvalues=null"
KEYS_PR = ("ptchwnd", "rollwnd")
KEYS_WIND = (
    "windwnd",
    "winddirmeanv",
    "airpresslmeanv",
    "windsplv",
    "winddirmean",
    "airpresmeanv",
    "airpresslmean",
    "airpresmean",
    "windspdauxmeanv",
    "windspdauxmaxv",
    "windspdauxmean",
    "windspdauxmax",
    "windspdmean",
    "windspdmeanv",
    "gustspdmax",
    "gustspdmaxv",
)

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
WAIT_OBJECT_0, EVENT_MODIFY_STATE = 0x00000000, 0x0002
QUIT_EVENT_NAME = "Global\\PitchRollMonitorQuitEvent"

BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
RESOURCE_ROOT = getattr(sys, "_MEIPASS", BASE_DIR) if getattr(sys, "frozen", False) else BASE_DIR
AUDIO_DIR = os.path.join(RESOURCE_ROOT, "audioss")

FILES = {
    "log": os.path.join(BASE_DIR, "pitch_roll_log.txt"),
    "html": os.path.join(BASE_DIR, "pitch_roll.html"),
}


def ordered_wind_hosts(preferencia: Optional[str] = None):
    """Retorna a ordem de hosts de vento, priorizando a preferência quando válida."""
    if preferencia and preferencia in WIND_HOSTS_ORDER:
        return [preferencia] + [h for h in WIND_HOSTS_ORDER if h != preferencia]
    return list(WIND_HOSTS_ORDER)

# =========================
# Logging com rotação
# =========================
LOG_FILE = os.path.join(BASE_DIR, "monitor.log")
LOG_MAX_BYTES = 5 * 1024 * 1024   # 5 MB
LOG_BACKUP_COUNT = 5              # mantém monitor.log.1 ... monitor.log.5


def _setup_logging() -> logging.Logger:
    """Configura logging com rotação (idempotente) e devolve o logger nomeado."""
    logger = logging.getLogger("painel")
    if getattr(logger, "_pitchroll_logging_configured", False):
        return logger

    level_name = os.environ.get("PITCHROLL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(fmt)

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        logger.addHandler(handler)

    logger._pitchroll_logging_configured = True
    return logger


log = _setup_logging()


REGEX = {
    "wind_src": re.compile(r"Usando\s+vento\s+(?:de|do|da)\s+([A-Za-z0-9._:\-]+)", re.IGNORECASE),
    "log_keep": re.compile(r"^\s*(\d{2}:\d{2})\s+(\d{2}/\d{2}/\d{4});"),
    "log_values": re.compile(
        r"^\s*\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4};\s*([-+]?\d*\.?\d+);\s*([-+]?\d*\.?\d+);\s*([-+]?\d*\.?\d+)"
    ),
}

# =========================
# Helpers
# =========================

def safe_float(val: object, default: Optional[float] = None) -> Optional[float]:
    try:
        out = float(val)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, val))


def fmt_or_placeholder(val: Optional[float], fmt: str, placeholder: str = "---") -> str:
    return (fmt % val) if val is not None else placeholder


# =========================
# Screen awake (Windows)
# =========================

def keep_screen_on(enable: bool = True) -> None:
    try:
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if enable else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        log.debug("Falha ao ajustar SetThreadExecutionState", exc_info=True)


# =========================
# Windows API (event/mutex)
# =========================
kernel32 = None
if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _api_funcs = {
        "CreateEventW": ([wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenEventW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CreateMutexW": ([wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
    }
    for name, (args, ret_type) in _api_funcs.items():
        func = getattr(kernel32, name)
        func.argtypes, func.restype = args, ret_type


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


_quit_evt: Optional[QuitEvent] = None
_mutex_handle = None


def signal_quit(name: str = QUIT_EVENT_NAME) -> bool:
    if not kernel32:
        return False

    def _try(name_try: str) -> bool:
        h = None
        try:
            # tenta abrir (se existir)
            h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name_try)
            if not h:
                # abre se existir / cria se não existir (evita race)
                h = kernel32.CreateEventW(None, True, False, name_try)
            if not h:
                return False
            return bool(kernel32.SetEvent(h))
        finally:
            try:
                if h:
                    kernel32.CloseHandle(h)
            except Exception:
                pass

    # 1) tenta como está (Global\...)
    if _try(name):
        return True

    # 2) fallback corporativo: Local\...
    if isinstance(name, str) and name.startswith("Global\\"):
        local_name = "Local\\" + name[len("Global\\"):]
        if _try(local_name):
            return True

    return False


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
# HTTP / Requests session
# =========================
session = None
if requests is not None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})


def coletar_json(url: str, tentativas: int = 3, timeout: int = 10):
    if session is None:
        return None
    for tent in range(tentativas):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            log.debug("Falha na tentativa %s para %s", tent + 1, url, exc_info=True)
            if tent == tentativas - 1:
                log.warning("Falha ao coletar %s", url, exc_info=True)
                return None
            time.sleep(0.5)
    return None


# =========================
# Audio
# =========================
audio_ok, CHANNELS, _SND = True, {}, {}


def _init_audio() -> bool:
    """Inicializa mixer/filas e devolve True/False indicando sucesso."""
    global CHANNELS
    if pygame is None:
        log.info("Pygame não encontrado; seguindo sem áudio.")
        return False
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        pygame.mixer.set_num_channels(4)
        CHANNELS = {name: pygame.mixer.Channel(i) for i, name in enumerate(["voz", "beep", "vento"])}
        return True
    except Exception:
        log.warning("Falha ao inicializar áudio; seguindo sem áudio.", exc_info=True)
        CHANNELS = {}
        return False


audio_ok = _init_audio()


def _carregar_wav(nome_base: str):
    if not audio_ok:
        return None
    path = os.path.join(AUDIO_DIR, f"{nome_base}.wav")
    try:
        snd = pygame.mixer.Sound(path)
        _SND[nome_base] = snd
        return snd
    except Exception:
        log.warning("Falha ao carregar áudio %s", path, exc_info=True)
        return None


def _esperar_canal(canal, timeout_s: float = 10.0):
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


def _tocar_em_canal(nome_base: str, vol01: float, canal_nome: str):
    if not audio_ok or not CHANNELS.get(canal_nome):
        return
    snd = _SND.get(nome_base) or _carregar_wav(nome_base)
    if not snd:
        return
    try:
        CHANNELS[canal_nome].set_volume(clamp(vol01, 0.0, 1.0))
        CHANNELS[canal_nome].play(snd)
        _esperar_canal(CHANNELS[canal_nome], max(1.5, snd.get_length() + 0.5))
    except Exception:
        log.warning("Erro ao tocar áudio %s", nome_base, exc_info=True)


def tocar_alerta(nivel_num: int):
    if not audio_ok:
        return
    nome = f"l{min(nivel_num, 4)}" if nivel_num >= 2 else "l2"
    snd = _SND.get(nome) or _carregar_wav(nome)
    if not snd:
        for fallback in ["l3", "l2"]:
            snd = _SND.get(fallback) or _carregar_wav(fallback)
            if snd:
                nome = fallback
                break
    if not snd:
        return
    vol = VOLUMES.get(f"beep_{nome}", VOLUMES["beep_fallback"])
    _tocar_em_canal(nome, vol, "beep")


_COMBO_MAP = {
    frozenset(["PROA", "BOMBORDO"]): "proabombordo",
    frozenset(["PROA", "BORESTE"]): "proaboreste",
    frozenset(["POPA", "BOMBORDO"]): "popabombordo",
    frozenset(["POPA", "BORESTE"]): "popaboreste",
}


def _combo_key(direcoes_upper: set):
    for combo_set, key in _COMBO_MAP.items():
        if combo_set.issubset(direcoes_upper):
            return key
    return None


def falar_wavs(direcoes, incluir_atencao: bool):
    if not audio_ok:
        return
    vol01 = clamp(VOLUMES.get("voz", 100) / 100.0, 0.0, 1.0)
    validos = {"PROA", "POPA", "BORESTE", "BOMBORDO"}
    dirs = [d.strip().upper() for d in (direcoes or []) if d and d.strip().upper() in validos]

    if CHANNELS.get("voz"):
        try:
            CHANNELS["voz"].stop()
        except Exception:
            pass

    if incluir_atencao:
        if _quit_evt and _quit_evt.is_signaled():
            return
        _tocar_em_canal("atencao", vol01, "voz")
        time.sleep(0.12)

    if not dirs:
        return

    combo = _combo_key(set(dirs))
    if combo and (_SND.get(combo) or _carregar_wav(combo)):
        if _quit_evt and _quit_evt.is_signaled():
            return
        _tocar_em_canal(combo, vol01, "voz")
    else:
        for d in dirs:
            if _quit_evt and _quit_evt.is_signaled():
                return
            _tocar_em_canal(d.lower(), vol01, "voz")
            time.sleep(0.12)

    time.sleep(0.25)


def tocar_alarme_vento():
    if not audio_ok:
        return
    canal = CHANNELS.get("vento") or CHANNELS.get("beep") or CHANNELS.get("voz")
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
    canal = CHANNELS.get("voz") or CHANNELS.get("beep")
    if canal is None:
        return
    snd = _SND.get("random") or _carregar_wav("random")
    if not snd:
        return
    try:
        canal.set_volume(1.0)
        canal.play(snd)
        _esperar_canal(canal, max(2.0, snd.get_length() + 0.5))
    except Exception:
        pass


# =========================
# Argparse helper (compartilhado)
# =========================

def base_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true", help="pede para a instância em execução encerrar e sai")
    return ap


__all__ = [
    "HTML_REFRESH_SEC",
    "HTML_STALE_MAX_AGE_SEC",
    "HTML_WIN_PITCH",
    "HTML_WIN_ROLL",
    "COLETA_INTERVAL",
    "RANDOM_INTERVAL_HOURS",
    "RANDOM_SILENCE_PERIOD_MIN",
    "VOLUMES",
    "FATOR_CORRECAO_PITCH",
    "FATOR_CORRECAO_ROLL",
    "AA_PITCH",
    "AA_ROLL",
    "NIVELADA_POS",
    "NIVELADA_NEG",
    "L2_LEVELS",
    "L3_LEVELS",
    "L4_LEVELS",
    "JANELA_WIND_SEC",
    "TOP_N_WIND",
    "LOG_RETENCAO_HRS",
    "VENTO_ALARME_CHECK_INTERVAL_MIN",
    "VENTO_ALARME_THRESHOLD",
    "VENTO_REARME_MIN",
    "MUTE_CTRL_PORT",
    "URL_SMP_PITCH_ROLL",
    "WIND_HOSTS_ORDER",
    "WIND_PREF",
    "GET_PATH",
    "KEYS_PR",
    "KEYS_WIND",
    "FILES",
    "log",
    "REGEX",
    "keep_screen_on",
    "QuitEvent",
    "signal_quit",
    "obter_mutex",
    "coletar_json",
    "ordered_wind_hosts",
    "tocar_alerta",
    "falar_wavs",
    "tocar_alarme_vento",
    "tocar_random",
    "audio_ok",
    "CHANNELS",
    "_quit_evt",
    "fmt_or_placeholder",
    "safe_float",
    "clamp",
    "base_argparser",
]
