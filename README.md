# lite2 – Monitor de Pitch/Roll e Vento

Monitor para pitch/roll com coleta HTTP, alarmes de áudio via pygame e painel HTML.

## Requisitos
- Python 3.9+
- Dependências: `requests`, `pygame`
- Arquivos de áudio na pasta `audioss/`

Instale as dependências com:
```bash
pip install -r requirements.txt
```

## Execução
- Iniciar monitor: `python lite2.py`
- Solicitar parada da instância em execução: `python lite2.py --stop`

## Servidor de controle (localhost)
- Porta padrão: `8765`
- Endpoints:
  - `/mute?mins=360` – silencia alarmes L2/L3 pelo período em minutos
  - `/unmute` – reativa som
  - `/mute_status` – status do mute (`muted`, `muted_until`)
  - `/wind_pref?host=<auto|smp18ocn01|smp19ocn02|smp35ocn01|smp53ocn01>` – define preferência de host ou automático
  - `/wind_pref` – obtém preferência atual

## HTML / Template
- O painel gera `pitch_roll.html` na raiz do projeto.
- Se existir `pitch_roll_template.html` com placeholders `$...`, ele será usado com `Template.substitute`.
- Em caso de erro ou ausência, o HTML interno é usado automaticamente.
- `refresh_token.js` é gravado junto ao HTML para detecção de mudanças.

## Notas
- Compatível com Windows (mutex + quit event para instância única).
- O modo `--stop` envia sinal para a instância ativa encerrar.
- Alarmes de vento, preferências de host e modo mute permanecem inalterados em relação ao comportamento original.
