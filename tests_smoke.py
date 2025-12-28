"""Smoke test mínimo para validar vento/rajada, HTML e serialização de áudio."""

import threading
import time
from pathlib import Path

import _part1 as P1
import _part4 as P4
import _part5 as P5


def run_smoke():
    fixture = {
        "ptchwnd": [0.1, -0.1, 0.2],
        "rollwnd": [0.05, -0.2, 0.15],
        "windspdmean": {"med. 2 min": 12.3},
        "gustspdmax": {"instantaneo op.": 18.5},
        "_wind_source": "fixture",
    }

    estado = P4.avaliar_de_json(fixture)
    P5.gerar_html(
        estado["pitch_val"],
        estado["roll_val"],
        estado["pitch_cor"],
        estado["roll_cor"],
        estado["rot"],
        estado["raj"],
        estado["raj_cor"],
        estado["status_cor"],
        estado.get("wdir_adj"),
        estado.get("barometro"),
        estado.get("wdir_lbl"),
        estado.get("vento_med"),
        estado.get("vento_cor", "verde"),
        estado.get("wind_source"),
    )

    html_path = P1.FILES.get("html")
    if not html_path:
        raise SystemExit("Arquivo HTML não definido em P1.FILES")

    html_text = Path(html_path).read_text(encoding="utf-8")
    assert "12.3" in html_text, "Vento médio não encontrado no HTML"
    assert "18.50" in html_text, "Rajada não encontrada no HTML"
    print("Smoke test OK ->", html_path)


def run_smoke_audio_serialization():
    """Valida serialização de áudio sem reproduzir arquivos reais."""

    eventos = []
    tocando = {"flag": False}

    def _sequencia(nome, dur=0.2):
        def _inner():
            if tocando["flag"]:
                raise AssertionError(f"Sobreposição detectada em {nome}")
            tocando["flag"] = True
            eventos.append(f"{nome}-start")
            time.sleep(dur)
            eventos.append(f"{nome}-end")
            tocando["flag"] = False

        return _inner

    t_pitch = threading.Thread(
        target=lambda: P1.run_audio_sequence(_sequencia("pitch_roll"), nome="pitch_roll")
    )
    t_vento = threading.Thread(
        target=lambda: P1.run_audio_sequence(_sequencia("vento"), nome="vento")
    )

    t_pitch.start()
    time.sleep(0.05)
    t_vento.start()
    t_pitch.join()
    t_vento.join()

    assert eventos == [
        "pitch_roll-start",
        "pitch_roll-end",
        "vento-start",
        "vento-end",
    ], f"Sequência inesperada: {eventos}"
    print("Smoke serialização OK ->", eventos)


if __name__ == "__main__":
    run_smoke()
    run_smoke_audio_serialization()
