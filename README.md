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
