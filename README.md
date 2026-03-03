# Pokemon-Bot (Ryujinx)

Bot em Python para automatizar Pokémon no **Ryujinx** com:
- captura de tela;
- heurísticas simples de estado (overworld / battle / menu);
- planner opcional com IA (OpenAI Vision) para decidir próximas ações.

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
   - Crie `.env` com:

```env
OPENAI_API_KEY=sua_chave_aqui
```

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
4. Se IA falhar/desligada, usa fallback script + regras simples:
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

1. Crie (ou edite) um arquivo `.env` na raiz do projeto.
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
