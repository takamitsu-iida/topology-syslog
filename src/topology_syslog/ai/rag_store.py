"""ChromaDB ベースのインシデント RAG ストア（セマンティック類似検索）。

DefaultEmbeddingFunction (ONNX all-MiniLM-L6-v2) を使用。
初回起動時にモデルが自動ダウンロードされる。
"""
from __future__ import annotations

import logging

from topology_syslog.models import Incident

_logger = logging.getLogger(__name__)
_COLLECTION = "incidents"


def _to_document(incident: Incident) -> str:
    lines = [
        f"RootCause: {incident.root_cause_node}",
        f"PrimaryEvent: {incident.primary_event}",
    ]
    if incident.secondary_nodes:
        lines.append(f"SecondaryNodes: {', '.join(incident.secondary_nodes)}")
    for log in incident.raw_logs[:8]:
        lines.append(f"Log: {log}")
    return "\n".join(lines)


class RAGStore:
    def __init__(self, persist_path: str) -> None:
        import chromadb  # lazy import — optional dep (pip install topology-syslog[ai])
        client = chromadb.PersistentClient(path=persist_path)
        self._col = client.get_or_create_collection(name=_COLLECTION)

    def add(self, incident: Incident) -> None:
        """インシデントをベクターストアに追加（同 ID は上書き）。"""
        self._col.upsert(
            ids=[incident.incident_id],
            documents=[_to_document(incident)],
            metadatas=[{
                "root_cause": incident.root_cause_node,
                "created_at": incident.created_at.isoformat(),
            }],
        )

    def search_similar(self, incident: Incident, n: int = 3) -> list[str]:
        """意味的に類似した過去インシデントのテキストを最大 n 件返す。自身は除外。"""
        total = self._col.count()
        if total == 0:
            return []
        try:
            results = self._col.query(
                query_texts=[_to_document(incident)],
                n_results=min(n + 1, total),  # +1 は自身除外のバッファ
            )
            docs = results["documents"][0] if results["documents"] else []
            ids  = results["ids"][0]       if results["ids"]       else []
            return [d for d, i in zip(docs, ids) if i != incident.incident_id][:n]
        except Exception as exc:
            _logger.warning("RAG search failed: %s", exc)
            return []

    def search_similar_ids(self, incident: Incident, n: int = 5) -> list[str]:
        """意味的に類似した過去インシデントの ID リストを返す。自身は除外。"""
        total = self._col.count()
        if total == 0:
            return []
        try:
            results = self._col.query(
                query_texts=[_to_document(incident)],
                n_results=min(n + 1, total),
                include=[],  # ドキュメント本文不要; ID のみ
            )
            ids = results["ids"][0] if results["ids"] else []
            return [i for i in ids if i != incident.incident_id][:n]
        except Exception as exc:
            _logger.warning("RAG similar-ids search failed: %s", exc)
            return []

    def search_similar_text_ids(self, text: str, n: int = 5) -> list[str]:
        """任意の SYSLOG テキストに類似したインシデント ID を返す。"""
        total = self._col.count()
        if total == 0:
            return []
        try:
            results = self._col.query(
                query_texts=[text], n_results=min(n, total), include=[]
            )
            return results["ids"][0] if results["ids"] else []
        except Exception as exc:
            _logger.warning("RAG text search failed: %s", exc)
            return []
