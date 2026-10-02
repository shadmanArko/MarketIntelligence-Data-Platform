"""Human review of match pairs, and precision / recall of the resolution against those labels (gate 2)."""

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from mip.db import connect

console = Console()


def review(n: int = 20, domain: str = "listing") -> None:
    with connect() as c:
        rows = c.execute(
            "SELECT pair_id, left_id, right_id, match_prob, features FROM ops.match_review"
            " WHERE domain=%s AND label IS NULL ORDER BY random() LIMIT %s", (domain, n)).fetchall()
        if not rows:
            console.print("[green]nothing left to review[/]")
            return
        for i, r in enumerate(rows, 1):
            f = r["features"] or {}
            t = Table(title=f"pair {i}/{len(rows)}   model p={r['match_prob']:.3f}   distance {f.get('distance_m')} m",
                      show_lines=True)
            t.add_column("")
            t.add_column(r["left_id"][:40])
            t.add_column(r["right_id"][:40])
            for k in ("name", "platform", "address", "phone", "domain"):
                v = f.get(k) or [None, None]
                t.add_row(k, str(v[0] or "—"), str(v[1] or "—"))
            console.print(t)
            ans = Prompt.ask("same business?", choices=["y", "n", "s", "q"], default="s")
            if ans == "q":
                break
            if ans == "s":
                continue
            c.execute("UPDATE ops.match_review SET label=%s, labelled_by=current_user, labelled_at=now()"
                      " WHERE pair_id=%s", (ans == "y", r["pair_id"]))
    evaluate()


def evaluate() -> dict:
    """A labelled pair is predicted 'match' when both listings ended up in the same business."""
    with connect() as c:
        rows = c.execute("""
            SELECT r.label, (a.business_id = b.business_id) AS predicted, r.match_prob
            FROM ops.match_review r
            JOIN ops.business_assignment a ON a.listing_key = r.left_id
            JOIN ops.business_assignment b ON b.listing_key = r.right_id
            WHERE r.domain = 'listing' AND r.label IS NOT NULL""").fetchall()
        tp = sum(1 for r in rows if r["label"] and r["predicted"])
        fp = sum(1 for r in rows if not r["label"] and r["predicted"])
        fn = sum(1 for r in rows if r["label"] and not r["predicted"])
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        out = {"labelled": len(rows), "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
               "gate_2_passed": bool(precision is not None and precision >= 0.95 and len(rows) >= 150)}
        c.execute("UPDATE ops.resolution_runs SET precision_lab=%s, recall_lab=%s WHERE resolution_run ="
                  " (SELECT resolution_run FROM ops.resolution_runs ORDER BY started_at DESC LIMIT 1)",
                  (precision, recall))
    left = 0
    with connect() as c:
        left = c.execute("SELECT count(*) n FROM ops.match_review WHERE label IS NULL").fetchone()["n"]
    colour = "green" if out["gate_2_passed"] else "yellow"
    console.print(f"[{colour}]labels {out['labelled']} (unlabelled {left}) | precision {precision} | recall {recall}"
                  f" | gate 2 {'PASSED' if out['gate_2_passed'] else 'not yet'}[/]")
    return out
