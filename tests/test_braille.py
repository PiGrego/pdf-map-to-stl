import pytest

from pdf_map_to_stl.braille import NUMBER_SIGN, BrailleSpec, dot_centres, to_cells, width_mm, wrap


def test_letters():
    assert to_cells("key") == ["13", "15", "13456"]


def test_capitals_and_accents_are_plain_letters():
    assert to_cells("Città") == to_cells("citta")


def test_numbers_get_a_number_sign_and_letters_after_them_a_letter_sign():
    assert to_cells("12") == [NUMBER_SIGN, "1", "12"]
    assert to_cells("2b") == [NUMBER_SIGN, "12", "56", "12"]
    assert to_cells("2 b") == [NUMBER_SIGN, "12", "", "12"]


def test_unknown_characters_are_dropped():
    assert to_cells("a#b") == ["1", "12"]


def test_wrap_breaks_at_spaces():
    assert wrap("open land with trees", 10) == ["open land", "with trees"]


def test_dot_positions_follow_standard_spacing():
    spec = BrailleSpec()
    # "l" = dots 1, 2, 3: one column, 2.5 mm apart, going down from the top edge.
    pts = dot_centres("l", spec, 0.0, 10.0)
    assert [round(y, 3) for _, y in pts] == [9.25, 6.75, 4.25]
    # second cell starts 6 mm to the right
    (x1, _), (x2, _) = dot_centres("aa", spec, 0.0, 10.0)
    assert x2 - x1 == pytest.approx(6.0)
    assert width_mm("aa", spec) == pytest.approx(6.0 + 2.5 + 1.5)
