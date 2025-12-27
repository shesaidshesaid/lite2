#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Template HTML interno usado como fallback para o painel."""

HTML_TPL = """<!DOCTYPE html>
<html lang=\"pt-BR\">
<head>
<meta charset=\"UTF-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>Pitch & Roll – Monitoramento</title>

<script>
setTimeout(()=>location.reload(true),{refresh_ms});
(function(){{
    let last = null;
    function tick(){{
        const s = document.createElement('script');
        s.src = 'refresh_token.js?ts=' + Date.now();
        s.onload = function(){{
            try {{
                const cur = window.__REFRESH_TOKEN__;
                if (last !== null && cur !== last) location.reload(true);
                last = cur;
            }} catch(e){{}}
            setTimeout(tick, 1500);
        }};
        s.onerror = function(){{ setTimeout(tick, 1500); }};
        document.head.appendChild(s);
        setTimeout(()=>s.remove(), 2000);
    }}
    tick();
}})();

const STALE_SEC = {stale_sec};
const LAST_EPOCH_MS = {last_epoch_ms};
function stalenessLoop() {{
    const ageSec = Math.floor((Date.now() - LAST_EPOCH_MS) / 1000);
    const ageEl = document.getElementById('stale-age');
    if (ageSec > STALE_SEC) {{
        document.body.classList.add('stale');
        if (ageEl) ageEl.textContent = ageSec;
    }} else {{
        document.body.classList.remove('stale');
    }}
    setTimeout(stalenessLoop, 1000);
}}
setTimeout(stalenessLoop, 500);

const CTRL = 'http://127.0.0.1:{port}';
async function muteL23(mins) {{ try {{ await fetch(CTRL + '/mute?mins=' + mins); }} catch (e) {{}} }}
async function unmuteL23() {{ try {{ await fetch(CTRL + '/unmute'); }} catch (e) {{}} }}

async function pollMuteBadge() {{
    try {{
        const r = await fetch(CTRL + '/mute_status');
        const j = await r.json();
        const el = document.getElementById('mute-badge');
        if (!el) return;
        if (j.muted) {{
            const dt = new Date(j.muted_until * 1000);
            el.textContent = '🔇 até ' + dt.toLocaleTimeString();
            el.style.display = 'inline-block';
        }} else {{
            el.style.display = 'none';
        }}
    }} catch(e){{}}
    setTimeout(pollMuteBadge, 3000);
}}

async function hydrateWindPref() {{
    try {{
        const r = await fetch(CTRL + '/wind_pref');
        const j = await r.json();
        const sel = document.getElementById('wind-pref');
        if (sel) sel.value = (j.host || 'auto');
    }} catch(e){{}}
}}

async function setWindPref(val) {{
    try {{ await fetch(CTRL + '/wind_pref?host=' + encodeURIComponent(val)); }} catch (e) {{}}
    location.reload(true);
}}

setTimeout(pollMuteBadge, 1000);
setTimeout(hydrateWindPref, 800);
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
    --primary-blue: #4460f1;
    --success: #32B643;
    --warning: #FFD700;
    --alert: #F4A300;
    --danger: #F44336;
    --bg-gradient: linear-gradient(135deg, #f2f6ff, #cfd9ff);
    --shadow: 0 4px 14px rgba(0,0,0,.15);
    --border-radius: 0.9rem;
    --z-unit: 1rem;
}}

#stale-overlay {{
    position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,0.88); color: #fff;
    display: none; align-items: center; justify-content: center;
    text-align: center; padding: 5vh 5vw;
}}
#stale-overlay h2 {{ font-size: 4.2rem; margin: 0 0 1rem; letter-spacing: .5px; }}
#stale-overlay p {{ font-size: 1.6rem; opacity: .9; margin: .4rem 0; }}
#stale-overlay .hint {{ font-size: 1.1rem; opacity: .75; margin-top: 1.2rem; }}
body.stale #stale-overlay {{ display: flex; }}
body.stale .container {{ display: none !important; }}

body {{
    font-family: 'Roboto', sans-serif;
    background: var(--bg-gradient);
    min-height: 100vh;
    color: #333;
    padding: 1rem;
}}

.container {{
    display: grid;
    grid-template-areas:
        "status controls wind"
        "main main wind2"
        "main main wind2";
    grid-template-columns: auto auto 1fr;
    grid-template-rows: auto 1fr auto;
    gap: 1.5rem;
    max-width: 1400px;
    margin: 0 auto;
    min-height: calc(100vh - 2rem);
}}

.status-label, .main-status, .main-values span {{
    white-space: pre-line;
    word-break: break-word;
    text-align: center;
}}

.status-indicator {{
    grid-area: status;
    display: flex; align-items: center; gap: 1rem;
    background: rgba(255,255,255,0.9);
    padding: 0.8rem 1.2rem; border-radius: 999px;
    box-shadow: var(--shadow);
    align-self: start;
    transform: scale(1) translateX(calc(-11 * var(--z-unit))) translateY(calc(0 * var(--z-unit)));
}}

.controls {{
    grid-area: controls;
    background: rgba(255,255,255,0.96);
    padding: 1rem; border-radius: var(--border-radius);
    box-shadow: var(--shadow);
    align-self: start;
    transform: scale(1) translateX(calc(-31 * var(--z-unit))) translateY(calc(+30 * var(--z-unit)));
}}

.wind-main {{
    grid-area: wind;
    background: rgba(255,255,255,0.92);
    padding: calc(1.2rem * 0.8) calc(1.2rem * 0.8);
    border-radius: var(--border-radius);
    box-shadow: var(--shadow);
    align-self: start;
    justify-self: end;
    transform: scale(2) translateX(calc(+6 * var(--z-unit))) translateY(calc(0 * var(--z-unit)));
    transform-origin: top right;
}}

.wind-secondary {{
    grid-area: wind2;
    background: rgba(255,255,255,0.92);
    padding: 1.2rem 1.6rem; border-radius: var(--border-radius);
    box-shadow: var(--shadow);
    align-self: start;
    justify-self: end;
    transform: scale(1) translateX(calc(-7 * var(--z-unit))) translateY(calc(13 * var(--z-unit)));
}}

.main-panel {{
    grid-area: main;
    background: #fff;
    padding: 4rem 3rem;
    border-radius: var(--border-radius);
    box-shadow: 0 8px 24px rgba(0,0,0,0.1);
    text-align: center;
    display: flex; flex-direction: column; justify-content: center;
    transform: scale(0.9) translateX(calc(15 * var(--z-unit))) translateY(calc(-10 * var(--z-unit)));
}}

.status-dot {{
    width: 60px; height: 60px; border-radius: 50%;
    box-shadow: inset 0 0 10px rgba(0,0,0,.25);
}}
.status-dot.verde {{ background: var(--success); box-shadow: 0 0 20px rgba(50,182,67,.6), inset 0 0 10px rgba(0,0,0,.25); }}
.status-dot.laranja {{ background: var(--alert); box-shadow: 0 0 20px rgba(244,163,0,.6), inset 0 0 10px rgba(0,0,0,.25); }}
.status-dot.amarelo {{ background: var(--warning); box-shadow: 0 0 20px rgba(255,215,0,.6), inset 0 0 10px rgba(0,0,0,.25); }}
.status-dot.vermelho {{ background: var(--danger); box-shadow: 0 0 20px rgba(244,67,54,.7), inset 0 0 10px rgba(0,0,0,.25); }}

.status-label {{ font-size: 1.2rem; color: #444; font-weight: 700; letter-spacing: .5px; }}

.controls {{ display: flex; flex-direction: column; gap: 0.6rem; min-width: 200px; }}
.btn {{
    font: 600 0.95rem/1.1 'Roboto',sans-serif;
    padding: 0.5rem 1rem; border-radius: 0.6rem; border: 0;
    background: #e8eefc; cursor: pointer;
    box-shadow: 0 2px 6px rgba(0,0,0,.08);
}}
.btn:hover {{ filter: brightness(0.98); }}
.mute-badge {{
    background: #ffe9a8; color: #6b5600;
    padding: 0.4rem 0.8rem; border-radius: 0.5rem;
    font-weight: 700; font-size: 0.9rem;
}}
.divider {{ border-top: 1px solid #dde4ff; margin: 0.5rem 0; }}

.wind-data {{ font-size: 1.4rem; line-height: 1.8rem; color: #333; }}
.wind-data > div {{ margin-top: 0.7rem; }}
.vento-label, .rajada-label {{ color: #4DA3FF; font-size: 2.1rem; font-weight: 700; }}
.vento-valor {{ font-size: 3.2rem; font-weight: 800; line-height: 1.05; }}
.rajada-valor {{ font-size: 4.2rem; font-weight: 800; line-height: 1.05; }}

.main-title {{ font-size: 2rem; color: var(--primary-blue); margin-bottom: 0.5rem; white-space: nowrap; }}
.main-status {{ font-size: 6rem; font-weight: 700; margin: 0.6rem 0; }}

.main-values {{
    font-size: calc(1.35rem * 2.5);
    color: #555;
    margin-bottom: 1rem;
    line-height: 1.7;
    transform: translateY(calc(3 * var(--z-unit)));
}}
.main-values strong {{ display: block; }}


.main-time {{
    font-size: 1rem;
    color: #888;
    transform: translateY(calc(3 * var(--z-unit)));
}}

.verde {{ color: var(--success); }}
.amarelo {{ color: var(--warning); }}
.laranja {{ color: var(--alert); }}
.vermelho {{ color: var(--danger); }}
.preto {{ color: #000; }}
.nivelada-preta {{ color: #000; font-weight: 700; }}
.subrotulo {{ display: block; margin-top: 0.25rem; font-size: 1.2rem; font-weight: 400; color: var(--success); }}

@media (max-width: 1200px) {{
    .container {{
        grid-template-areas:
            "status controls"
            "main main"
            "wind wind2";
        grid-template-columns: 1fr 1fr;
    }}
    .wind-main, .wind-secondary {{ justify-self: stretch; }}
}}

@media (max-width: 768px) {{
    .container {{
        grid-template-areas:
            "status"
            "controls"
            "wind"
            "wind2"
            "main";
        grid-template-columns: 1fr;
        gap: 1rem;
    }}
    .main-panel {{ padding: 1.5rem 2rem; }}
    .main-status {{ font-size: 4rem; }}
    .vento-valor {{ font-size: 2.5rem; }}
    .rajada-valor {{ font-size: 3rem; }}
}}
</style>
</head>

<body>
<div id="stale-overlay">
    <div>
        <h2>⚠ DADOS DESATUALIZADOS</h2>
        <p>Última atualização: <strong>{hora}</strong></p>
        <p>Idade dos dados: <strong><span id="stale-age">--</span>s</strong></p>
        <p class="hint">Aguarde o sistema retomar ou feche esta janela.</p>
    </div>
</div>

<div class="container">
    <div class="status-indicator">
        <div class="status-dot {status_cor}"></div>
        <div class="status-label">STATUS</div>
    </div>

    <div class="controls">
        <button class="btn" onclick="muteL23(360)">Silenciar (6 horas)</button>
        <button class="btn" onclick="unmuteL23()">Reativar som</button>
        <span id="mute-badge" class="mute-badge" style="display:none"></span>

        <div class="divider"></div>
        <label style="font-size:0.85rem; color:#555;">Fonte do vento (prioritária)</label>
        <select id="wind-pref" class="btn" onchange="setWindPref(this.value)">
            <option value="auto">Automática (fallback)</option>
            <option value="smp18ocn01">smp18ocn01</option>
            <option value="smp19ocn02">smp19ocn02</option>
            <option value="smp35ocn01">smp35ocn01</option>
            <option value="smp53ocn01">smp53ocn01</option>
        </select>
    </div>

    <div class="wind-main">
        <div class="wind-data">
            <div><span class="vento-label">Vento</span>:
                <strong class="{vento_cor}"><span class="vento-valor">{vento_med_txt}</span> nós</strong>
            </div>
            <div><span class="rajada-label">Rajada</span>:
                <strong class="{rajada_cor}"><span class="rajada-valor">{rajada_txt}</span> nós</strong>
            </div>
        </div>
    </div>

    <div class="wind-secondary">
        <div class="wind-data">
            <div>Dir. vento (ajustado): <strong>{wdir_aj}° ({wdir_lbl})</strong></div>
            <div>Barômetro: <strong>{barometro} hPa</strong></div>
        </div>
    </div>

    <div class="main-panel">
        <h1 class="main-title">⚓ Monitoramento de Pitch & Roll</h1>
        <div class="main-status">{rot}</div>
        <div class="main-values">
            <strong><span class="{pitch_cor}">Pitch: {pitch_txt}</span></strong>
            <strong><span class="{roll_cor}">Roll: {roll_txt}</span></strong>

        </div>
        <div class="main-time">🕒 Atualizado em: {hora}</div>
    </div>
</div>
</body>
</html>
"""

__all__ = ["HTML_TPL"]
