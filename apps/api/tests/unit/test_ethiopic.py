import pytest

from markx.core.ethiopic import (
    detect_script,
    normalize_text,
    skeleton_key,
    skeleton_keys,
    tokenize,
)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # the four pairs blueprint P.1 says must match
        ("ሰላም", "ሠላም"),
        ("ዓለም", "አለም"),
        ("ጸሀይ", "ፀሐይ"),
        ("ኃይል", "ሀይል"),
        # further same-sound spellings
        ("ሐኪም", "ሀኪም"),
        ("ሥራ", "ስራ"),
        ("ዕቃ", "እቃ"),
        ("ፀጉር", "ጸጉር"),
        ("ሃይማኖት", "ሀይማኖት"),
        ("ኣዲስ", "አዲስ"),
    ],
)
def test_same_sound_spellings_normalise_identically(a: str, b: str) -> None:
    assert normalize_text(a) == normalize_text(b)


def test_different_words_stay_different() -> None:
    assert normalize_text("ስልክ") != normalize_text("ስልኮች")
    assert normalize_text("ሰላም") != normalize_text("ሰለም")
    # ለ and ረ are different sounds and must not merge
    assert normalize_text("ለም") != normalize_text("ረም")


def test_normalisation_is_idempotent() -> None:
    for text in ["ፀሐይ ዓለም", "Samsung  GALAXY", "ሠላም፣ ዓለም።"]:
        once = normalize_text(text)
        assert normalize_text(once) == once


def test_lowercases_and_collapses_latin_text() -> None:
    assert normalize_text("  Samsung   GALAXY A16 ") == "samsung galaxy a16"


def test_punctuation_becomes_one_space() -> None:
    assert normalize_text("ሰላም፣ዓለም።") == normalize_text("ሰላም አለም")
    assert normalize_text("ስልክ፡ዋጋ") == "ስልክ ዋጋ"
    assert normalize_text("wi-fi / 128GB+") == "wi fi 128gb"
    assert normalize_text("snake_case") == "snake case"


def test_composed_and_decomposed_forms_match() -> None:
    assert normalize_text("Café") == normalize_text("Café")


def test_empty_and_punctuation_only_input() -> None:
    assert normalize_text("") == ""
    assert normalize_text("  ።፣!? ") == ""
    assert tokenize("") == []


def test_detects_script() -> None:
    assert detect_script("ስልክ") == "ethiopic"
    assert detect_script("silk") == "latin"
    assert detect_script("Samsung ስልክ") == "ethiopic"
    assert detect_script("12345") == "latin"


def test_blueprint_skeleton_example() -> None:
    # blueprint D.24: "silk", "selk" and "slk" all find ስልክ
    assert skeleton_key("ስልክ") == "slk"
    assert skeleton_key("silk") == "slk"
    assert skeleton_key("selk") == "slk"
    assert skeleton_key("slk") == "slk"


@pytest.mark.parametrize(
    ("amharic", "latin"),
    [
        ("ሳምሰንግ", "samsung"),
        ("ጋላክሲ", "galaxy"),
        ("ላፕቶፕ", "laptop"),
        ("ቻርጅ", "charj"),
        ("ቴክኖ", "tecno"),
        ("ቴክኖ", "tekno"),
        ("ኖኪያ", "nokia"),
        ("ማክስ", "max"),
        ("ራውተር", "router"),
        ("ቀለም", "qelem"),
        ("ጠረጴዛ", "terepeza"),
        ("ፀሐይ", "tsehay"),
    ],
)
def test_amharic_and_latin_spellings_share_a_skeleton(amharic: str, latin: str) -> None:
    assert skeleton_key(amharic) == skeleton_key(latin)


def test_spelling_variants_share_a_skeleton() -> None:
    assert skeleton_key("chargerr") == skeleton_key("charger")
    assert skeleton_key("sellk") == skeleton_key("silk")
    assert skeleton_key("phone") == skeleton_key("fone")
    assert skeleton_key("Tecno") == skeleton_key("tekno")
    assert skeleton_key("cell") == skeleton_key("sel")
    assert skeleton_key("kitchen") == skeleton_key("kichen") == "kcn"
    # one consonant is too little to match on
    assert skeleton_key("watch") is None


def test_known_limit_english_soft_g_is_not_merged_with_j() -> None:
    # "charger" is spelled with g but pronounced j; ቻርጀር uses ጀ. Skeletons follow
    # spelling, so these differ. Product aliases cover such words instead.
    assert skeleton_key("charger") == "crgr"
    assert skeleton_key("ቻርጀር") == "crjr"


def test_sh_and_ch_sounds_are_kept_apart_from_s_and_k() -> None:
    assert skeleton_key("ሸሚዝ") == skeleton_key("shemiz") == "shmz"
    assert skeleton_key("ሸሚዝ") != skeleton_key("semiz")
    assert skeleton_key("ቻይና") == skeleton_key("china") == "cn"


def test_model_codes_and_short_words_have_no_skeleton() -> None:
    assert skeleton_key("a16") is None
    assert skeleton_key("128gb") is None
    assert skeleton_key("a") is None
    assert skeleton_key("io") is None  # only vowels
    assert skeleton_key("") is None
    assert skeleton_key("two words") is None


def test_skeleton_keys_for_a_phrase() -> None:
    assert skeleton_keys("Samsung Galaxy A16") == ["smsng", "glks"]
    assert skeleton_keys("ሳምሰንግ ስልክ") == ["smsng", "slk"]
    assert skeleton_keys("silk silk selk") == ["slk"]
