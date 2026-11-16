# Portal de Automações Financeiras Carmel

Projeto isolado contendo exclusivamente o **Portal Web (Flet + FastAPI)** e seus módulos:
- **Borderô (`/bordero`)**: Conferência de pagamentos em aberto, visualização de anexos PDF em memória, persistência do status de conferência em SQLite e exportação Excel.
- **Inventário (`/inventario`)**:
  - Contagem mensal por empresa e almoxarifado (`/inventario`)
  - Impacto financeiro mensal (`/inventario/financeiro`)
  - Plano de ação integrado à API de auditoria com persistência SQLite e exportação Excel e PDF (`/inventario/plano-acao`)
- **Cartões de crédito (`/cartoes`)**: Conferência de faturas XLSX contra lançamentos CMFlex, persistência SQLite das conciliações e encargos, e exportação de conciliação.
- **Cartão Flash (`/flash`)**: Conciliação de despesas corporativas Flash contra `cmflex.historico_cartao_flash`, identificação automática de `PENDENTE DE LANÇAMENTO`, `PENDENTE DE PRESTAÇÃO` e `PRESTADO CONTAS`, visualização de comprovantes fiscais em PDF e geração de planilha Excel e texto de cobrança para e-mail.

## Instalação

```powershell
cd c:\Users\magno.alves\Documents\projetos\painel-carmel-automacoes
uv sync
# ou via pip:
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Configuração

Copie o arquivo `.env.example` para `.env` na raiz do projeto e configure as variáveis necessárias:
- **PostgreSQL (CMFlex)**: Apenas leitura (`DB_HOST`, `DB_PORT`, `DB_USER`, etc.).
- **Persistência SQLite**: As conferências e classificações humanas são mantidas em bancos SQLite locais com WAL mode para garantir que o que já foi conferido permaneça salvo:
  - `BORDERO_ACTION_DB`: Caminho para `bordero.sqlite3`.
  - `CARTOES_ACTION_DB`: Caminho para `cartoes.sqlite3`.
  - `FLASH_ACTION_DB`: Caminho para `flash.sqlite3`.
  - `INVENTARIO_ACTION_DB`: Caminho para `plano-acao.sqlite3`.

## Execução

### Local

```powershell
python main.py
# ou
python -m portal
```

Acesse no navegador: `http://127.0.0.1:8550`

### Docker / Docker Compose

```powershell
docker compose up -d --build
```

O compose configura automaticamente a persistência dos bancos SQLite no volume `portal-data`.

## Testes

```powershell
uv run python -m unittest discover -s tests -v
```
