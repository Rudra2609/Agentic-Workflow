import pytest
from solution import BankAccount, InsufficientFunds

def test_flow():
    a = BankAccount("ann", 100)
    a.deposit(50); a.withdraw(30)
    assert a.balance == 120
    assert a.history == [("deposit", 50), ("withdraw", 30)]

def test_insufficient():
    a = BankAccount("bob")
    with pytest.raises(InsufficientFunds):
        a.withdraw(1)
    assert a.balance == 0 and a.history == []
    assert issubclass(InsufficientFunds, Exception)

def test_invalid_amounts():
    a = BankAccount("c", 10)
    for bad in [0, -5]:
        with pytest.raises(ValueError):
            a.deposit(bad)
        with pytest.raises(ValueError):
            a.withdraw(bad)
    with pytest.raises(ValueError):
        BankAccount("d", -1)

def test_balance_read_only():
    a = BankAccount("e", 5)
    with pytest.raises(AttributeError):
        a.balance = 1000
