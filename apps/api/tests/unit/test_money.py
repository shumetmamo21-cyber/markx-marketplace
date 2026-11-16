import pytest

from markx.core.money import Money


def test_formats_whole_birr_in_both_languages() -> None:
    money = Money(1_250_000)
    assert money.format("en") == "ETB 12,500"
    assert money.format("am") == "12,500 ብር"


def test_formats_santim_only_when_present() -> None:
    assert Money(1_250_050).format("en") == "ETB 12,500.50"
    assert Money(1_250_005).format("am") == "12,500.05 ብር"
    assert Money(0).format("en") == "ETB 0"
    assert Money(99).format("en") == "ETB 0.99"


def test_formats_negative_amounts() -> None:
    assert Money(-15_000).format("en") == "-ETB 150"
    assert Money(-15_000).format("am") == "-150 ብር"


@pytest.mark.parametrize("bad", [12.5, "100", None, True, 1.0])
def test_rejects_anything_but_an_integer(bad: object) -> None:
    with pytest.raises(TypeError):
        Money(bad)  # type: ignore[arg-type]


def test_rejects_unknown_currency() -> None:
    with pytest.raises(ValueError, match="unsupported currency"):
        Money(100, "USD")


def test_arithmetic_is_exact() -> None:
    assert Money(10) + Money(20) == Money(30)
    assert Money(30) - Money(20) == Money(10)
    assert Money(1999) * 3 == Money(5997)
    # The classic float failure does not exist in integer santim.
    assert Money(10) + Money(20) == Money(30)


def test_multiplying_by_a_fraction_is_refused() -> None:
    with pytest.raises(TypeError):
        Money(100) * 1.5  # type: ignore[operator]


def test_comparison() -> None:
    assert Money(1) < Money(2)
    assert Money(2) <= Money(2)
    assert not Money(3) < Money(2)


@pytest.mark.parametrize(
    ("amount", "bps", "expected"),
    [
        (250_000, 700, 17_500),  # blueprint J.8: 7% of ETB 2,500 is ETB 175
        (500_000, 300, 15_000),  # blueprint J.8: 3% of ETB 5,000 is ETB 150
        (250_000, 0, 0),
        (250_000, 10_000, 250_000),
        (1, 5_000, 1),  # half a santim rounds up
        (1, 4_999, 0),
        (3, 5_000, 2),  # 1.5 rounds up to 2
        (333, 3_333, 111),  # 110.9889 rounds to 111
    ],
)
def test_portion_in_basis_points_rounds_half_up(amount: int, bps: int, expected: int) -> None:
    assert Money(amount).portion_bps(bps) == Money(expected)


@pytest.mark.parametrize("bps", [-1, 10_001, 2.5, True])
def test_portion_rejects_bad_basis_points(bps: object) -> None:
    with pytest.raises(ValueError, match="basis points must be"):
        Money(100).portion_bps(bps)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "santim"),
    [
        ("12500", 1_250_000),
        ("12,500", 1_250_000),
        ("12,500.50", 1_250_050),
        ("0.5", 50),
        ("0.05", 5),
        (" 1,234,567.89 ", 123_456_789),
    ],
)
def test_parses_what_a_seller_types(text: str, santim: int) -> None:
    assert Money.from_birr_text(text) == Money(santim)


@pytest.mark.parametrize("text", ["", "abc", "12.345", "1,25", "-5", "12,5000", "1e3", "12.", ".5"])
def test_rejects_malformed_birr_text(text: str) -> None:
    with pytest.raises(ValueError, match="not a valid birr amount"):
        Money.from_birr_text(text)


def test_mixing_currencies_is_refused() -> None:
    # Only ETB exists today; the guard is exercised through the private check.
    a = Money(1)
    object.__setattr__(a, "currency", "XXX")
    with pytest.raises(ValueError, match="currency mismatch"):
        _ = a + Money(1)
