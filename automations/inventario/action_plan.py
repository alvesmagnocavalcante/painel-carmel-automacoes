"""API contract, editable action fields and persistent local plan storage."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv


DEFAULT_API_URL = "https://api-relatorio-auditoria-inventario-387905886048.europe-west1.run.app/api/auditorias"
# Internal dataset identity, not an address to connect to. Keep this legacy
# value so moving the HTTP service does not duplicate previously saved plans.
DEFAULT_SOURCE_ID = "http://127.0.0.1:8001/api/auditorias"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
STATUSES = ("Não iniciada", "Em andamento", "Replanejada", "Atrasada", "Concluída")


def load_environment():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def parse_date(value: str) -> date | None:
    if not value.strip():
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            pass
    raise ValueError("Informe as datas no formato DD/MM/AAAA.")


@dataclass(frozen=True)
class ManualFields:
    how: str = ""
    responsible: str = ""
    start: str = ""
    due: str = ""
    revised: str = ""
    completed: str = ""
    progress: int = 0
    notes: str = ""

    def validate(self):
        if type(self.progress) is not int or not 0 <= self.progress <= 100:
            raise ValueError("O percentual concluído deve ser um inteiro de 0 a 100.")
        if any(len(value) > 12000 for value in (self.how, self.responsible, self.notes)):
            raise ValueError("Um dos campos ultrapassou o limite de 12.000 caracteres.")
        dates = {key: parse_date(getattr(self, key)) for key in ("start", "due", "revised", "completed")}
        if dates["start"] and any(value and value < dates["start"] for key, value in dates.items() if key != "start"):
            raise ValueError("Os prazos e a realização não podem ser anteriores ao início.")
        if dates["completed"] and self.progress != 100:
            raise ValueError("Ao informar a data realizada, preencha 100% concluído.")
        return self

    def status(self, today: date | None = None) -> str:
        if self.completed or self.progress == 100:
            return "Concluída"
        deadline = parse_date(self.revised or self.due)
        if deadline and deadline < (today or date.today()):
            return "Atrasada"
        if self.revised:
            return "Replanejada"
        if self.start or self.progress:
            return "Em andamento"
        return "Não iniciada"


@dataclass(frozen=True)
class Action:
    id: str
    hotel: str
    inventory_date: str
    improvement: str
    source_date: str
    manual: ManualFields = field(default_factory=ManualFields)
    revision: int = 0


def actions_from_response(payload: dict, source: str) -> tuple[Action, ...]:
    required = ("hotel", "data", "pontos_de_melhoria", "carimbo_de_data_hora", "endereco_de_e_mail")
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("A API retornou uma resposta inválida.")
    if not isinstance(payload.get("columns"), list):
        raise ValueError("A API não informou as colunas das auditorias.")
    keys = {column.get("key") for column in payload["columns"] if isinstance(column, dict)}
    if payload["items"] and not set(required) <= keys:
        raise ValueError("O formato da API mudou: faltam campos obrigatórios das auditorias.")
    actions = {}
    for item in payload["items"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in required):
            raise ValueError("A API retornou uma auditoria incompleta.")
        if not item["pontos_de_melhoria"].strip():
            continue
        # Row numbers are not stable when Sheets rows are inserted or sorted.
        identity = [source, *(item[key].strip() for key in ("carimbo_de_data_hora", "endereco_de_e_mail", "hotel", "data"))]
        if not all(identity):
            raise ValueError("Uma auditoria não possui identificação suficiente para salvar o plano.")
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        action = Action(key, item["hotel"].strip(), item["data"].strip(),
                        item["pontos_de_melhoria"].strip(), item["carimbo_de_data_hora"].strip())
        if key in actions:
            raise ValueError("A API retornou auditorias com identificação duplicada. Revise a origem.")
        actions[key] = action
    return tuple(actions.values())


class AuditApi:
    def __init__(self, url: str | None = None):
        load_environment()
        configured_url = (url or os.getenv("INVENTARIO_AUDITORIA_API_URL") or DEFAULT_API_URL).strip()
        parsed = urlparse(configured_url)
        self.url = parsed._replace(path="/api/auditorias").geturl() if parsed.path in ("", "/") else configured_url
        self.source_id = os.getenv("INVENTARIO_AUDITORIA_SOURCE_ID", DEFAULT_SOURCE_ID).strip()
        if not self.source_id:
            raise ValueError("Configure uma identificação não vazia para a origem das auditorias.")

    def fetch(self) -> tuple[Action, ...]:
        parsed = urlparse(self.url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"))):
            raise ValueError("Use uma URL local HTTP ou uma URL HTTPS para a API de auditorias.")
        try:
            with urlopen(Request(self.url, headers={"Accept": "application/json"}), timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("A resposta da API excedeu o limite de 8 MB.")
            return actions_from_response(json.loads(raw), self.source_id)
        except HTTPError as error:
            raise RuntimeError(f"A API de auditorias retornou HTTP {error.code}. Verifique o serviço e sua configuração.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("Não foi possível acessar a API de auditorias. Confirme que ela está em execução.") from error
        except (json.JSONDecodeError, UnicodeError) as error:
            raise RuntimeError("A API de auditorias não retornou JSON válido.") from error


class ActionStore:
    def __init__(self, path: Path | None = None):
        load_environment()
        configured = os.getenv("INVENTARIO_ACTION_DB")
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = path if path is not None else Path(configured) if configured else root / "Carmel" / "portal" / "plano-acao.sqlite3"
        if not self.path.is_absolute():
            raise ValueError("INVENTARIO_ACTION_DB deve ser um caminho absoluto e persistente.")

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, hotel TEXT NOT NULL, inventory_date TEXT NOT NULL,
                    improvement TEXT NOT NULL, source_date TEXT NOT NULL,
                    manual TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                yield connection
        finally:
            connection.close()

    def sync(self, actions: tuple[Action, ...]):
        with self.connection() as connection:
            for item in actions:
                # Only source-owned fields change. Manual work is never overwritten.
                connection.execute("""INSERT INTO actions(id,hotel,inventory_date,improvement,source_date)
                    VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    hotel=excluded.hotel, inventory_date=excluded.inventory_date,
                    improvement=excluded.improvement, source_date=excluded.source_date""",
                    (item.id, item.hotel, item.inventory_date, item.improvement, item.source_date))

    def list(self) -> tuple[Action, ...]:
        with self.connection() as connection:
            return tuple(Action(row["id"], row["hotel"], row["inventory_date"], row["improvement"],
                                row["source_date"], ManualFields(**json.loads(row["manual"])), row["revision"])
                         for row in connection.execute("SELECT * FROM actions ORDER BY hotel,source_date,id"))

    def save(self, action: Action, fields: ManualFields):
        fields.validate()
        with self.connection() as connection:
            changed = connection.execute("""UPDATE actions SET manual=?, revision=revision+1,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?""",
                (json.dumps(asdict(fields), ensure_ascii=False), action.id, action.revision))
            if changed.rowcount != 1:
                raise ValueError("Este registro foi alterado em outra sessão. Recarregue os salvos antes de editar.")
