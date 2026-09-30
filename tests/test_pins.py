import pytest

from accounts.pins import LOOKS_LIKE_PHONE, TOO_EASY, WRONG_FORMAT, pin_problem


@pytest.mark.parametrize(
    "pin",
    [
        "000000",
        "111111",
        "123456",
        "234567",
        "456789",
        "987654",
        "654321",
        "121212",
        "101010",
        "123123",
        "112233",
        "111222",
        "123321",
        "147258",
        "159753",
        "102030",
    ],
)
def test_easy_pins_are_refused(pin):
    assert pin_problem(pin) == TOO_EASY


@pytest.mark.parametrize("pin", ["", "12345", "1234567", "12a456", "48 291"])
def test_pins_must_be_exactly_six_digits(pin):
    assert pin_problem(pin) == WRONG_FORMAT


@pytest.mark.parametrize("pin", ["482916", "730259", "905184", "271828"])
def test_ordinary_pins_are_accepted(pin):
    assert pin_problem(pin) is None


def test_end_of_own_phone_number_is_refused():
    assert pin_problem("550123", phone="(740) 555-0123") == LOOKS_LIKE_PHONE
    assert pin_problem("550123", phone="(740) 555-9999") is None
