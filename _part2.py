#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, math, threading, json, webbrowser
from datetime import datetime
from pathlib import Path
from heapq import nlargest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from string import Template

import _part1 as P1

# =========================================================
# Wind coletor com fallback (depende de P1.coletar_json)
# =========================================================
def _only_finite(seq):
    result = []
    for x in (seq or []):
        try:
            v = float(x)
            if math.isfinite(v):
                result.append(v)
        except (TypeError, ValueError):
            continue
    return result

def coletar_wind_com_fallback(tentativas=1, timeout=10):
    ordem = ([P1.WIND_PREF] + [h for h in P1.WIND_HOSTS_ORDER if h != P1.WIND_PREF]
             if P1.WIND_PREF and P1.WIND_PREF in P1.WIND_HOSTS_ORDER else P1.WIND_HOSTS_ORDER)

    for host in ordem:
        d = P1.coletar_json(f"http://{host}:8509{P1.GET_PATH}", tentativas, timeout)
        if not d:
            continue

        serie = _only_finite(d.get("windwnd", []))
        if not serie:
            continue

        try:
            vm, rj = vento_medio(d), rajada(d)
            if vm and rj and float(vm) > 0 and float(rj) > 0:
                d["_wind_source"] = host
                P1.log.info("Usando vento de %s (vm=%s, raj=%s).", host, vm, rj)
                return d
        except Exception:
            continue

    return None

# =========================================================
# Pitch/Roll math (originais)
# =========================================================
def _soma_max_min_param(arr, n, aa, fator):
    arr = _only_finite(arr)
    if not arr:
        return 0.0
    janela = arr[-n:] if n and n > 0 else arr
    return (max(janela) + min(janela) + aa) * fator if janela else 0.0

def soma_max_min_pitch(arr, n=None):
    return _soma_max_min_param(arr, P1.HTML_WIN_PITCH if n is None else n, P1.AA_PITCH, P1.FATOR_CORRECAO_PITCH)

def soma_max_min_roll(arr, n=None):
    return _soma_max_min_param(arr, P1.HTML_WIN_ROLL if n is None else n, P1.AA_ROLL, P1.FATOR_CORRECAO_ROLL)

def rajada(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return 0.0
    tail = w[-max(P1.JANELA_WIND_SEC, P1.TOP_N_WIND):]
    top = nlargest(min(P1.TOP_N_WIND, len(tail)), tail)
    return (sum(top) / len(top)) if top else 0.0

def vento_medio(d):
    w = _only_finite(d.get("windwnd", []))
    if not w:
        return None
    tail = w[-120:] if len(w) >= 120 else w
    return (sum(tail) / len(tail)) if tail else None

def _valor_auxiliar(d, chave_imediata, chave_dict, fallback_fn):
    try:
        v = d.get(chave_imediata, None)
        if v is not None and math.isfinite(float(v)):
            return float(v)
    except Exception:
        pass

    try:
        spl = d.get("windsplv") or "med. 2 min"
        m = d.get(chave_dict)
        if isinstance(m, dict) and m.get(spl) is not None:
            v = float(m[spl])
            return v if math.isfinite(v) else fallback_fn(d)
    except Exception:
        pass

    return fallback_fn(d)

def vento_medio_ui_aux(d):
    return _valor_auxiliar(d, "windspdauxmeanv", "windspdauxmean", vento_medio)

def rajada_ui_aux(d):
    return _valor_auxiliar(d, "windspdauxmaxv", "windspdauxmax", rajada)

_ROSA16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

def rosa_16_pontos(graus):
    if graus is None:
        return None
    q = graus / 22.5
    idx = int(math.floor(q + 0.5 + 1e-12)) % 16
    return _ROSA16[idx]

def _dir_vento_media(d):
    spl = d.get("windsplv") or "med. 2 min"
    wm = d.get("winddirmean")

    if isinstance(wm, dict) and wm.get(spl) is not None:
        try:
            return float(wm[spl])
        except Exception:
            pass

    if d.get("winddirmeanv") is not None:
        try:
            return float(d["winddirmeanv"])
        except Exception:
            pass

    return None

def dir_vento_ajustada(d):
    base = _dir_vento_media(d)
    return (float(base) - 23.0) % 360.0 if base is not None else None

def barometro_hpa(d):
    try:
        for key in ["airpresslmeanv", "airpresmeanv"]:
            if d.get(key) is not None:
                return float(d[key])

        spl = d.get("windsplv") or "med. 2 min"
        for key in ["airpresslmean", "airpresmean"]:
            val = d.get(key)
            if isinstance(val, dict) and val.get(spl) is not None:
                return float(val[spl])
    except Exception:
        pass
    return None

def cor_raj(v):
    if v is None:
        return 'verde'
    try:
        vv = float(v)
    except Exception:
        return 'verde'

    if vv > 29.9:
        return 'vermelho'
    elif vv > 24.9:
        return 'laranja'
    elif vv > 20.9:
        return 'amarelo'
    else:
        return 'verde'

def classif2(v, n4, n3, n2, niv_n, niv_p, p2, p3, p4, nomes):
    if v >= p4: return nomes[0], 'vermelho', None, 4
    if v >= p3: return nomes[0], 'vermelho', None, 3
    if v >= p2: return nomes[0], 'laranja', None, 2
    if v <= n4: return nomes[1], 'vermelho', None, 4
    if v <= n3: return nomes[1], 'vermelho', None, 3
    if v <= n2: return nomes[1], 'laranja', None, 2
    if niv_n <= v <= niv_p: return 'NIVELADA', 'verde', None, 0
    return 'NIVELADA_HINT', 'verde', (nomes[0] if v > niv_p else nomes[1]), 1

def pior_cor(*cores):
    if 'vermelho' in cores: return 'vermelho'
    if 'laranja' in cores: return 'laranja'
    if 'amarelo' in cores: return 'amarelo'
    return 'verde'

def _montar_rotulo_e_status(pitch_val, roll_val, pitch_rot, pitch_cor, pitch_hint, pitch_nivel,
                           roll_rot, roll_cor, roll_hint, roll_nivel):
    ha_alarme = (pitch_nivel >= 2) or (roll_nivel >= 2)

    if ha_alarme:
        partes = []
        if pitch_nivel >= 2 and pitch_rot != "NIVELADA":
            partes.append(f'<span class="{pitch_cor}">{pitch_rot.replace(" ", "<br>")}</span>')
        if roll_nivel >= 2 and roll_rot != "NIVELADA":
            partes.append(f'<span class="{roll_cor}">{roll_rot.replace(" ", "<br>")}</span>')
        if pitch_nivel >= 2 and roll_nivel == 1 and roll_hint:
            partes.append(f'<span class="preto">{roll_hint.replace(" ", "<br>")}</span>')
        if roll_nivel >= 2 and pitch_nivel == 1 and pitch_hint:
            partes.append(f'<span class="preto">{pitch_hint.replace(" ", "<br>")}</span>')

        rot = '<br>'.join(partes) if partes else '<span class="verde">NIVELADA</span>'
    else:
        hints = [h.replace(" ", "<br>") for h in [pitch_hint, roll_hint] if h]
        if hints:
            rot = (
                f'<span class="nivelada-preta">NIVELADA</span>'
                f'<span class="subrotulo">({"<br>".join(hints)})</span>'
            )
        else:
            rot = '<span class="verde">NIVELADA</span>'

    status_cor = pior_cor(pitch_cor, roll_cor)
    return rot, status_cor

def avaliar_por_valores(pitch_val, roll_val, raj_val):
    pitch_rot, pitch_cor, pitch_hint, pitch_nivel = classif2(
        pitch_val, P1.L4_LEVELS[1], P1.L3_LEVELS[1], P1.L2_LEVELS[1],
        P1.NIVELADA_NEG, P1.NIVELADA_POS, P1.L2_LEVELS[0], P1.L3_LEVELS[0], P1.L4_LEVELS[0], ("PROA", "POPA")
    )

    roll_rot, roll_cor, roll_hint, roll_nivel = classif2(
        roll_val, P1.L4_LEVELS[3], P1.L3_LEVELS[3], P1.L2_LEVELS[3],
        P1.NIVELADA_NEG, P1.NIVELADA_POS, P1.L2_LEVELS[2], P1.L3_LEVELS[2], P1.L4_LEVELS[2], ("BORESTE", "BOMBORDO")
    )

    rot, status_cor = _montar_rotulo_e_status(
        pitch_val, roll_val, pitch_rot, pitch_cor, pitch_hint, pitch_nivel,
        roll_rot, roll_cor, roll_hint, roll_nivel
    )

    return {
        "pitch_val": pitch_val, "roll_val": roll_val,
        "pitch_rot": pitch_rot, "pitch_cor": pitch_cor, "pitch_hint": pitch_hint, "pitch_nivel": pitch_nivel,
        "roll_rot": roll_rot, "roll_cor": roll_cor, "roll_hint": roll_hint, "roll_nivel": roll_nivel,
        "rot": rot, "status_cor": status_cor, "raj": raj_val, "raj_cor": cor_raj(raj_val)
    }

def avaliar_de_json(dados: dict):
    pitch_val = soma_max_min_pitch(dados.get("ptchwnd", []), P1.HTML_WIN_PITCH)
    roll_val = soma_max_min_roll(dados.get("rollwnd", []), P1.HTML_WIN_ROLL)

    src = (dados.get("_wind_source") or "").lower()
    if src == "smp53ocn01":
        vento_val = vento_medio_ui_aux(dados)
        raj_val = rajada_ui_aux(dados)
    else:
        vento_val = vento_medio(dados)
        raj_val = rajada(dados)

    out = avaliar_por_valores(pitch_val, roll_val, raj_val)

    wdir_adj = dir_vento_ajustada(dados)
    out.update({
        "wdir_adj": wdir_adj,
        "wdir_lbl": rosa_16_pontos(wdir_adj) if wdir_adj is not None else None,
        "barometro": barometro_hpa(dados),
        "vento_med": vento_val,
        "vento_cor": cor_raj(vento_val)
    })
    return out

# =========================================================
# Alarm State (originais)
# =========================================================
class AlarmState:
    def __init__(self):
        self.historico_niveis = []
        self.nivel_anterior = 0
        self.ultimo_alarme_l2 = 0.0
        self.ultimo_alarme_l3 = 0.0
        self.ultimo_alarme_l4 = 0.0
        self.ultimo_l3_inibe_l2 = 0.0
        self.ultimo_l4_inibe_l23 = 0.0
        self.mudancas_recentes = []
        self.auto_mute_until = 0.0
        self.ciclos_estaveis = 0
        self.ultimo_random = 0.0

    def nivel_combinado(self, est):
        return max(est.get("pitch_nivel", 0), est.get("roll_nivel", 0))

    def detectar_direcao(self, nivel_atual):
        if nivel_atual > self.nivel_anterior:
            return "SUBINDO"
        elif nivel_atual < self.nivel_anterior:
            return "DESCENDO"
        else:
            return "ESTAVEL"

    def eh_alarme_imediato(self, nivel_atual):
        direcao = self.detectar_direcao(nivel_atual)
        if direcao == "SUBINDO" and nivel_atual >= 2:
            return True
        return False

    def verificar_cooldown(self, nivel):
        agora = time.monotonic()

        if nivel <= 2:
            if (agora - self.ultimo_alarme_l2) < (P1.COOLDOWN_L2_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l3) < (P1.COOLDOWN_L3_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True

        if nivel <= 3:
            if (agora - self.ultimo_alarme_l3) < (P1.COOLDOWN_L3_MIN * 60):
                return True
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True

        if nivel <= 4:
            if (agora - self.ultimo_alarme_l4) < (P1.COOLDOWN_L4_MIN * 60):
                return True

        return False

    def verificar_inibicao(self, nivel):
        agora = time.monotonic()

        if nivel == 2:
            inibido_l3 = (agora - self.ultimo_l3_inibe_l2) < (P1.INIBICAO_L3_SOBRE_L2_MIN * 60)
            inibido_l4 = (agora - self.ultimo_l4_inibe_l23) < (P1.INIBICAO_L4_SOBRE_L23_MIN * 60)
            return inibido_l3 or inibido_l4
        elif nivel == 3:
            return (agora - self.ultimo_l4_inibe_l23) < (P1.INIBICAO_L4_SOBRE_L23_MIN * 60)

        return False

    def verificar_auto_mute(self):
        return time.monotonic() < self.auto_mute_until

    def detectar_oscilacao(self, nivel_atual):
        agora = time.monotonic()

        if nivel_atual != self.nivel_anterior:
            self.mudancas_recentes.append((agora, nivel_atual))

        janela_s = P1.OSCILACAO_JANELA_MIN * 60
        self.mudancas_recentes = [(t, n) for t, n in self.mudancas_recentes if (agora - t) <= janela_s]

        if len(self.mudancas_recentes) >= P1.OSCILACAO_MAX_MUDANCAS:
            self.auto_mute_until = agora + (P1.AUTO_MUTE_OSCILACAO_MIN * 60)
            self.mudancas_recentes.clear()
            return True

        return False

    def atualizar_historico(self, nivel_atual):
        agora = time.monotonic()

        self.historico_niveis.append((agora, nivel_atual))

        if len(self.historico_niveis) > 10:
            self.historico_niveis = self.historico_niveis[-10:]

        if nivel_atual <= 1:
            self.ciclos_estaveis += 1
            if self.ciclos_estaveis >= P1.RESET_ESTAVEL_CICLOS:
                self._reset_estado()
        else:
            self.ciclos_estaveis = 0

        self.nivel_anterior = nivel_atual

    def _reset_estado(self):
        self.historico_niveis.clear()
        self.mudancas_recentes.clear()
        self.ciclos_estaveis = 0

    def registrar_alarme_tocado(self, nivel):
        agora = time.monotonic()

        if nivel == 2:
            self.ultimo_alarme_l2 = agora
        elif nivel == 3:
            self.ultimo_alarme_l3 = agora
            self.ultimo_l3_inibe_l2 = agora
        elif nivel == 4:
            self.ultimo_alarme_l4 = agora
            self.ultimo_l4_inibe_l23 = agora

    def deve_tocar_alarme(self, est):
        nivel_atual = self.nivel_combinado(est)

        if nivel_atual <= 1:
            self.atualizar_historico(nivel_atual)
            return False, None, "Nível baixo (L0/L1)"

        if self.verificar_auto_mute():
            self.atualizar_historico(nivel_atual)
            return False, None, "Auto-mute ativo (oscilação)"

        if self.detectar_oscilacao(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, "Auto-mute ativado (oscilação detectada)"

        if self.verificar_cooldown(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, f"Cooldown L{nivel_atual} ativo"

        if self.verificar_inibicao(nivel_atual):
            self.atualizar_historico(nivel_atual)
            return False, None, f"L{nivel_atual} inibido por nível superior"

        eh_imediato = self.eh_alarme_imediato(nivel_atual)
        motivo = f"IMEDIATO (escalada {self.nivel_anterior}→{nivel_atual})" if eh_imediato else f"Normal L{nivel_atual}"

        self.atualizar_historico(nivel_atual)
        return True, motivo, None

alarm_state = AlarmState()

# =========================================================
# Mute L2/L3 state + lock (originais)
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
# Merge + refresh_token + refresh html now (originais)
# =========================================================
def _merge_dados(d_pr, d_wind):
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

    return dados

def _gravar_refresh_token():
    try:
        tok = str(int(time.time() * 1000))
        with open(P1.FILES['refresh_js'], "w", encoding="utf-8") as f:
            f.write(f"window.__REFRESH_TOKEN__='{tok}';")
        return tok
    except Exception:
        return None

def _refresh_html_now():
    try:
        d_pr = P1.coletar_json(P1.URL_SMP_PITCH_ROLL, tentativas=1, timeout=5)
        d_wind = coletar_wind_com_fallback(tentativas=1, timeout=5)

        if not d_pr and not d_wind:
            _gravar_refresh_token()
            return False

        dados = _merge_dados(d_pr, d_wind)
        est = avaliar_de_json(dados)

        gerar_html(
            est["pitch_val"], est["roll_val"], est["pitch_cor"], est["roll_cor"],
            est["rot"], est["raj"], est["raj_cor"], est["status_cor"],
            est.get("wdir_adj"), est.get("barometro"), est.get("wdir_lbl"),
            vento_med=est.get("vento_med"), vento_cor=est.get("vento_cor", "verde")
        )

        _gravar_refresh_token()
        return True
    except Exception:
        _gravar_refresh_token()
        return False

# =========================================================
# Control server (originais, com WIND_PREF em P1)
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
                self._reply_json({"muted": is_muted_L23(), "muted_until": MUTE_L23_UNTIL_TS})

            elif path == "/wind_pref":
                hv = qs.get("host", [None])[0]
                if hv is None:
                    self._reply_json({"ok": True, "host": (P1.WIND_PREF or "auto")})
                    return

                v = (hv or "").strip().lower()
                host_set = set(P1.WIND_HOSTS_ORDER)

                if v in ("", "auto", "none", "null"):
                    P1.WIND_PREF = None
                    ok = _refresh_html_now()
                    self._reply_json({"ok": ok, "host": "auto"})
                elif v in host_set:
                    P1.WIND_PREF = v
                    ok = _refresh_html_now()
                    self._reply_json({"ok": ok, "host": v})
                else:
                    self._reply_json({"ok": False, "error": "host inválido"}, code=400)

            elif path == "/wind_pref_status":
                self._reply_json({"ok": True, "pref": (P1.WIND_PREF or "auto"), "options": P1.WIND_HOSTS_ORDER})

            else:
                self._reply_json({"error": "not found"}, code=404)

        except Exception as e:
            self._reply_json({"ok": False, "error": str(e)}, code=500)

def start_control_server(port: int = P1.MUTE_CTRL_PORT):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _ControlHandler)
    except Exception:
        return None

    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    return srv

# =========================================================
# HTML rendering: template externo ($...) OU fallback HTML_TPL
# =========================================================
HTML_TPL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
                <strong class="{rajada_cor}"><span class="rajada-valor">{rajada:.2f}</span> nós</strong>
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
            <strong><span class="{pitch_cor}">Pitch: {pitch:.1f}</span></strong>
            <strong><span class="{roll_cor}">Roll: {roll:.1f}</span></strong>
        </div>
        <div class="main-time">🕒 Atualizado em: {hora}</div>
    </div>
</div>
</body>
</html>
"""

def _fmt_or_dash(val, fmt):
    try:
        return fmt.format(float(val))
    except Exception:
        return "---"

def gerar_html(p, r, pc, rc, rot, raj, rcor, status, wdir_aj, barometro, wdir_lbl,
              vento_med=None, vento_cor="verde"):

    dt = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    src = None
    try:
        log_path = os.path.join(P1.BASE_DIR, "monitor.log")
        with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
            tail = lf.readlines()[-800:]
        for li in reversed(tail):
            m = P1.REGEX['wind_src'].search(li)
            if m:
                src = m.group(1)
                break
    except Exception:
        src = None

    dt_show = dt if not src else f"""{dt} <span style="font-size:.85em;opacity:.75">(vento: {src})</span>"""

    wdir_txt = _fmt_or_dash(wdir_aj, "{:.1f}")
    baro_txt = _fmt_or_dash(barometro, "{:.2f}")
    lbl_txt = "---" if (wdir_lbl is None or str(wdir_lbl).strip() == "") else str(wdir_lbl)

    vento_txt = _fmt_or_dash(vento_med, "{:.1f}")

    last_epoch_ms = int(time.time() * 1000)

    # --- preferir template externo se existir e estiver no padrão $... ---
    template_path = Path(P1.FILES.get("html_template", ""))
    if template_path and template_path.exists():
        try:
            txt = template_path.read_text(encoding="utf-8")
            # Critério simples: se contém pelo menos $refresh_ms, tratamos como Template
            if "$refresh_ms" in txt or "$stale_sec" in txt or "$last_epoch_ms" in txt:
                tpl = Template(txt)
                html = tpl.substitute(
                    refresh_ms=P1.HTML_REFRESH_SEC * 1000,
                    stale_sec=P1.HTML_STALE_MAX_AGE_SEC,
                    last_epoch_ms=last_epoch_ms,
                    port=P1.MUTE_CTRL_PORT,

                    hora=dt_show,
                    status_cor=status,
                    rot=rot,

                    pitch=_fmt_or_dash(p, "{:.1f}"),
                    roll=_fmt_or_dash(r, "{:.1f}"),
                    pitch_cor=pc,
                    roll_cor=rc,

                    rajada=_fmt_or_dash(raj, "{:.2f}"),
                    rajada_cor=rcor,

                    vento_med_txt=vento_txt,
                    vento_cor=vento_cor,

                    wdir_aj=wdir_txt,
                    wdir_lbl=lbl_txt,
                    barometro=baro_txt,
                )
                Path(P1.FILES['html']).write_text(html, encoding="utf-8")
                return
        except Exception:
            # se o template externo estiver inválido, cai no fallback original
            pass

    # --- fallback original (HTML_TPL .format com chaves escapadas) ---
    with open(P1.FILES['html'], "w", encoding="utf-8") as f:
        f.write(HTML_TPL.format(
            refresh_ms=P1.HTML_REFRESH_SEC * 1000,
            stale_sec=P1.HTML_STALE_MAX_AGE_SEC,
            last_epoch_ms=last_epoch_ms,
            rot=rot, pitch=p, roll=r, pitch_cor=pc, roll_cor=rc,
            rajada=raj, rajada_cor=rcor,
            vento_med_txt=vento_txt, vento_cor=vento_cor,
            status_cor=status, wdir_aj=wdir_txt, barometro=baro_txt, wdir_lbl=lbl_txt,
            hora=dt_show, port=P1.MUTE_CTRL_PORT,
        ))

def abrir_html_no_navegador():
    try:
        uri = Path(P1.FILES['html']).resolve().as_uri()
        webbrowser.open(uri, new=0, autoraise=True)
    except Exception:
        pass
