#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Runtime: loop principal, log e inicialização."""

from __future__ import annotations


import os
import sys
import time
import atexit
from datetime import datetime, timedelta

import _part1 as P1
import _part2 as P2
import _part4 as P4
import _part5 as P5
import threading

from _part5 import ensure_http_shortcut


STOP_EVENT = threading.Event()
SNAP_INTERVAL_SEC = 120     # 2 minutos
RETENCAO_HORAS = 36
_last_snap_ts = 0.0



from typing import Optional, Tuple




def ler_ultimo_do_log() -> Optional[Tuple[float, float, float]]:
    """Retorna (pitch, roll, rajada) do último registro válido (linha SNAP)."""
    try:
        log_path = P1.FILES["log"]
        if (not os.path.isfile(log_path)) or os.path.getsize(log_path) == 0:
            return None

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for li in reversed(f.readlines()):
                parts = [p.strip() for p in li.split(";")]
                if len(parts) < 3 or parts[1].upper() != "SNAP":
                    continue

                valores = {k: v for k, v in (p.split("=", 1) for p in parts[2:] if "=" in p)}

                pitch_s = valores.get("pitch")
                roll_s  = valores.get("roll")
                raj_s   = valores.get("raj")

                # Se faltar algum campo, não tenta converter
                if pitch_s is None or roll_s is None or raj_s is None:
                    continue

                try:
                    return float(pitch_s), float(roll_s), float(raj_s)
                except ValueError:
                    # Campo veio não-numérico (ex: vazio, "None", etc.)
                    continue

    except Exception:
        P1.log.exception("Erro ao ler último registro do log")

    return None



def encerrar_gracioso():
    """Para áudio e libera recursos do evento/quit."""
    STOP_EVENT.set()
    try:
        for nm in ("beep", "voz", "vento"):
            canal = P1.CHANNELS.get(nm)
            if canal:
                canal.stop()
        if P1.audio_ok and P1.pygame is not None:
            P1.pygame.mixer.quit()
    except Exception:
        P1.log.debug("Erro ao encerrar mixer/áudio", exc_info=True)
    try:
        if P1._quit_evt:
            P1._quit_evt.close()
            P1._quit_evt = None
    except Exception:
        P1.log.debug("Erro ao fechar quit event", exc_info=True)


def run_monitor():
    P1.log_event("RUN_START")

    def _coletar_merged():
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL)
        d_wind = P2.coletar_wind_com_fallback()
        return P5.merge_dados(d_pr, d_wind)

    def _render_html(est_local):
        P5.gerar_html(
            est_local["pitch_val"],
            est_local["roll_val"],
            est_local["pitch_cor"],
            est_local["roll_cor"],
            est_local["rot"],
            est_local["raj"],
            est_local["raj_cor"],
            est_local["status_cor"],
            est_local.get("wdir_adj"),
            est_local.get("barometro"),
            est_local.get("wdir_lbl"),
            est_local.get("vento_med"),
            est_local.get("vento_cor", "verde"),
            est_local.get("wind_source"),
        )

    try:
        dados = None
        for _ in range(3):
            if STOP_EVENT.is_set() or (P1._quit_evt and P1._quit_evt.is_signaled()):
                encerrar_gracioso()
                return
            dados = _coletar_merged()
            if dados:
                break
            time.sleep(0.6)

        if dados:
            est = P4.avaliar_de_json(dados)
        else:
            ult = ler_ultimo_do_log()
            if ult:
                p, r, w = ult
                est = P4.avaliar_por_valores(p, r, w)
                est.update({"wdir_adj": None, "wdir_lbl": None, "barometro": None, "vento_med": None, "vento_cor": "verde", "wind_source": None})
            else:
                est = {
                    "pitch_val": 0,
                    "roll_val": 0,
                    "pitch_cor": "amarelo",
                    "roll_cor": "amarelo",
                    "pitch_rot": "NIVELADA",
                    "pitch_hint": None,
                    "pitch_nivel": 0,
                    "roll_rot": "NIVELADA",
                    "roll_hint": None,
                    "roll_nivel": 0,
                    "rot": "⚠ SEM DADOS",
                    "status_cor": "amarelo",
                    "raj": 0,
                    "raj_cor": "verde",
                    "wdir_adj": None,
                    "wdir_lbl": None,
                    "barometro": None,
                    "vento_med": None,
                    "vento_cor": "verde",
                    "wind_source": None,
                }

        _render_html(est)
        P5.abrir_html_no_navegador()

        wind_alarm_state = {
            "last_wind_alarm_ts": 0.0,
            "next_wind_check_ts": time.monotonic() + P1.VENTO_ALARME_CHECK_INTERVAL_MIN * 60.0,
        }

        def verificar_alarme_vento(vento_val_atual, raj_val_atual):
            now = time.monotonic()
            try:
                vento_num = None if (vento_val_atual is None) else float(vento_val_atual)
                raj_num = None if (raj_val_atual is None) else float(raj_val_atual)
            except Exception:
                vento_num = raj_num = None
            vento_acima = (vento_num is not None) and (vento_num > P1.VENTO_ALARME_THRESHOLD)
            rajada_acima = (raj_num is not None) and (raj_num > P1.VENTO_ALARME_THRESHOLD)
            if vento_acima or rajada_acima:
                if (now - wind_alarm_state["last_wind_alarm_ts"]) >= (P1.VENTO_REARME_MIN * 60.0):
                    P1.log_event("ALARM_WIND", vento=vento_num, raj=raj_num, threshold=P1.VENTO_ALARME_THRESHOLD)

                    P1.tocar_alarme_vento()
                    wind_alarm_state["last_wind_alarm_ts"] = now

        wind_alarm_timer = threading.Timer(
            9.0, lambda: verificar_alarme_vento(est.get("vento_med"), est.get("raj"))
        )
        wind_alarm_timer.daemon = True
        wind_alarm_timer.start()

        def processar_alarme_pitch_roll(est_local):
            P5.processar_alarme_pitch_roll(est_local)

        now_boot = time.monotonic()
        if not hasattr(P5.alarm_state, "ultimo_random") or P5.alarm_state.ultimo_random <= 0:
            P5.alarm_state.ultimo_random = now_boot

        global _last_snap_ts
        _last_snap_ts = time.monotonic() - SNAP_INTERVAL_SEC

        while not STOP_EVENT.is_set():
            t0 = time.monotonic()

            if STOP_EVENT.is_set() or (P1._quit_evt and P1._quit_evt.is_signaled()):
                encerrar_gracioso()
                return
            dados = _coletar_merged()
            if not dados:
                _render_html({
                    "pitch_val": 0,
                    "roll_val": 0,
                    "pitch_cor": "amarelo",
                    "roll_cor": "amarelo",
                    "rot": "⚠ SEM DADOS",
                    "raj": 0,
                    "raj_cor": "verde",
                    "status_cor": "amarelo",
                    "wdir_adj": None,
                    "barometro": None,
                    "wdir_lbl": None,
                    "vento_med": None,
                    "vento_cor": "verde",
                    "wind_source": None,
                })
            else:
                est = P4.avaliar_de_json(dados)
                now = time.monotonic()
                _render_html(est)
                if (now - _last_snap_ts) >= SNAP_INTERVAL_SEC:
                    P1.log_snapshot(
                        est.get("pitch_val"),
                        est.get("roll_val"),
                        est.get("vento_med"),
                        est.get("raj"),
                        est.get("wind_source"),
                    )
                    _last_snap_ts = now
                processar_alarme_pitch_roll(est)
                if (now - P5.alarm_state.ultimo_random) >= (P1.RANDOM_INTERVAL_HOURS * 3600):
                    tempo_limite = now - (P1.RANDOM_SILENCE_PERIOD_MIN * 60)
                    sem_alarmes = (
                        P5.alarm_state.ultimo_alarme_l2 < tempo_limite
                        and P5.alarm_state.ultimo_alarme_l3 < tempo_limite
                        and P5.alarm_state.ultimo_alarme_l4 < tempo_limite
                        and P5.alarm_state.ultimo_alarme_l5 < tempo_limite
                    )
                    if sem_alarmes:
                        P1.tocar_random()
                        P5.alarm_state.ultimo_random = now
                if now >= wind_alarm_state["next_wind_check_ts"]:
                    wind_alarm_state["next_wind_check_ts"] = now + P1.VENTO_ALARME_CHECK_INTERVAL_MIN * 60.0
                    verificar_alarme_vento(est.get("vento_med"), est.get("raj"))

            elapsed = time.monotonic() - t0
            rest = max(0.0, P1.COLETA_INTERVAL - elapsed)
            if P1._quit_evt and getattr(P1._quit_evt, "handle", None) and P1.kernel32 is not None:
                res = P1.kernel32.WaitForSingleObject(P1._quit_evt.handle, int(rest * 1000))
                if res == P1.WAIT_OBJECT_0:
                    encerrar_gracioso()
                    return
            else:
                time.sleep(rest)

        if wind_alarm_timer.is_alive():
            wind_alarm_timer.cancel()
    finally:
        P1.log_event("RUN_STOP")


def _main():
    ap = P1.base_argparser()
    args = ap.parse_args()

    if args.stop:
        ok = P1.signal_quit()
        msg = "OK, sinal enviado." if ok else "Nenhuma instância encontrada."
        print(msg)
        sys.exit(0)

    P1.keep_screen_on(True)
    atexit.register(lambda: P1.keep_screen_on(False))

    ja_existe, _ = P1.obter_mutex()

    try:
        P1._quit_evt = P1.QuitEvent()
        P1._quit_evt.create()
    except Exception:
        P1._quit_evt = None

    if ja_existe:
        ok = P1.signal_quit()
        msg = (
            "Outra instância já está rodando. Enviei sinal para encerrar."
            if ok else
            "Outra instância já está rodando; não consegui sinalizar. Use --stop."
        )
        print(msg)
        sys.exit(0)

    # Inicia servidor
    P5.start_control_server(P1.MUTE_CTRL_PORT)

    # Cria atalhos (AGORA, já com FILES e logging prontos)
    P5.ensure_http_shortcut(P1.MUTE_CTRL_PORT)
    P5.ensure_log_shortcut(P1.FILES["events"])

    try:
        P1.log_event("START")
        run_monitor()
    except KeyboardInterrupt:
        P1.log.info("Interrompido por KeyboardInterrupt; encerrando.")
    finally:
        encerrar_gracioso()
        P1.log_event("STOP")

