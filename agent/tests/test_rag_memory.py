import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_memory import RepairRAGStore


def test_repair_rag_store_retrieves_similar_cases(tmp_path):
    store = RepairRAGStore(storage_dir=str(tmp_path / "rag"))

    store.add_case(
        deployment="backend",
        pod_name="backend-123",
        failure_reason="ImagePullBackOff",
        action="rollback_deployment",
        outcome="rolled back deployment backend",
        logs="image pull failed because invalidtag",
    )

    matches = store.search("invalid image tag rollback deployment", limit=3)

    assert matches
    assert any(item["action"] == "rollback_deployment" for item in matches)
    assert any(item["deployment"] == "backend" for item in matches)
