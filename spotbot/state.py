"""Paper ledger on disk. Live mode uses the same file after a real fill."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Position:
    symbol: str
    entry_micro: int
    peak_micro: int
    quote_micro: int
    base_atoms: int
    reason: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> "Position":
        return cls(
            symbol=str(raw["symbol"]),
            entry_micro=int(raw["entry_micro"]),
            peak_micro=int(raw["peak_micro"]),
            quote_micro=int(raw["quote_micro"]),
            base_atoms=int(raw["base_atoms"]),
            reason=str(raw["reason"]),
        )


@dataclass
class Book:
    cash_micro: int
    positions: list[Position]
    realized_micro: int

    def to_json(self) -> dict[str, object]:
        return {
            "cash_micro": self.cash_micro,
            "realized_micro": self.realized_micro,
            "positions": [pos.to_json() for pos in self.positions],
        }


def load_book(path: Path, paper_cash_micro: int) -> Book:
    if not path.exists():
        return Book(cash_micro=paper_cash_micro, positions=[], realized_micro=0)
    raw = json.loads(path.read_text(encoding="utf-8"))
    positions = [Position.from_json(item) for item in raw.get("positions", [])]
    return Book(
        cash_micro=int(raw["cash_micro"]),
        positions=positions,
        realized_micro=int(raw.get("realized_micro", 0)),
    )


def save_book(path: Path, book: Book) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book.to_json(), indent=2), encoding="utf-8")
