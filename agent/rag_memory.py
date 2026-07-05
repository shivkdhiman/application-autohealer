import os
import json
from pathlib import Path
from typing import Any

from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document


class RepairRAGStore:
    def __init__(self, storage_dir: str | None = None, collection_name: str = "repair-cases") -> None:
        self.storage_dir = Path(storage_dir or os.getenv("RAG_STORAGE_DIR", "/tmp/repair-rag"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._vectorstore = None

    def _get_vectorstore(self) -> Chroma:
        if self._vectorstore is None:
            self._vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=FakeEmbeddings(size=1536),
                persist_directory=str(self.storage_dir),
            )
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
        self._get_vectorstore().add_documents([doc])
        self._get_vectorstore().persist()

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
