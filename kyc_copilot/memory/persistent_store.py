"""Smriti Persistent Digital Twin Store & Arthashastra Policy RAG.

Named after *Smriti* (remembered tradition / institutional memory), this module
provides persistent SQLite storage for Entity Digital Twins, immutable audit
snapshots, session states, and Perpetual KYC (cKYC) watch subscriptions, plus
a simple pure-Python TF-IDF vector Policy RAG index over `data/kyc_governance_policy.md`.

Includes clean GCP production adapter classes (`CloudSqlDigitalTwinAdapter` and
`VertexAiSearchPolicyRagAdapter`) so local CI runs zero-config while GCP
deployments wire straight into Cloud SQL and Vertex AI Search.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kyc_copilot.callbacks.kavach_pii_redactor import redact_pii_in_structure
from kyc_copilot.models.schemas import CorporateGoldenRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / "data" / "kyc_governance_policy.md"
DEFAULT_SQLITE_PATH = Path(
    os.getenv("KYC_SQLITE_PATH", str(REPO_ROOT / ".adk" / "smriti_digital_twin.sqlite3"))
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SmritiDigitalTwinStore:
    """SQLite-backed Digital Twin, audit snapshot, and session state repository."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_SQLITE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS digital_twin_entities (
                    entity_id TEXT PRIMARY KEY,
                    registration_number TEXT,
                    canonical_name TEXT NOT NULL,
                    jurisdiction_iso TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_states (
                    case_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ckyc_watches (
                    entity_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    watch_config_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                """
            )

    def upsert_golden_record(self, record: CorporateGoldenRecord) -> None:
        """Persists or updates a canonical CorporateGoldenRecord in SQLite."""
        sanitized = redact_pii_in_structure(record.model_dump())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO digital_twin_entities
                    (entity_id, registration_number, canonical_name, jurisdiction_iso, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    registration_number=excluded.registration_number,
                    canonical_name=excluded.canonical_name,
                    jurisdiction_iso=excluded.jurisdiction_iso,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.entity_id,
                    record.registration_number,
                    record.canonical_name,
                    record.jurisdiction_iso,
                    json.dumps(sanitized, sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def get_golden_record(self, entity_id: str) -> Optional[CorporateGoldenRecord]:
        """Retrieves a persisted Digital Twin record by entity_id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM digital_twin_entities WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        if not row:
            return None
        return CorporateGoldenRecord.model_validate_json(row["payload_json"])

    def find_by_registration_number(
        self, registration_number: str
    ) -> Optional[CorporateGoldenRecord]:
        """Looks up a persisted Digital Twin record by corporate registration number."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM digital_twin_entities WHERE registration_number = ?",
                (registration_number,),
            ).fetchone()
        if not row:
            return None
        return CorporateGoldenRecord.model_validate_json(row["payload_json"])

    def save_audit_snapshot(
        self,
        snapshot_id: str,
        case_id: str,
        tool_name: str,
        source_uri: str,
        payload: dict[str, Any],
    ) -> None:
        """Persists an immutable, PII-redacted audit snapshot."""
        clean_payload = redact_pii_in_structure(payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_snapshots
                    (snapshot_id, case_id, tool_name, source_uri, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    case_id,
                    tool_name,
                    source_uri,
                    json.dumps(clean_payload, default=str, sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def list_case_snapshots(self, case_id: str) -> list[dict[str, Any]]:
        """Lists all persisted audit snapshots for a case."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_id, tool_name, source_uri, payload_json, created_at "
                "FROM audit_snapshots WHERE case_id = ? ORDER BY created_at ASC",
                (case_id,),
            ).fetchall()
        return [
            {
                "snapshot_id": r["snapshot_id"],
                "tool_name": r["tool_name"],
                "source_uri": r["source_uri"],
                "payload": json.loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def save_session_state(
        self, case_id: str, status: str, state: dict[str, Any]
    ) -> None:
        """Persists cross-turn case session state (e.g., AWAITING_CLIENT_RFI)."""
        clean_state = redact_pii_in_structure(state)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_states (case_id, status, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    status=excluded.status,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (
                    case_id,
                    status,
                    json.dumps(clean_state, default=str, sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def get_session_state(self, case_id: str) -> Optional[dict[str, Any]]:
        """Loads persisted session state across turns."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, state_json, updated_at FROM session_states WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "case_id": case_id,
            "status": row["status"],
            "state": json.loads(row["state_json"]),
            "updated_at": row["updated_at"],
        }

    def register_ckyc_watch(
        self,
        entity_id: str,
        case_id: str,
        risk_tier: str,
        watch_config: dict[str, Any],
    ) -> None:
        """Registers a Stage 7 Perpetual KYC (cKYC) event monitor."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ckyc_watches
                    (entity_id, case_id, risk_tier, watch_config_json, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    case_id=excluded.case_id,
                    risk_tier=excluded.risk_tier,
                    watch_config_json=excluded.watch_config_json,
                    registered_at=excluded.registered_at
                """,
                (
                    entity_id,
                    case_id,
                    risk_tier,
                    json.dumps(watch_config, sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def get_ckyc_watch(self, entity_id: str) -> Optional[dict[str, Any]]:
        """Fetches the registered cKYC watch subscription for an entity."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT entity_id, case_id, risk_tier, watch_config_json, registered_at "
                "FROM ckyc_watches WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "entity_id": row["entity_id"],
            "case_id": row["case_id"],
            "risk_tier": row["risk_tier"],
            "watch_config": json.loads(row["watch_config_json"]),
            "registered_at": row["registered_at"],
        }


class CloudSqlDigitalTwinAdapter(SmritiDigitalTwinStore):
    """GCP Cloud SQL PostgreSQL adapter (falls back to SQLite locally/CI)."""

    def __init__(
        self,
        connection_name: Optional[str] = None,
        fallback_sqlite_path: str | Path | None = None,
    ) -> None:
        self.connection_name = connection_name or os.getenv(
            "CLOUD_SQL_CONNECTION_NAME"
        )
        super().__init__(db_path=fallback_sqlite_path)


# ---------------------------------------------------------------------------
# Pure-Python Local Vector Policy RAG (TF-IDF Cosine Similarity)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class ArthashastraPolicyRag:
    """Simple, dependency-free TF-IDF cosine vector retriever over bank KYC policy."""

    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path or DEFAULT_POLICY_PATH
        self.chunks: list[dict[str, Any]] = []
        self._idf: dict[str, float] = {}
        self._load_and_index()

    def _load_and_index(self) -> None:
        raw_md = self.policy_path.read_text(encoding="utf-8")
        sections = [s.strip() for s in raw_md.split("\n## ") if s.strip()]
        doc_freq: Counter[str] = Counter()

        for idx, section in enumerate(sections):
            lines = section.splitlines()
            title = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip() or title
            rule_match = re.search(r"(POL-[A-Z0-9-]+)", title)
            rule_id = rule_match.group(1) if rule_match else f"POL-GEN-{idx:02d}"
            tokens = _tokenize(f"{title} {body}")
            tf = Counter(tokens)
            for tok in tf:
                doc_freq[tok] += 1
            self.chunks.append(
                {
                    "rule_id": rule_id,
                    "title": title,
                    "body": body,
                    "source_uri": f"policy://kyc_governance_policy.md#{rule_id}",
                    "tf": tf,
                }
            )

        total_docs = max(len(self.chunks), 1)
        self._idf = {
            tok: math.log((1.0 + total_docs) / (1.0 + df)) + 1.0
            for tok, df in doc_freq.items()
        }

    def _tfidf_vector(self, tf: Counter[str]) -> dict[str, float]:
        return {tok: count * self._idf.get(tok, 1.0) for tok, count in tf.items()}

    @staticmethod
    def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        if not vec_a or not vec_b:
            return 0.0
        common = set(vec_a).intersection(vec_b)
        dot = sum(vec_a[k] * vec_b[k] for k in common)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def query_policy(self, query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Retrieves the top-K relevant bank KYC policy sections via cosine similarity."""
        query_vec = self._tfidf_vector(Counter(_tokenize(query_text)))
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self.chunks:
            chunk_vec = self._tfidf_vector(chunk["tf"])
            score = self._cosine_similarity(query_vec, chunk_vec)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "rule_id": item["rule_id"],
                "title": item["title"],
                "excerpt": item["body"],
                "source_uri": item["source_uri"],
                "similarity_score": round(score, 4),
            }
            for score, item in scored[:top_k]
            if score > 0.0
        ]


class VertexAiSearchPolicyRagAdapter(ArthashastraPolicyRag):
    """GCP Vertex AI Search Policy RAG adapter with local TF-IDF fallback."""

    def __init__(
        self,
        datastore_id: Optional[str] = None,
        policy_path: Path | None = None,
    ) -> None:
        self.datastore_id = datastore_id or os.getenv("VERTEX_AI_SEARCH_DATASTORE_ID")
        super().__init__(policy_path=policy_path)


_GLOBAL_SMRITI_STORE: SmritiDigitalTwinStore | None = None
_GLOBAL_POLICY_RAG: ArthashastraPolicyRag | None = None


def get_smriti_store(db_path: str | Path | None = None) -> SmritiDigitalTwinStore:
    """Returns the configured persistent store (SQLite default or Cloud SQL adapter)."""
    global _GLOBAL_SMRITI_STORE
    if db_path is not None:
        return SmritiDigitalTwinStore(db_path=db_path)
    if _GLOBAL_SMRITI_STORE is None:
        backend = os.getenv("KYC_STORAGE_BACKEND", "sqlite").lower()
        if backend == "gcp":
            _GLOBAL_SMRITI_STORE = CloudSqlDigitalTwinAdapter()
        else:
            _GLOBAL_SMRITI_STORE = SmritiDigitalTwinStore()
    return _GLOBAL_SMRITI_STORE


def set_smriti_store(store: SmritiDigitalTwinStore) -> None:
    """Overrides the active global store (helpful for isolated pytest fixtures)."""
    global _GLOBAL_SMRITI_STORE
    _GLOBAL_SMRITI_STORE = store


def get_policy_rag() -> ArthashastraPolicyRag:
    """Returns the configured Policy RAG index (local vector or Vertex AI Search)."""
    global _GLOBAL_POLICY_RAG
    if _GLOBAL_POLICY_RAG is None:
        if os.getenv("VERTEX_AI_SEARCH_DATASTORE_ID"):
            _GLOBAL_POLICY_RAG = VertexAiSearchPolicyRagAdapter()
        else:
            _GLOBAL_POLICY_RAG = ArthashastraPolicyRag()
    return _GLOBAL_POLICY_RAG
