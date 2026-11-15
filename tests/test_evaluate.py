"""evaluate.oracle: the aggregator fed gold edge effects reads every gold-answered item as answered."""

from __future__ import annotations

from camoreasoning.config import DEVSETS_DIR, Settings
from camoreasoning.contracts import GoldItem
from camoreasoning.evaluate import load_devsets, oracle


def unsigned_only(gold):
    return [g for g in gold if g.status == "answered" and g.edge_effects and all(e is None for _, e in g.edge_effects)]


def test_unsigned_gold_votes_read_as_unclear(graph):
    """#61: an answered item whose gold edges are all unsigned is D2's `unclear`, not no_evidence."""
    eid = next(iter(graph.edges))
    item = GoldItem("t", "q", "answered", "unclear", edge_ids=(eid,), edge_effects=((eid, None),))
    assert oracle([item], Settings())["direction_accuracy"] == 1.0


def test_oracle_reads_every_unsigned_only_dev_item():
    """The 12 node-level dev items gold labels `unclear` from unsigned edges alone."""
    items = unsigned_only(load_devsets([DEVSETS_DIR / "gold_annotated.yaml"], "dev"))
    assert len(items) >= 12 and {g.direction for g in items} == {"unclear"}
    assert oracle(items, Settings())["direction_accuracy"] == 1.0
