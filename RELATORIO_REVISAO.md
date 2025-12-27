# Revisão de vento/rajada e alarmes L2/L3/L4

## Etapa A — Arquitetura
- **lite2.py**: apenas chama `_main()` em `_part3`.
- **_part1.py**: constantes globais (limiares L2/L3/L4, janela de vento, portas, hosts), utilidades (`safe_float`, `fmt_or_placeholder`, logging rotativo), inicialização de áudio e helpers Windows (mutex, quit event). Mantém sessão `requests` para HTTP.
- **_part2.py**: matemática de pitch/roll e cadeia de vento/rajada. Calcula rajada e vento médio priorizando campos do PyHMS (`gustspdmaxv`/`gustspdmax[...]` e `windspdmean["med. 2 min"]`/`windspdmeanv`), com fallback antigo via `windwnd`. Também ajusta direção/barômetro e coleta vento com fallback de host.
- **_part3.py**: loop principal. Coleta pitch/roll + vento (`coletar_wind_com_fallback`), avalia (`_part4.avaliar_de_json`), gera HTML, salva log, aciona alarmes (vento simples e pitch/roll via `_part5.processar_alarme_pitch_roll`), controla ritmo de coleta e random voice.
- **_part4.py**: motor de avaliação (classificação L2/L3/L4) e montagem de rótulos/cores. Usa thresholds de `_part1`, rajada para cor de vento, combina info de direção/barômetro.
- **_part5.py**: estado de alarmes (debounce/confirm/silence), servidor HTTP de controle (mute L2/L3, preferência de host), merge de dados, renderização HTML (fallback ou template) e abertura de navegador.

## Etapa B — Cadeia vento/rajada (fim-a-fim)
- **Fonte de rajada**: `_part2.rajada` prioriza `gustspdmaxv` → `gustspdmax["instantaneo op."]` → `gustspdmax["met. 3 sec"]` → fallback antigo por `windwnd` (top N). Chamado por `rajada_ui_aux` e usado em `_part4.avaliar_de_json` para alimentar decisões/HTML.
- **Fonte de vento médio**: `_part2.vento_medio` prioriza `windspdmean["med. 2 min"]` → `windspdmeanv` → fallback `windwnd` (média 120s). Chamado por `vento_medio_ui_aux` em `_part4.avaliar_de_json`.
- **Coleta**: `_part2.coletar_wind_com_fallback` varre hosts em ordem (ou preferência via `/wind_pref`), aceita dados somente se vento médio e rajada são >0 e finitos; registra `_wind_source` e loga host.
- **Uso em decisões**: `_part4.avaliar_de_json` é a única origem para o loop principal e alarmes, portanto as decisões de cor/alarme de vento usam os campos corretos do PyHMS. O alarme de vento simples em `_part3.run_monitor` compara vento médio e rajada com `VENTO_ALARME_THRESHOLD`.
- **Resquícios/risco**: `windwnd` ainda aparece apenas como fallback; `KEYS_WIND` inclui `windspdaux*` que não são usados em parte alguma. Nenhum caminho ativo usa `windwnd` se campos PyHMS vierem preenchidos.

## Etapa C — Alarmes L2/L3/L4 (pitch/roll)
### Thresholds
- Pitch: L2 ±0.50, L3 ±1.10, L4 ±1.45 (offset 0.35 sobre L3). Roll idêntico.
- Histerese implícita: não há debounce por tempo; classificação é instantânea. Reset para nível inferior depende apenas do valor atual (sem retenção de ciclos), porém o estado de alarme sonoro tem lógica de silêncio.

### Máquina de alarme sonoro (`AlarmState`)
- Dispara apenas quando o nível combinado (máx de pitch/roll) **sobe** para ≥L2.
- Confirmação: coleta imediata após 5s e só toca se ainda ≥L2; respeita mute manual para L2/L3 e silêncio ativo.
- Silêncio: após tocar nível N, silencia níveis ≤N por 8 min; L4 ignora mute manual mas respeita silêncio vigente.
- Mute manual: `/mute?mins=X` define `MUTE_L23_UNTIL_TS`; `/unmute` limpa. Aplica-se tanto na triagem quanto na confirmação.

### Tabela resumida (decisão sonora)
- **Entradas**: `pitch_nivel`, `roll_nivel` (0–4), estado mute L2/L3, silêncio ativo, evento de shutdown.
- **Escalonamento**: sobe para nível atual se maior que anterior e não silenciado → agenda confirmação (5s) → toca nível confirmado e reinicia silêncio de 8 min.
- **Desescalonamento/reset**: níveis inferiores apenas atualizam `nivel_anterior`; não tocam som e não limpam silêncio antes do tempo expirar. Oscilações rápidas são amortecidas porque só toca em subida e exige confirmação.

### Alarme de vento simples
- Triggera se vento médio **ou** rajada >21.0 m/s e último alarme foi há ≥76 min; roda a cada 15 min (e uma vez 9s após start). Sem histerese adicional.

## Etapa D — Otimização e limpeza
- **Código morto/não usado**: constantes `INIBICAO_L3_SOBRE_L2_MIN`, `INIBICAO_L4_SOBRE_L23_MIN`, `RESET_ESTAVEL_CICLOS`, `OSCILACAO_MAX_MUDANCAS`, `OSCILACAO_JANELA_MIN`, `AUTO_MUTE_OSCILACAO_MIN` não são referenciadas. Import `deque` em `_part5.py` não é usado. `KEYS_WIND` carrega `windspdaux*` nunca consumidos.
- **Clareza/performance**: `coletar_wind_com_fallback` tenta dois caminhos (UI helpers e funções diretas) com mesmas fontes; pode consolidar em um único cálculo para reduzir duplo parsing/float. Log de falha de coleta é silencioso (falhas ignoradas); adicionar motivos ajudaria troubleshooting. A verificação de vento simples poderia reutilizar valores já numéricos e evitar conversão duplicada.

## Etapa E — Recomendações e passos sugeridos
### Recomendações prioritárias
1. **Garantir logging de fonte de vento** mesmo em falhas de validação (ex.: campos ausentes) para facilitar diagnóstico de hosts ruins.
2. **Remover/limpar código morto**: constantes não usadas, imports e chaves `windspdaux*` em `KEYS_WIND` (após confirmar com stakeholders) para evitar confusão.
3. **Documentar cadeia de vento** diretamente no código (docstrings) e centralizar leitura em `vento_medio`/`rajada` para evitar caminhos paralelos.
4. **Alarme de vento**: opcionalmente alinhar histerese com lógica de pitch/roll (confirmar após 1 coleta extra) para reduzir falsos positivos em spikes únicos.

### Patch/refactor proposto (incremental, sem mudar regra de negócio)
- **_part2.py**: consolidar `coletar_wind_com_fallback` para usar apenas `vento_medio`/`rajada` (eliminando bloco duplicado de validação) e registrar erros explicando por que um host foi ignorado.
- **_part1.py**: remover constantes não referenciadas e chaves `windspdaux*` se não houver integração prevista; adicionar comentário sobre prioridade de campos PyHMS em `KEYS_WIND`.
- **_part5.py**: remover import `deque` não usado; adicionar log quando `_coletar_est_para_confirmacao` não conseguir dados. Avaliar expor estado de silêncio/mute no HTML para depuração.
- **Testes**: criar fixtures JSON do PyHMS (com/sem `gustspdmaxv`, com apenas `gustspdmax["instantaneo op."]`, sem dados → fallback `windwnd`) para validar `vento_medio`/`rajada` e thresholds de cor. Simular sequência de níveis para garantir que `AlarmState` toca apenas na subida e respeita silêncio/mute.

### Testes manuais recomendados
- Enviar payload real do PyHMS com `gustspdmaxv` e `windspdmean["med. 2 min"]`; verificar UI/HTML e alarme de vento (forçar >21 m/s) e origem `wind_source`.
- Usar `/wind_pref` para alternar host válido/inválido e observar logs de seleção/falha.
- Simular oscilações: variar `pitch/roll` para cruzar L2→L3→L4 e voltar, confirmando que o som só toca na subida e silencia por 8 min.
- Validar `/mute` e `/unmute` (L2/L3) enquanto L4 continua tocando.
