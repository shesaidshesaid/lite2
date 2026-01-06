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
import threading
import time

import tempfile
from datetime import datetime, timedelta

from ctypes import wintypes
from typing import Optional, Any
from logging.handlers import RotatingFileHandler


# =========================
# Diretórios (recursos x saída)
# =========================
def _can_write_in_dir(d: str) -> bool:
    """Realiza probe de escrita criando/apagando um arquivo temporário."""

    try:
        os.makedirs(d, exist_ok=True)
        test_path = os.path.join(d, ".__lite2_write_test.tmp")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return True
    except Exception:
        return False


def escolher_output_dir(app_name: str = "lite2") -> str:
    """Escolhe saída: exe/script, %LOCALAPPDATA%/<app>, %TEMP%/<app>, cwd."""

    candidates = []

    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        candidates.append(base)
    except Exception:
        pass

    lad = os.environ.get("LOCALAPPDATA")
    if lad:
        candidates.append(os.path.join(lad, app_name))

    candidates.append(os.path.join(tempfile.gettempdir(), app_name))
    candidates.append(os.getcwd())

    for candidate in candidates:
        if _can_write_in_dir(candidate):
            return candidate

    return os.getcwd()


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




RANDOM_INTERVAL_HOURS = 7
RANDOM_SILENCE_PERIOD_MIN = 55

VOLUMES = {"beep_l2": 0.07, "beep_l3": 0.09, "beep_l4": 0.55, "beep_l5": 0.95, "voz": 100, "beep_fallback": 0.07}

FATOR_CORRECAO_PITCH = FATOR_CORRECAO_ROLL = 0.74
AA_PITCH, AA_ROLL = 0.08, -0.08
NIVELADA_POS, NIVELADA_NEG = 0.34, -0.34

L2_LEVELS = [0.5, -0.5, 0.5, -0.5]
L3_LEVELS = [0.9, -0.9, 0.9, -0.9]

OFFSET_L4 = 0.45
L4_LEVELS = [
    L3_LEVELS[0] + OFFSET_L4,
    L3_LEVELS[1] - OFFSET_L4,
    L3_LEVELS[2] + OFFSET_L4,
    L3_LEVELS[3] - OFFSET_L4,

]

OFFSET_L5 = 0.45
L5_LEVELS = [
    L4_LEVELS[0] + OFFSET_L5,
    L4_LEVELS[1] - OFFSET_L5,
    L4_LEVELS[2] + OFFSET_L5,
    L4_LEVELS[3] - OFFSET_L5,
    
]

JANELA_WIND_SEC, TOP_N_WIND = 120, 4
LOG_RETENCAO_HRS, VENTO_ALARME_CHECK_INTERVAL_MIN = 36, 15
VENTO_ALARME_THRESHOLD, VENTO_REARME_MIN = 23.0, 90.0
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

from pathlib import Path
import os
import sys

APP_NAME = "Lite2"

# =========================
# Diretórios (recursos x saída)
# =========================
IS_FROZEN = bool(getattr(sys, "frozen", False))

# Onde está o script/exe (bom para localizar recursos quando não frozen)
BASE_DIR = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))

# Onde estão os recursos empacotados (PyInstaller usa _MEIPASS)
RESOURCE_ROOT = getattr(sys, "_MEIPASS", BASE_DIR) if IS_FROZEN else BASE_DIR
AUDIO_DIR = os.path.join(RESOURCE_ROOT, "audioss")

def _app_home_dir() -> Path:
    """
    Retorna um diretório gravável e estável fora do OneDrive.
    Permite override via variável de ambiente LITE2_HOME.
    """
    forced = os.environ.get("LITE2_HOME")
    if forced:
        return Path(forced)

    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")

    return Path(base) / APP_NAME

APP_HOME = _app_home_dir()
OUTPUT_DIR = str((APP_HOME / "runtime").resolve())
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


FILES = {
    # ÚNICO TXT (eventos + snapshots + logging padrão)
    "events": os.path.join(OUTPUT_DIR, "lite2_events.log"),
    # Alias para compatibilidade temporária (se ainda existir código usando FILES["log"])
    "log": os.path.join(OUTPUT_DIR, "lite2_events.log"),
    # HTML gerado
    "html": os.path.join(OUTPUT_DIR, "pitch_roll.html"),
}


def ordered_wind_hosts(preferencia: Optional[str] = None):
    """Retorna a ordem de hosts de vento, priorizando a preferência quando válida."""
    if preferencia and preferencia in WIND_HOSTS_ORDER:
        return [preferencia] + [h for h in WIND_HOSTS_ORDER if h != preferencia]
    return list(WIND_HOSTS_ORDER)


# =========================
# Logging (no arquivo único)
# =========================
_LOGGING_CONFIGURED = False


def _setup_logging() -> logging.Logger:
    """Configura logging (idempotente) no arquivo único e devolve o logger nomeado."""
    global _LOGGING_CONFIGURED

    logger = logging.getLogger("painel")
    if _LOGGING_CONFIGURED:
        return logger

    level_name = os.environ.get("PITCHROLL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    try:
        _apply_log_retention()
        os.makedirs(os.path.dirname(FILES["events"]), exist_ok=True)
        handler = logging.FileHandler(FILES["events"], encoding="utf-8")
    except Exception:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)

    # evita duplicar handlers se recarregar módulo em dev
    if not any(type(h) is type(handler) for h in logger.handlers):
        logger.addHandler(handler)

    _LOGGING_CONFIGURED = True
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


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _apply_log_retention():
    """Mantém apenas as últimas LOG_RETENCAO_HRS horas no arquivo único."""
    logger = logging.getLogger("painel")
    path = FILES["events"]
    cutoff = datetime.now() - timedelta(hours=LOG_RETENCAO_HRS)
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return

        kept = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for li in f:
                ts_str = li.split(";", 1)[0].strip()
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    kept.append(li.rstrip("\n"))
                    continue
                if ts >= cutoff:
                    kept.append(li.rstrip("\n"))

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    except Exception:
        try:
            logger.warning("Falha ao aplicar retenção do log único", exc_info=True)
        except Exception:
            pass


def append_log_line(entry_type: str, *parts: str) -> None:
    """Append seguro no log único (não pode quebrar o monitor)."""
    try:
        path = FILES["events"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        clean_parts = [str(p).strip() for p in parts if p is not None and str(p).strip() != ""]
        line = "; ".join([_now_str(), entry_type.strip().upper()] + clean_parts)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # não pode crashar; usa logger se estiver de pé
        try:
            log.warning("Falha ao escrever no log único", exc_info=True)
        except Exception:
            pass


def _fmt_num(v, nd: int = 1) -> str:
    """Formata números com nd casas; mantém string/int/bool como legíveis."""
    try:
        # bool é int em Python; trate antes
        if isinstance(v, bool):
            return "YES" if v else "NO"
        if v is None:
            return "---"
        if isinstance(v, (int, float)):
            return f"{float(v):.{nd}f}"
        # tenta converter strings numéricas
        fv = float(v)
        return f"{fv:.{nd}f}"
    except Exception:
        # fallback para qualquer coisa (ex: host, texto)
        s = str(v).strip()
        return s if s else "---"


def _kv_line(label: str, **kv) -> str:
    """Monta linha amigável: LABEL | KEY: val | KEY: val ..."""
    items = []
    for k, v in kv.items():
        key = str(k).strip().upper()
        items.append(f"{key}: {_fmt_num(v)}")
    # Espaçamento mais “humano”
    return f"{label.upper():<6} | " + " | ".join(items)


def log_event(event_name: str, **kv) -> None:
    # EVENT com “NAME” destacado e chaves em maiúsculo
    line = _kv_line("EVENT", name=event_name, **kv)
    append_log_line(line)


def log_snapshot(pitch, roll, vento_med, raj, wind_source=None) -> None:
    # SNAP com 1 casa decimal; SRC como texto
    line = _kv_line(
        "SNAP",
        pitch=pitch,
        roll=roll,
        vento=vento_med,
        raj=raj,
        src=wind_source,
    )
    append_log_line(line)



def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if val is None:
            return default

        if isinstance(val, str):
            cleaned = val.strip()
            if cleaned == "":
                return default
            out = float(cleaned)
        else:
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
    h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not h:
        return False
    try:
        return bool(kernel32.SetEvent(h))
    finally:
        kernel32.CloseHandle(h)


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
                log_event("HTTP_FAIL", url=url)
                return None
            time.sleep(0.5)
    return None


# =========================
# Audio
# =========================
audio_ok, CHANNELS, _SND = True, {}, {}
AUDIO_SEQ_LOCK = threading.RLock()
_ACTIVE_AUDIO_SEQ = None


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
# Quando pygame não está disponível, audio_ok fica False para evitar chamadas a atributos
# de pygame.* mais adiante, mantendo o restante da aplicação funcional.


def _any_channel_busy() -> bool:
    for ch in CHANNELS.values():
        try:
            if ch and ch.get_busy():
                return True
        except Exception:
            continue
    return False


def _wait_all_channels_free(timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while _any_channel_busy():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def run_audio_sequence(seq_callable, nome: str = "audio_seq", timeout_s: float = 7.0) -> bool:
    """Executa uma sequência de áudio de forma serializada e atômica."""

    seq_name = nome or getattr(seq_callable, "__name__", "audio_seq")
    start_wait = time.monotonic()
    acquired = AUDIO_SEQ_LOCK.acquire(timeout=timeout_s)
    if not acquired:
        log.warning("AudioSeq %s cancelado: timeout aguardando sequência atual.", seq_name)
        return False

    global _ACTIVE_AUDIO_SEQ
    _ACTIVE_AUDIO_SEQ = seq_name
    log.info("AudioSeq START %s", seq_name)

    try:
        elapsed = time.monotonic() - start_wait
        remaining = max(0.0, timeout_s - elapsed)
        if not _wait_all_channels_free(remaining):
            log.warning("AudioSeq %s cancelado: canais ocupados.", seq_name)
            return False
        seq_callable()
        return True
    finally:
        log.info("AudioSeq END %s", seq_name)
        _ACTIVE_AUDIO_SEQ = None
        AUDIO_SEQ_LOCK.release()


def _carregar_wav(nome_base: str):
    if not audio_ok or pygame is None:
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
    if not audio_ok or canal is None or pygame is None:
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
    if not audio_ok or pygame is None or not CHANNELS.get(canal_nome):
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
    nome = f"l{min(nivel_num, 5)}" if nivel_num >= 2 else "l2"
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

def _audio_file_exists(nome_base: str) -> bool:
    """Evita warning do _carregar_wav quando o arquivo nem existe."""
    try:
        path = os.path.join(AUDIO_DIR, f"{nome_base}.wav")
        return os.path.isfile(path)
    except Exception:
        return False


def _ensure_sound_loaded(nome_base: str):
    """
    Garante que o som está carregado em _SND.
    Só tenta carregar se o arquivo existir (para não poluir o log).
    """
    if _SND.get(nome_base):
        return _SND.get(nome_base)
    if not _audio_file_exists(nome_base):
        return None
    return _carregar_wav(nome_base)


def _pick_sound_key(base_key: str, use_v2: bool) -> str:
    """
    Se use_v2=True tenta <base_key>2 primeiro; se não existir/carregar, cai no base_key.
    """
    if not use_v2:
        return base_key

    key2 = f"{base_key}2"
    if _ensure_sound_loaded(key2):
        return key2

    # fallback para o original
    return base_key



def falar_wavs(direcoes, incluir_atencao: bool, use_v2: bool = False):
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

    # 1) Atenção (normal ou v2)
    if incluir_atencao:
        if _quit_evt and _quit_evt.is_signaled():
            return
        key = _pick_sound_key("atencao", use_v2)
        _tocar_em_canal(key, vol01, "voz")
        time.sleep(0.12)

    if not dirs:
        return

    # 2) Combo (normal ou v2)
    combo = _combo_key(set(dirs))
    if combo:
        combo_key = _pick_sound_key(combo, use_v2)

        # garante load sem warning se arquivo não existir
        if _ensure_sound_loaded(combo_key):
            if _quit_evt and _quit_evt.is_signaled():
                return
            _tocar_em_canal(combo_key, vol01, "voz")
            time.sleep(0.25)
            return

        # fallback: se pediu v2 e não existe, tenta o combo original (se existir)
        if combo_key != combo and _ensure_sound_loaded(combo):
            if _quit_evt and _quit_evt.is_signaled():
                return
            _tocar_em_canal(combo, vol01, "voz")
            time.sleep(0.25)
            return

    # 3) Sem combo: toca individuais (normal ou v2)
    for d in dirs:
        if _quit_evt and _quit_evt.is_signaled():
            return
        base = d.lower()  # "popa", "proa", ...
        key = _pick_sound_key(base, use_v2)

        # se v2 não existir, cai para base automaticamente
        if key != base and not _ensure_sound_loaded(key):
            key = base

        _tocar_em_canal(key, vol01, "voz")
        time.sleep(0.12)

    time.sleep(0.25)



def tocar_alarme_vento():
    def _seq():
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

    return run_audio_sequence(_seq, nome="alarme_vento")


def tocar_random():
    def _seq():
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

    return run_audio_sequence(_seq, nome="random")


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
    "L5_LEVELS",
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
    "run_audio_sequence",
    "audio_ok",
    "CHANNELS",
    "_quit_evt",
    "fmt_or_placeholder",
    "safe_float",
    "clamp",
    "base_argparser",
]
