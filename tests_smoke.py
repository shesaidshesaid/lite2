"""Smoke test mínimo para validar vento/rajada e geração de HTML."""

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


if __name__ == "__main__":
    run_smoke()
