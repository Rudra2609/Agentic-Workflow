class InsufficientFunds(Exception):
    pass
class BankAccount:
    def __init__(self, owner, balance=0):
        if balance < 0:
            raise ValueError("negative balance")
        self.owner = owner
        self._balance = balance
        self.history = []
    @property
    def balance(self):
        return self._balance
    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("amount")
        self._balance += amount
        self.history.append(("deposit", amount))
    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("amount")
        if amount > self._balance:
            raise InsufficientFunds(amount)
        self._balance -= amount
        self.history.append(("withdraw", amount))
