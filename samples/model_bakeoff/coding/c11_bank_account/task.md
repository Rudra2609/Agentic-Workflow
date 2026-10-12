Write a class `BankAccount` and an exception class `InsufficientFunds(Exception)`.

- `BankAccount(owner: str, balance: float = 0)` — raise `ValueError` if the starting balance is negative.
- `deposit(amount)` and `withdraw(amount)`: raise `ValueError` if amount <= 0;
  `withdraw` raises `InsufficientFunds` if amount is larger than the balance (balance unchanged).
- `balance` is a read-only property.
- `history` is a list of `("deposit", amount)` / `("withdraw", amount)` tuples for successful operations only, in order.
