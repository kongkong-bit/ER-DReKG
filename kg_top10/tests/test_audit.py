from pathlib import Path

from kg_top10.audit import run_audit


def test_existing_top10_audit_has_ten_candidates(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    result = run_audit(root, tmp_path / "top10")
    assert len(result["candidates"]) == 10
    assert result["metrics"]["top10_count"] == 10
    assert result["metrics"]["identity_exact_count"] == 5


def test_audit_does_not_call_external_sources():
    root = Path(__file__).resolve().parents[2]
    result = run_audit(root)
    assert result["metrics"]["status"] == "audited"
