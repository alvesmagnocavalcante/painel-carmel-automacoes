# Portal de Automações Financeiras Carmel

Projeto isolado contendo exclusivamente o **Portal Web (Flet + FastAPI)** e seus módulos:
- **Borderô (`/bordero`)**: Conferência de pagamentos em aberto, visualização de anexos PDF em memória e exportação Excel.
- **Inventário (`/inventario`)**:
  - Contagem mensal por empresa e almoxarifado (`/inventario`)
  - Impacto financeiro mensal (`/inventario/financeiro`)
  - Plano de ação integrado à API de auditoria com exportação Excel e PDF (`/inventario/plano-acao`)

## Instalação

```powershell
cd c:\Users\magno\Documents\Projeto\portal-carmel
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Configuração

Copie o arquivo `.env.example` para `.env` na raiz de `portal-carmel` (ou aponte `BORDERO_ENV_FILE` / `INVENTARIO_ENV_FILE`) e preencha as credenciais de leitura do banco PostgreSQL.

## Execução

Na pasta `portal-carmel`:

```powershell
python main.py
# ou
python -m portal
```

Acesse no navegador: `http://127.0.0.1:8550`

## Testes

```powershell
uv run --directory portal-carmel python -m unittest discover -s tests -v
```
