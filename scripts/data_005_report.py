"""DATA-005 report builder: reads the live store, computes the required
rates, checks the quality gates, classifies A/B/C/D and writes
docs/DATA_005_PROSPECTIVE_LINEUP_VALIDATION.md.

Run: python scripts/data_005_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lineup_capture.models import CaptureManifest, CaptureRecord

OUT_DIR = Path("backtest_output/data_005_lineup_live")
STORE = OUT_DIR / "store"
DOC = Path("docs/DATA_005_PROSPECTIVE_LINEUP_VALIDATION.md")


def load_all() -> Dict[str, Any]:
    manifests: List[CaptureManifest] = []
    for p in sorted((STORE / "manifests").glob("*.json")):
        manifests.append(CaptureManifest.model_validate(json.loads(p.read_text(encoding="utf-8"))))
    records_by_event: Dict[str, List[CaptureRecord]] = {}
    observations_by_event: Dict[str, List[dict]] = {}
    for p in sorted((STORE / "normalized").glob("*.jsonl")):
        records_by_event[p.stem] = [CaptureRecord.model_validate(json.loads(l))
                                    for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    for p in sorted((STORE / "observations").glob("*.jsonl")):
        observations_by_event[p.stem] = [json.loads(l)
                                         for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    # real-match universe = observation events (sessions that never finalized
    # still left real observation logs) UNION manifest events
    event_ids = sorted(set(observations_by_event) | {m.event_id for m in manifests})
    return {"manifests": manifests, "records": records_by_event,
            "observations": observations_by_event, "event_ids": event_ids}


def audit(store_data: Dict[str, Any]) -> Dict[str, Any]:
    manifests = store_data["manifests"]
    records = store_data["records"]
    obs = store_data["observations"]
    gates: Dict[str, Any] = {}
    issues: List[str] = []

    # gate 1+4: post-match data marked time_safe (capture_time >= kickoff)
    bad_safe = []
    for eid, recs in records.items():
        for r in recs:
            if r.time_safe and r.state.capture_time >= r.state.kickoff_utc:
                bad_safe.append((eid, r.version))
    gates["post_match_marked_time_safe"] = len(bad_safe) == 0
    if bad_safe:
        issues.append(f"post-match data marked time_safe: {bad_safe}")

    # gate 2: kickoff consistency across records per event
    for eid, recs in records.items():
        kickoffs = {r.state.kickoff_utc.isoformat() for r in recs}
        if len(kickoffs) > 1:
            gates["kickoff_consistent"] = False
            issues.append(f"kickoff changed across versions: {eid} {kickoffs}")
            break
    else:
        gates["kickoff_consistent"] = True

    # gate 3: timezone - all timestamps must be tz-aware UTC
    naive = []
    for eid, recs in records.items():
        for r in recs:
            for v in (r.state.capture_time, r.state.kickoff_utc):
                if v.tzinfo is None or v.utcoffset() != __import__("datetime").timedelta(0):
                    naive.append((eid, r.version))
    gates["timezone_utc"] = len(naive) == 0
    if naive:
        issues.append(f"naive/non-UTC timestamps: {naive[:5]}")

    # gate 5: immutable snapshots (recompute hashes)
    bad_hash = []
    for eid, recs in records.items():
        for r in recs:
            p = Path(r.raw_snapshot_path)
            if not p.exists():
                bad_hash.append((eid, r.version, "missing"))
            else:
                import hashlib
                h = hashlib.sha256(p.read_bytes()).hexdigest()
                if h != r.raw_snapshot_sha256:
                    bad_hash.append((eid, r.version, "hash mismatch"))
    gates["immutable_snapshots"] = len(bad_hash) == 0
    if bad_hash:
        issues.append(f"immutable snapshot failures: {bad_hash[:5]}")

    # gate 6: version continuity (no gaps, no loss)
    gap = []
    for eid, recs in records.items():
        vers = [r.version for r in recs]
        if vers != sorted(vers) or vers != list(range(1, len(recs) + 1)):
            gap.append((eid, vers))
    gates["version_continuity"] = len(gap) == 0
    if gap:
        issues.append(f"version gaps: {gap}")

    # gate 7: polling after kickoff must not produce time_safe records
    # (guaranteed by the strict inequality gate 1; explicitly reported)

    # gate 9: ESPN returns FINAL XI indistinguishably -> known limitation
    gates["final_xi_source_limitation_flagged"] = True
    issues.append("KNOWN LIMITATION: ESPN provides no native publication "
                  "timestamp; time_safe rests on capture-proxy evidence only")

    # ---- per-match status (valid-XI rule: a capture is a VALID lineup
    # sample only when home_xi>=11 AND away_xi>=11; empty-XI records from the
    # pre-fix era are preserved on disk but excluded from all valid-sample
    # statistics and never count toward time_safe) ----
    def valid_xi(rec) -> bool:
        return (len(rec.state.home_xi) >= 11 and len(rec.state.away_xi) >= 11)

    valid_by_event = {eid: [r for r in recs if valid_xi(r)]
                      for eid, recs in records.items()}
    n_invalid_empty_xi = sum(len(recs) - len(valid_by_event[eid])
                             for eid, recs in records.items())

    match_status: Dict[str, str] = {}
    for eid in store_data["event_ids"]:
        recs = records.get(eid, [])
        entries = obs.get(eid, [])
        if valid_by_event.get(eid):
            match_status[eid] = ("captured_time_safe"
                                 if any(r.time_safe for r in valid_by_event[eid])
                                 else "captured_post_kickoff_only")
            continue
        if recs:
            match_status[eid] = "captured_invalid_empty_xi"
            continue
        in_window_polls = [e for e in entries
                           if e.get("outcome") in ("no_lineup_yet",
                                                   "post_kickoff_no_lineup")]
        if in_window_polls:
            match_status[eid] = "window_reached_no_lineup"
        else:
            match_status[eid] = "window_missed_or_not_reached"

    # ---- rates (all capture/time_safe statistics use VALID records only) ----
    n_matches = len(store_data["event_ids"])
    n_with_lineup = sum(1 for eid, recs in valid_by_event.items() if recs)
    n_time_safe_match = sum(1 for eid, recs in valid_by_event.items()
                            if any(r.time_safe for r in recs))
    n_window_missed = sum(1 for v in match_status.values()
                          if v == "window_missed_or_not_reached")
    n_captured = sum(1 for v in match_status.values() if v.startswith("captured"))
    total_versions = sum(len(v) for v in valid_by_event.values())
    safe_versions = sum(sum(1 for r in v if r.time_safe)
                        for v in valid_by_event.values())
    pre_kickoff_versions = sum(
        sum(1 for r in v if r.state.capture_time < r.state.kickoff_utc)
        for v in valid_by_event.values())
    multi_version = sum(1 for eid, recs in valid_by_event.items() if len(recs) > 1)
    polls = sum(len(v) for v in obs.values())
    lineup_polls = 0
    unchanged_polls = 0
    error_polls = 0
    no_lineup_polls = 0
    for eid, entries in obs.items():
        for e in entries:
            out = e.get("outcome", "")
            if out == "lineup_captured":
                lineup_polls += 1
            elif out == "lineup_unchanged":
                unchanged_polls += 1
                lineup_polls += 1
            elif out == "source_error":
                error_polls += 1
            elif out in ("no_lineup_yet", "post_kickoff_no_lineup", "post_kickoff"):
                no_lineup_polls += 1
    events_with_error = {eid for eid, entries in obs.items()
                         if any(e.get("outcome") == "source_error" for e in entries)}
    events_with_error_then_lineup = {
        eid for eid in events_with_error if valid_by_event.get(eid)}
    first_capture_pre_kickoff = sum(
        1 for eid, recs in valid_by_event.items()
        if recs and recs[0].state.capture_time < recs[0].state.kickoff_utc)

    rates = {
        "real_matches": n_matches,
        "matches_with_lineup": n_with_lineup,
        "matches_time_safe": n_time_safe_match,
        "window_missed_or_not_reached": n_window_missed,
        "matches_captured_any": n_captured,
        "invalid_empty_xi_records_excluded": n_invalid_empty_xi,
        "time_safe_match_rate": round(n_time_safe_match / max(n_matches, 1), 4),
        "capture_success_rate": round(n_with_lineup / max(n_matches, 1), 4),
        "first_lineup_capture_rate": round(first_capture_pre_kickoff / max(n_with_lineup, 1), 4),
        "pre_kickoff_capture_rate": round(pre_kickoff_versions / max(total_versions, 1), 4),
        "unstable_rate": round(multi_version / max(n_with_lineup, 1), 4),
        "duplicate_rate": round(unchanged_polls / max(lineup_polls, 1), 4),
        "api_failure_rate": round(error_polls / max(polls, 1), 4),
        "retry_recovery_rate": round(len(events_with_error_then_lineup) / max(len(events_with_error), 1), 4),
        "version_change_rate": round(multi_version / max(n_with_lineup, 1), 4),
        "total_versions": total_versions,
        "time_safe_versions": safe_versions,
        "total_polls": polls,
    }

    # ---- classification ----
    if issues and any(g in ("post_match_marked_time_safe", "immutable_snapshots",
                            "version_continuity") for g, v in gates.items() if v is False):
        classification = "C: PIPELINE FAILURE"
    elif n_time_safe_match >= 100:
        classification = "A: REAL-WORLD PIPELINE VALIDATED"
    elif n_time_safe_match >= 10:
        classification = "B: PARTIAL VALIDATION"
    else:
        classification = "D: INSUFFICIENT REAL-WORLD OBSERVATION"
    return {"gates": gates, "issues": issues, "rates": rates,
            "match_status": match_status,
            "classification": classification}


def main() -> None:
    data = load_all()
    result = audit(data)
    rates = result["rates"]

    lines: List[str] = []
    lines.append("# DATA-005：前瞻实时首发采集实弹验证（Prospective Live Lineup Capture Validation）")
    lines.append("")
    lines.append("> 真实世界验证：仅使用**真实即将开赛的比赛**（西甲 2026-27 首批；英超 2026-27 "
                 "开赛后加入）。禁止 mock/historical replay/赛后补抓/用最终 XI 反推；"
                 "历史 FINAL XI 不转换为 time_safe。本阶段不运行预测实验、不计算 "
                 "ΔBrier/LogLoss/ROI、不进入 V1.3、不是 DIAG-010。")
    lines.append("")
    lines.append("## 0. 最终判定")
    lines.append("")
    lines.append(f"**分类：{result['classification']}**")
    lines.append("")
    lines.append("## 1. 采集概览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    for k, v in rates.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## 2. 逐场记录")
    lines.append("")
    lines.append("| event_id | kickoff (UTC) | 状态 | versions | time_safe | polls | failures |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for eid in data["event_ids"]:
        status = result["match_status"].get(eid, "?")
        entries = data["observations"].get(eid, [])
        kickoff = None
        for e in reversed(entries):
            if e.get("kickoff_observed"):
                kickoff = e["kickoff_observed"]
                break
        m = next((m for m in data["manifests"] if m.event_id == eid), None)
        recs = data["records"].get(eid, [])
        versions = m.versions if m else len(recs)
        safe = m.time_safe_versions if m else sum(1 for r in recs if r.time_safe)
        polls = len(entries)  # observations are the ground truth
        fails = sum(1 for e in entries if e.get("outcome") == "source_error")
        lines.append(f"| {eid} | {kickoff or '?'} | {status} | {versions} | "
                     f"{safe} | {polls} | {fails} |")
    lines.append("")
    lines.append("## 2.1 工程限制（如实报告）")
    lines.append("")
    lines.append("- 本运行环境**无法保证后台任务跨回合持续运行**：两次采集会话均在环境中断时"
                 "被杀（401882925、401882908 → `window_missed`，比赛在中断期间完赛，"
                 "**未做赛后补抓**，不转为 time_safe）。")
    lines.append("- 已按指令停止长时间 wait/sleep 值守；当前正在运行的两个无人值守采集会话"
                 "（401882914 Betis-Sociedad 19:00Z、401876489 Marseille-Strasbourg 18:45Z）"
                 "将在窗口开启后自行轮询（16:45-17:00Z 起），其结果可在下次检查时读取；"
                 "本报告基于当前已确认的证据定级，不因『可能成功』而升级分类。")
    lines.append("")
    lines.append("## 3. 质量门槛")
    lines.append("")
    for gate, ok in result["gates"].items():
        lines.append(f"- {gate}: {'PASS' if ok else 'FAIL'}")
    lines.append("")
    lines.append("## 4. 已知限制与问题")
    lines.append("")
    for issue in result["issues"]:
        lines.append(f"- {issue}")
    lines.append("")
    lines.append("## 5. 说明")
    lines.append("")
    lines.append("- 全部时间戳 UTC-aware；time_safe 采用严格不等式 "
                 "`information_available_time < kickoff`。")
    lines.append("- ESPN 无原生 published_at → `time_trust='capture_proxy'`，"
                 "capture_time 是系统可用性证据，绝非官方发布时间。")
    lines.append("- 若某场比赛首发首次捕获发生在 kickoff 后 → 该场 `time_safe=False`，不得补救。")
    lines.append("- mock 与历史数据不计入；本文件只统计真实捕获。")
    lines.append(f"- 总体 manifest 与 fingerprint：`{OUT_DIR / 'MANIFEST.json'}`。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")
    print(json.dumps(result["rates"], indent=1))
    print(f"classification: {result['classification']}")


if __name__ == "__main__":
    main()
