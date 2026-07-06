import json
import os
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

try:
    from langchain_chroma import Chroma
    from langchain_community.embeddings import FakeEmbeddings
except Exception:  # pragma: no cover - fallback when Chroma is unavailable
    Chroma = None
    FakeEmbeddings = None


class _FallbackStore:
    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.storage_file = storage_dir / "repair-cases.json"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._items: list[dict[str, Any]] = []
        if self.storage_file.exists():
            try:
                self._items = json.loads(self.storage_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._items = []

    def add_documents(self, docs: list[Document]) -> None:
        for doc in docs:
            self._items.append(
                {
                    "page_content": doc.page_content,
                    "metadata": doc.metadata,
                }
            )
        self.storage_file.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def similarity_search(self, query: str, k: int = 3) -> list[Document]:
        query_lower = query.lower()
        scored = []
        for item in self._items:
            content = item.get("page_content", "").lower()
            score = sum(1 for token in query_lower.split() if token in content)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            Document(
                page_content=item["page_content"],
                metadata=item.get("metadata", {}),
            )
            for _, item in scored[:k]
        ]


class RepairRAGStore:
    def __init__(self, storage_dir: str | None = None, collection_name: str = "repair-cases") -> None:
        self.storage_dir = Path(storage_dir or os.getenv("RAG_STORAGE_DIR", "/tmp/repair-rag"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._vectorstore = None

    def _get_vectorstore(self):
        if self._vectorstore is None:
            if Chroma is not None and FakeEmbeddings is not None:
                try:
                    self._vectorstore = Chroma(
                        collection_name=self.collection_name,
                        embedding_function=FakeEmbeddings(size=1536),
                        persist_directory=str(self.storage_dir),
                    )
                except Exception:
                    self._vectorstore = _FallbackStore(self.storage_dir)
            else:
                self._vectorstore = _FallbackStore(self.storage_dir)
        return self._vectorstore

    def add_case(
        self,
        deployment: str,
        pod_name: str,
        failure_reason: str,
        action: str,
        outcome: str,
        logs: str,
    ) -> None:
        doc = Document(
            page_content="\n".join(
                [
                    f"deployment={deployment}",
                    f"pod={pod_name}",
                    f"failure_reason={failure_reason}",
                    f"action={action}",
                    f"outcome={outcome}",
                    f"logs={logs}",
                ]
            ),
            metadata={
                "deployment": deployment,
                "pod_name": pod_name,
                "failure_reason": failure_reason,
                "action": action,
                "outcome": outcome,
            },
        )
        store = self._get_vectorstore()
        if hasattr(store, "add_documents"):
            store.add_documents([doc])

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        docs = self._get_vectorstore().similarity_search(query, k=limit)
        return [
            {
                "deployment": doc.metadata.get("deployment", ""),
                "pod_name": doc.metadata.get("pod_name", ""),
                "failure_reason": doc.metadata.get("failure_reason", ""),
                "action": doc.metadata.get("action", ""),
                "outcome": doc.metadata.get("outcome", ""),
                "content": doc.page_content,
            }
            for doc in docs
        ]

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        store = self._get_vectorstore()

        if isinstance(store, _FallbackStore):
            items = store._items[-limit:]
            return [
                {
                    "deployment": item.get("metadata", {}).get("deployment", ""),
                    "pod_name": item.get("metadata", {}).get("pod_name", ""),
                    "failure_reason": item.get("metadata", {}).get("failure_reason", ""),
                    "action": item.get("metadata", {}).get("action", ""),
                    "outcome": item.get("metadata", {}).get("outcome", ""),
                    "content": item.get("page_content", ""),
                }
                for item in reversed(items)
            ]

        try:
            raw = store.get(include=["documents", "metadatas"])
            docs = raw.get("documents") or []
            metas = raw.get("metadatas") or []
            combined = list(zip(docs, metas))[-limit:]
            return [
                {
                    "deployment": (meta or {}).get("deployment", ""),
                    "pod_name": (meta or {}).get("pod_name", ""),
                    "failure_reason": (meta or {}).get("failure_reason", ""),
                    "action": (meta or {}).get("action", ""),
                    "outcome": (meta or {}).get("outcome", ""),
                    "content": doc,
                }
                for doc, meta in reversed(combined)
            ]
        except Exception:
            return []
