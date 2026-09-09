from pathlib import Path

import polars as pl

from wikidata.silver import canonical_parents as sg

REGIONAL_CLASSIFICATION_ROWS = [
    # rock music -> popular music: popular music is a real genre (is_regional_overview=False)
    {
        "item_id": "Q11399",
        "item_label": "rock music",
        "parent_id": "Q9778",
        "parent_label": "popular music",
        "item_url": "https://www.wikidata.org/wiki/Q11399",
        "parent_url": "https://www.wikidata.org/wiki/Q9778",
        "is_regional_overview": False,
        "classification_reason": None,
        "is_regional": False,
        "regional_reason": None,
        "relation_type": "P279",
    },
    # popular music: root item, no parent
    {
        "item_id": "Q9778",
        "item_label": "popular music",
        "parent_id": None,
        "parent_label": None,
        "item_url": "https://www.wikidata.org/wiki/Q9778",
        "parent_url": None,
        "is_regional_overview": False,
        "classification_reason": None,
        "is_regional": False,
        "regional_reason": None,
        "relation_type": None,
    },
    # opera -> composed musical work: parent isn't in the genre extension at all
    {
        "item_id": "Q1344",
        "item_label": "opera",
        "parent_id": "Q207628",
        "parent_label": "composed musical work",
        "item_url": "https://www.wikidata.org/wiki/Q1344",
        "parent_url": "https://www.wikidata.org/wiki/Q207628",
        "is_regional_overview": False,
        "classification_reason": None,
        "is_regional": False,
        "regional_reason": None,
        "relation_type": "P279",
    },
    # some subgenre -> music of Kenya: parent is in the genre extension but tagged non-genre
    {
        "item_id": "Q999999",
        "item_label": "some subgenre",
        "parent_id": "Q3868594",
        "parent_label": "music of Kenya",
        "item_url": "https://www.wikidata.org/wiki/Q999999",
        "parent_url": "https://www.wikidata.org/wiki/Q3868594",
        "is_regional_overview": False,
        "classification_reason": None,
        "is_regional": True,
        "regional_reason": "direct",
        "relation_type": "P279",
    },
    {
        "item_id": "Q3868594",
        "item_label": "music of Kenya",
        "parent_id": None,
        "parent_label": None,
        "item_url": "https://www.wikidata.org/wiki/Q3868594",
        "parent_url": None,
        "is_regional_overview": True,
        "classification_reason": "regional_overview",
        "is_regional": True,
        "regional_reason": "seed",
        "relation_type": None,
    },
]


def _write_main_parent_selection(tmp_path: Path) -> Path:
    main_parent_selection_path = tmp_path / "5_main_parent_selection.parquet"
    pl.DataFrame(REGIONAL_CLASSIFICATION_ROWS).write_parquet(main_parent_selection_path)
    return main_parent_selection_path


def test_flag_canonical_parents_marks_parent_status(tmp_path: Path) -> None:
    main_parent_selection_path = _write_main_parent_selection(tmp_path)
    output_dir = tmp_path / "silver"

    result = sg.flag_canonical_parents(main_parent_selection_path, output_dir)

    assert result == output_dir / "6_canonical_parents.parquet"
    parent_is_canonical_by_item = {
        row["item_id"]: row["parent_is_canonical"] for row in pl.read_parquet(result).to_dicts()
    }
    assert parent_is_canonical_by_item == {
        "Q11399": True,  # parent (popular music) is_regional_overview=False
        "Q9778": None,  # root item, no parent
        "Q1344": False,  # parent not in the genre extension at all
        "Q999999": False,  # parent in the genre extension but is_regional_overview=True
        "Q3868594": None,  # root item, no parent
    }


def test_flag_canonical_parents_creates_output_dir(tmp_path: Path) -> None:
    main_parent_selection_path = _write_main_parent_selection(tmp_path)
    output_dir = tmp_path / "does" / "not" / "exist"

    sg.flag_canonical_parents(main_parent_selection_path, output_dir)

    assert output_dir.is_dir()
