"""Owner check (guide 16.4): the scorer reads the graded CSV, the drop histogram sums saved run output."""
import csv

from tkg.reporting import OWNER_CHECK_COLUMNS, drop_histogram, owner_check_score


def write_csv(path, marks):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(OWNER_CHECK_COLUMNS)
        for i, (mark, note) in enumerate(marks):
            w.writerow([f"evt{i:05d}x", "title", "http://u", "company", f"item {i}", mark, note])


def test_precision_counts_y_over_graded_rows_and_lists_the_n_notes(tmp_path):
    path = tmp_path / "c.csv"
    write_csv(path, [("Y", ""), ("y", ""), ("Y", ""), ("N", "wrong direction"), ("", "")])
    res = owner_check_score(str(path))
    assert (res["y"], res["n"], res["ungraded"]) == (3, 1, 1)
    assert res["precision"] == 0.75 and res["passes"] is False
    assert res["n_notes"][0][2] == "wrong direction"


def test_the_gate_is_85_percent(tmp_path):
    path = tmp_path / "c.csv"
    write_csv(path, [("Y", "")] * 17 + [("N", "x")] * 3)
    assert owner_check_score(str(path))["passes"] is True               # 17/20 = 85%


def test_an_ungraded_file_has_no_precision(tmp_path):
    path = tmp_path / "c.csv"
    write_csv(path, [("", "")] * 4)
    res = owner_check_score(str(path))
    assert res["precision"] is None and res["passes"] is None and res["ungraded"] == 4


def test_drop_histogram_sums_the_logged_dicts(tmp_path):
    (tmp_path / "backfill_a.txt").write_text("x\n  Validation drops: {'evidence_not_found': 3, 'summary_advice_word': 1}\n", encoding="utf-8")
    (tmp_path / "backfill_b.txt").write_text("  Validation drops: {'evidence_not_found': 2}\n  Validation drops: {}\n", encoding="utf-8")
    hist = drop_histogram(str(tmp_path / "backfill_*.txt"))
    assert hist == {"evidence_not_found": 5, "summary_advice_word": 1}
