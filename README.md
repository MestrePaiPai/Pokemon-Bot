# Pokemon-Bot (Ryujinx)

Bot em Python para automatizar Pokémon no **Ryujinx** com:
- captura de tela;
- heurísticas simples de estado (overworld / battle / menu);
- planner opcional com IA (OpenAI Vision) para decidir próximas ações;
- anti-stuck para detectar tela parada e executar recuperação automática.

> ⚠️ Uso por sua conta e risco. Automação pode violar regras de alguns jogos/serviços.

## Requisitos

- Windows (recomendado para Ryujinx + `pydirectinput`)
- Python 3.9+
- Ryujinx aberto com o jogo Pokémon rodando
- Mapeamento de teclas no Ryujinx compatível com o `config/config.yaml`

## Instalação

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Se aparecer erro de versão do `numpy`, confirme o Python com:

```bash
python --version
```

e atualize o `pip` antes de instalar:

```bash
python -m pip install --upgrade pip
```

## Configuração

1. Copie o arquivo de exemplo:

```bash
copy config\config.example.yaml config\config.yaml
# ou
cp config/config.example.yaml config/config.yaml
```

2. Ajuste `config/config.yaml` para o seu teclado. O exemplo já está alinhado com a imagem enviada:
   - A=Z, B=X, X=C, Y=V
   - LStick: W/A/S/D
   - Triggers: L=E, R=U, ZL=Q, ZR=O

3. (Opcional) IA com OpenAI:
   - Copie `.env.example` para `.env` e preencha sua chave:

```env
OPENAI_API_KEY=sk-...
```

> 🔒 Segurança: nunca publique sua chave no GitHub/chat. O projeto ignora `.env` automaticamente via `.gitignore`.

4. Anti-stuck (recomendado manter ligado):
   - `strategy.anti_stuck_enabled: true`
   - `stuck_diff_threshold`: sensibilidade de detecção
   - `stuck_max_still_frames`: quantos ciclos iguais antes de recuperar
   - `recovery_script`: ações automáticas para destravar menu/tela

## Uso

```bash
python src/pokemon_bot.py --config config/config.yaml --log-level INFO
```

- O bot tenta focar a janela com título contendo `Ryujinx`.
- Loop padrão: 500 ms.
- Pare com `Ctrl + C`.

## Como funciona

1. Captura a tela do monitor definido.
2. Classifica estado por visão computacional leve.
3. Se IA estiver ativa, pede até 3 ações curtas para o modelo.
4. Detecta encravamento por similaridade entre frames e executa `recovery_script` automaticamente.
5. Se IA falhar/desligada, usa fallback script + regras simples:
   - `battle`: confirma com `A`
   - `menu`: volta com `B`
   - `overworld`: script de movimento configurado

## Próximos passos recomendados

- Definir regiões de interesse (ROI) específicas da UI de batalha.
- Treinar classificador de tela (menu/luta/mapa) com dataset.
- Adicionar "anti-stuck" (detecção de repetição de frames).
- Criar perfis por jogo (Scarlet/Violet, Sword/Shield, etc.).

## Troubleshooting

### Erro comum (numpy)

Se aparecer `No matching distribution found for numpy==2.1.3`, você provavelmente está usando um ZIP/snapshot antigo do projeto. Baixe novamente a versão atual e reinstale:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Erro comum (unicodeescape no Windows)

Se aparecer `SyntaxError: (unicode error) 'unicodeescape' codec can't decode ...`, isso acontece quando um caminho Windows com `\` é usado dentro de string Python, por exemplo:

```python
path = "C:\Users\ricar\Downloads\Pokemon"
```

Nesse caso, `\U` é interpretado como início de escape Unicode. Use uma destas opções:

```python
path = r"C:\Users\ricar\Downloads\Pokemon"   # raw string
# ou
path = "C:/Users/ricar/Downloads/Pokemon"
# ou
path = "C:\\Users\\ricar\\Downloads\\Pokemon"
```

No projeto, prefira passar caminhos por argumento (`--config`) em vez de hardcode no código Python.

### Erro comum (OPENAI_API_KEY ausente)

Se aparecer `openai.OpenAIError: The api_key client option must be set...`, o planner com IA está ativo mas sem chave configurada.

Como resolver:

1. Crie (ou edite) um arquivo `.env` na raiz do projeto (você pode copiar de `.env.example`).
2. Adicione sua chave:

```env
OPENAI_API_KEY=sk-...
```

3. Rode o bot novamente.

Se você não quiser usar IA, no `config/config.yaml` defina:

```yaml
strategy:
  use_ai_planner: false
```

Com isso o bot funciona só com as heurísticas/fallback (sem OpenAI).


### Bot encrava com frequência

Se o bot fica preso em menus/animações por muito tempo, ajuste no `config/config.yaml`:

```yaml
strategy:
  anti_stuck_enabled: true
  stuck_diff_threshold: 0.9      # mais sensível
  stuck_max_still_frames: 4      # reage mais rápido
  recovery_script:
    - action: B
      duration_ms: 250
    - action: LStickDown
      duration_ms: 500
    - action: A
      duration_ms: 200
```

Dicas rápidas:
- diminua `stuck_diff_threshold` para detectar travamento mais cedo;
- diminua `stuck_max_still_frames` para recuperar mais agressivamente;
- personalize `recovery_script` para o jogo/cena onde encrava.
