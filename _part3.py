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


STOP_EVENT = threading.Event()
_LOG_COMPACT_INTERVAL_SEC = 300  # 5 minutos
_LOG_COMPACT_SIZE_BYTES = 512 * 1024
_last_log_compact_ts = time.monotonic()



def ler_ultimo_do_log():
    """Retorna (pitch, roll, rajada) do último registro válido."""
    try:
        if (not os.path.isfile(P1.FILES["log"])) or os.path.getsize(P1.FILES["log"]) == 0:
            return None
        with open(P1.FILES["log"], "r", encoding="utf-8", errors="ignore") as f:
            for li in reversed(f.readlines()):
                m = P1.REGEX["log_values"].match(li.strip())
                if m:
                    p, r, w = m.groups()
                    return float(p), float(r), float(w)
    except Exception:
        P1.log.exception("Erro ao ler último registro do log")
    return None


def salvar_log(p, r, raj):
    """Mantém retenção de LOG_RETENCAO_HRS horas e adiciona a linha atual."""
    global _last_log_compact_ts
    agora = datetime.now()
    linha_atual = f"{agora.strftime('%H:%M %d/%m/%Y')};{float(p):.3f};{float(r):.3f};{float(raj):.2f}"

    def _compactar():
        linhas = []
        try:
            if os.path.exists(P1.FILES["log"]):
                with open(P1.FILES["log"], "r", encoding="utf-8", errors="ignore") as f:
                    for li in f:
                        m = P1.REGEX["log_keep"].match(li)
                        if not m:
                            continue
                        h, d = m.groups()
                        try:
                            ts = datetime.strptime(f"{h} {d}", "%H:%M %d/%m/%Y")
                        except Exception:
                            continue
                        if ts >= agora - timedelta(hours=P1.LOG_RETENCAO_HRS):
                            linhas.append(li.rstrip())
            linhas.append(linha_atual)
            with open(P1.FILES["log"], "w", encoding="utf-8") as f:
                f.write("\n".join(linhas) + "\n")
            return True
        except Exception:
            P1.log.warning("Falha ao compactar log; mantendo append.", exc_info=True)
            return False

    try:
        need_compact = False
        try:
            need_compact = (time.monotonic() - _last_log_compact_ts) >= _LOG_COMPACT_INTERVAL_SEC
            need_compact = need_compact or os.path.getsize(P1.FILES["log"]) > _LOG_COMPACT_SIZE_BYTES
        except Exception:
            need_compact = True

        if need_compact and _compactar():
            _last_log_compact_ts = time.monotonic()
            return

        with open(P1.FILES["log"], "a", encoding="utf-8") as f:
            f.write(linha_atual + "\n")
    except Exception:
        P1.log.exception("Erro ao salvar log")


def encerrar_gracioso():
    """Para áudio e libera recursos do evento/quit."""
    STOP_EVENT.set()
    try:
        if P1.CHANNELS.get("beep"):
            P1.CHANNELS["beep"].stop()
        if P1.CHANNELS.get("voz"):
            P1.CHANNELS["voz"].stop()
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
    try:
        if not os.path.exists(P1.FILES["log"]):
            open(P1.FILES["log"], "w", encoding="utf-8").close()
    except Exception:
        P1.log.exception("Não foi possível preparar arquivo de log")

    def _coletar_merged():
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL)
        d_wind = P2.coletar_wind_com_fallback()
        return P5.merge_dados(d_pr, d_wind)

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

    P5.gerar_html(
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

    while not STOP_EVENT.is_set():
        t0 = time.monotonic()

        if STOP_EVENT.is_set() or (P1._quit_evt and P1._quit_evt.is_signaled()):
            encerrar_gracioso()
            return
        dados = _coletar_merged()
        if not dados:
            P5.gerar_html(0, 0, "amarelo", "amarelo", "⚠ SEM DADOS", 0, "verde", "amarelo", None, None, None, vento_med=None, vento_cor="verde", wind_source=None)
        else:
            est = P4.avaliar_de_json(dados)
            now = time.monotonic()
            P5.gerar_html(
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
            salvar_log(est["pitch_val"], est["roll_val"], est["raj"])
            processar_alarme_pitch_roll(est)
            if (now - P5.alarm_state.ultimo_random) >= (P1.RANDOM_INTERVAL_HOURS * 3600):
                tempo_limite = now - (P1.RANDOM_SILENCE_PERIOD_MIN * 60)
                sem_alarmes = (
                    P5.alarm_state.ultimo_alarme_l2 < tempo_limite
                    and P5.alarm_state.ultimo_alarme_l3 < tempo_limite
                    and P5.alarm_state.ultimo_alarme_l4 < tempo_limite
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


def _main():
    P1.keep_screen_on(True)
    P5.start_control_server(P1.MUTE_CTRL_PORT)
    atexit.register(lambda: P1.keep_screen_on(False))
    ap = P1.base_argparser()
    args = ap.parse_args()

    if args.stop:
        ok = P1.signal_quit()
        msg = "OK, sinal enviado." if ok else "Nenhuma instância encontrada."
        print(msg)
        sys.exit(0)

    ja_existe, _ = P1.obter_mutex()
    try:
        P1._quit_evt = P1.QuitEvent()
        P1._quit_evt.create()
    except Exception:
        P1._quit_evt = None

    if ja_existe:
        ok = P1.signal_quit()
        msg = "Outra instância já está rodando. Enviei sinal para encerrar." if ok else "Outra instância já está rodando; não consegui sinalizar. Use --stop."
        print(msg)
        sys.exit(0)

    try:
        run_monitor()
    finally:
        encerrar_gracioso()


if __name__ == "__main__":
    _main()
