"""APQP artifact store — read/write project artifacts.

Usage:
    from store import ArtifactStore
    store = ArtifactStore('/path/to/project')
    store.write('n01', {...})
    artifact = store.read('n01')
    done = store.list_done()
"""
import json
from datetime import datetime, timezone
from pathlib import Path


class ArtifactStore:
    def __init__(self, project_path: str):
        self.artifacts_dir = Path(project_path) / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, node_id: str) -> Path:
        return self.artifacts_dir / f"{node_id}-output.json"

    def read(self, node_id: str) -> dict | None:
        p = self._path(node_id)
        return json.loads(p.read_text()) if p.exists() else None

    def write(self, node_id: str, data: dict) -> None:
        data.setdefault("produced_at", datetime.now(timezone.utc).isoformat())
        self._path(node_id).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def set_status(self, node_id: str, status: str) -> None:
        artifact = self.read(node_id) or {
            "node": node_id,
            "gaps": [],
            "assumptions": [],
            "payload": {},
        }
        artifact["status"] = status
        artifact.setdefault("produced_at", datetime.now(timezone.utc).isoformat())
        self._path(node_id).write_text(json.dumps(artifact, ensure_ascii=False, indent=2))

    def list_done(self) -> set[str]:
        """Return node IDs whose status is ready/done/waiting_human."""
        done = set()
        for f in self.artifacts_dir.glob("*-output.json"):
            try:
                d = json.loads(f.read_text())
                if d.get("status") in ("ready", "done", "waiting_human"):
                    done.add(d.get("node", f.stem.replace("-output", "")))
            except (json.JSONDecodeError, KeyError):
                continue
        return done

    def get_status(self, node_id: str) -> str:
        a = self.read(node_id)
        return a["status"] if a else "pending"

    def list_all(self) -> list[dict]:
        """Return all artifacts as list of dicts."""
        result = []
        for f in sorted(self.artifacts_dir.glob("*-output.json")):
            try:
                result.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                continue
        return result
