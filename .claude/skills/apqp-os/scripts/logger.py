"""APQP execution logger — append-only markdown log per node run.

Log location: <project>/logs/nXX-YYYYMMDD-HHMMSS.md

Purpose: Technical audit trail for debugging and traceability.
         Records WHAT happened, WHEN, and WHY decisions were made.
         NOT a results summary (that's the report's job).

Usage:
    from logger import NodeLogger
    log = NodeLogger('<project_path>', 'n01')
    log.step("Step 1: Read input files")
    log.info("Found 6 files in inputs/")
    log.file("SSTS.xlsx", "采购技术总要求", "L0")
    log.embed("SSTS.xlsx", ["CTS.docx"], ["ole1.bin"])
    log.decision("annual_volume", "客户文件未说明", "使用行业基准 50,000/年", "S4")
    log.warn("annual_volume not found")
    log.error("SAE J2044 not in file set")
    log.gap("R-01-01", "annual_volume missing", "warning", "50000 (S4)")
    log.done(artifact)   # writes closing mark + elapsed time
"""
import json
from datetime import datetime, timezone
from pathlib import Path


class NodeLogger:
    def __init__(self, project_path: str, node_id: str):
        self.node_id = node_id
        self.project_path = Path(project_path)
        self.log_dir = self.project_path / "logs"
        self.log_dir.mkdir(exist_ok=True)

        self._start_time = datetime.now(timezone.utc)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = self.log_dir / f"{node_id}-{ts}.md"

        self._write(f"# {node_id} 执行日志\n")
        self._write(f"**项目**: {self.project_path.name}  \n")
        self._write(f"**开始时间**: {self._start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}  \n")
        self._write("\n---\n\n")

    def _write(self, text: str):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text)

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def step(self, title: str):
        """Major step header — marks the beginning of a logical phase."""
        self._write(f"\n## [{self._ts()}] {title}\n\n")
        print(f"[{self._ts()}] ▶ {title}")

    def info(self, msg: str):
        """Informational entry — what happened."""
        self._write(f"- `{self._ts()}` {msg}\n")
        print(f"[{self._ts()}]   {msg}")

    def warn(self, msg: str):
        """Warning — something unexpected but not blocking."""
        self._write(f"- `{self._ts()}` ⚠️ {msg}\n")
        print(f"[{self._ts()}] ⚠ {msg}")

    def error(self, msg: str):
        """Error — something wrong that may affect results."""
        self._write(f"- `{self._ts()}` ❌ {msg}\n")
        print(f"[{self._ts()}] ✗ {msg}")

    def decision(self, field: str, situation: str, action: str, confidence: str = ""):
        """Record a judgment call — why a specific value/approach was chosen."""
        self._write(f"- `{self._ts()}` 🔹 **决策: {field}**\n")
        self._write(f"  - 情况: {situation}\n")
        self._write(f"  - 处理: {action}\n")
        if confidence:
            self._write(f"  - 置信度: {confidence}\n")
        print(f"[{self._ts()}] 🔹 决策: {field} → {action}")

    def gap(self, rule: str, msg: str, severity: str, assumption: str = ""):
        """Record a data gap with rule ID."""
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(severity, "·")
        line = f"- `{self._ts()}` {icon} `{rule}` {msg}"
        if assumption:
            line += f" → 假设: {assumption}"
        self._write(line + "\n")
        print(f"[{self._ts()}] GAP {rule}: {msg}")

    def file(self, fname: str, role: str, layer: str = "L0"):
        """Record a file being read/processed."""
        self._write(f"- `{self._ts()}` 📄 `[{layer}]` **{fname}** → {role}\n")

    def embed(self, src: str, extracted: list[str], discarded: list[str] = None):
        """Record embedded file extraction results."""
        self._write(f"\n`{self._ts()}` **{src}** 嵌入提取:\n")
        for f in extracted:
            self._write(f"  - ✅ {f}\n")
        for f in (discarded or []):
            self._write(f"  - 🗑 {f} (link-only, 丢弃)\n")

    def done(self, artifact: dict):
        """Write closing mark with elapsed time. No results summary — that's the report's job."""
        end_time = datetime.now(timezone.utc)
        elapsed = end_time - self._start_time
        elapsed_str = f"{int(elapsed.total_seconds())}s"
        if elapsed.total_seconds() >= 60:
            m, s = divmod(int(elapsed.total_seconds()), 60)
            elapsed_str = f"{m}m{s}s"

        gaps = artifact.get("gaps", [])
        gap_counts = {}
        for g in gaps:
            gap_counts[g["severity"]] = gap_counts.get(g["severity"], 0) + 1

        self._write("\n---\n\n")
        self._write(f"## 执行完成\n\n")
        self._write(f"- **结束时间**: {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        self._write(f"- **耗时**: {elapsed_str}\n")
        self._write(f"- **状态**: {artifact.get('status', '?')}\n")
        self._write(f"- **置信度底线**: {artifact.get('confidence_floor', '?')}\n")
        self._write(f"- **缺口**: {sum(gap_counts.values())} 个")
        if gap_counts:
            parts = [f"{v} {k}" for k, v in gap_counts.items()]
            self._write(f"（{', '.join(parts)}）")
        self._write(f"\n- **制品**: `artifacts/{self.node_id}-output.json`\n")
        self._write(f"- **日志**: `logs/{self.log_path.name}`\n")

        print(f"[{self._ts()}] ✓ {self.node_id} done ({elapsed_str}) — "
              f"{artifact.get('status','?')} / {artifact.get('confidence_floor','?')} / "
              f"{sum(gap_counts.values())} gaps — log: {self.log_path.name}")
