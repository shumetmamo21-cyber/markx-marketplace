from markx.core.codes import (
    ORDER_CODE_ALPHABET,
    is_order_code,
    new_numeric_code,
    new_order_code,
    normalize_order_code,
)


def test_order_code_shape() -> None:
    for _ in range(500):
        code = new_order_code()
        assert code.startswith("MX-")
        assert len(code) == 9
        assert all(c in ORDER_CODE_ALPHABET for c in code[3:])
        assert is_order_code(code)


def test_alphabet_has_no_lookalike_characters() -> None:
    for confusable in "0O1IL2Z5S8B":
        assert confusable not in ORDER_CODE_ALPHABET
    assert len(set(ORDER_CODE_ALPHABET)) == len(ORDER_CODE_ALPHABET)


def test_blueprint_example_is_a_valid_code() -> None:
    assert is_order_code("MX-7K3F9Q")


def test_codes_are_not_repeated_in_a_small_sample() -> None:
    codes = {new_order_code() for _ in range(2000)}
    assert len(codes) > 1990  # 25**6 possibilities; collisions here would mean a broken RNG


def test_normalises_how_people_type_a_code() -> None:
    assert normalize_order_code("mx-7k3f9q") == "MX-7K3F9Q"
    assert normalize_order_code("MX 7K3F9Q") == "MX-7K3F9Q"
    assert normalize_order_code("7k3f9q") == "MX-7K3F9Q"
    assert normalize_order_code("  mx7k3f9q ") == "MX-7K3F9Q"


def test_rejects_malformed_codes() -> None:
    for bad in ["", "MX-", "MX-7K3F9", "MX-7K3F9QQ", "MX-0O1IL2", "AB-7K3F9Q", "MX-7K3F9!"]:
        assert not is_order_code(bad)
    assert normalize_order_code("MX-0O1IL2") is None
    assert normalize_order_code("hello") is None


def test_numeric_code_keeps_leading_zeros() -> None:
    for _ in range(300):
        code = new_numeric_code(6)
        assert len(code) == 6
        assert code.isdigit()
