import polars as pl

from gold.genre_tree_builder import build_genre_tree

TREE_ROWS = [
    {"item_id": "Q1", "item_label": "rock", "parent_id": None},
    {"item_id": "Q2", "item_label": "punk rock", "parent_id": "Q1"},
    {"item_id": "Q3", "item_label": "hardcore punk", "parent_id": "Q2"},
    {"item_id": "Q4", "item_label": "pop rock", "parent_id": "Q1"},
    {"item_id": "Q5", "item_label": "jazz", "parent_id": None},
]


def _hierarchy() -> pl.DataFrame:
    return pl.DataFrame(TREE_ROWS)


def test_build_genre_tree_nests_children_under_parent() -> None:
    tree = build_genre_tree(_hierarchy())

    rock = next(node for node in tree["tree"] if node["name"] == "rock")
    child_names = {child["name"] for child in rock["children"]}
    assert child_names == {"punk rock", "pop rock"}

    punk_rock = next(child for child in rock["children"] if child["name"] == "punk rock")
    assert punk_rock["children"] == [{"name": "hardcore punk", "children": []}]


def test_build_genre_tree_handles_multiple_roots() -> None:
    tree = build_genre_tree(_hierarchy())

    root_names = {node["name"] for node in tree["tree"]}
    assert root_names == {"rock", "jazz"}
