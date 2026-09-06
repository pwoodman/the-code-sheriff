from quality_gates.models import Finding
from quality_gates.review.ledger import update_ledger


def test_ledger_keeps_omitted_finding_as_not_rechecked(tmp_path) -> None:
    finding = Finding(gate="review", rule="logic", path="app.py", line=3, message="bug")
    update_ledger(tmp_path, [finding])
    ledger = update_ledger(tmp_path, [])

    assert next(iter(ledger["findings"].values()))["state"] == "not-rechecked"


def test_ledger_tracks_verified_fixed_and_suppressed(tmp_path) -> None:
    from quality_gates.review.ledger import mark_suppressed, mark_verified_fixed

    finding = Finding(gate="review", rule="logic", path="app.py", line=3, message="bug")
    update_ledger(tmp_path, [finding])

    mark_verified_fixed(tmp_path, finding)
    ledger = update_ledger(tmp_path, [])
    assert next(iter(ledger["findings"].values()))["state"] == "verified-fixed"

    mark_suppressed(tmp_path, finding, "approved exception")
    ledger = update_ledger(tmp_path, [])
    entry = next(iter(ledger["findings"].values()))
    assert entry["state"] == "suppressed"
    assert entry["suppression_reason"] == "approved exception"
