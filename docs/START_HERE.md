# С чего начать (обычным языком)

**Не финансовый совет.** Это исследовательский спот-бот, не «включил и заработал».

---

## Что это?

Программа, которая умеет:

- крутить **бумажную** торговлю (по умолчанию);
- при жёстких флагах — слать спот-ордера на KuCoin;
- вести **три отдельные кассы** (major / alt / meme): депозит делится поровну, прибыль остаётся в своём рукаве.

Сейчас по протоколу:

> **Новые покупки выключены.** Стратегия MEASUREMENT v1 на текущей ленте остановлена (нет края).  
> Флаг `SPOT_ENTRIES` процесс **не включает**.  
> Уже открытую монету бот всё ещё может **продать** по правилам.

Статус: [`PROTOCOL_STATUS.md`](PROTOCOL_STATUS.md).

---

## Быстрый безопасный запуск (бумага)

```powershell
cd absolute-trading-bot-final
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python -m spotbot --once --sleeves
```

Страница наблюдения (только смотреть, ордера с неё не шлёт):

```powershell
.\.venv\Scripts\python -m spotbot.ops_main
```

Обычно `http://127.0.0.1:19280/`.

---

## Что НЕ делать

1. Не ставить `SPOT_ENTRIES=1` «чтобы наконец купило» — протокол это запрещает, пока нет принятого нового измерения с уликами.
2. Не путать с **Market Radar** (`dup-market-radar`) — это другой продукт (другие сигналы, другие рукава секторов).
3. Не включать `SPOT_LIVE=1` без понимания [`TRADING.md`](TRADING.md) и [`BOOK.md`](BOOK.md).

---

## Research-ветки (для любопытных)

На `main` стратегия входов не «зелёная». Отдельные ветки:

| Ветка | Честный итог |
|-------|----------------|
| `research/trend-following` | Гейт **FAIL** |
| `research/v2-holdout` | Кандидат A3 заморожен; blind holdout был **NOT_READY** (мало пост-cut ленты) |
| Tag `v2-candidate-a3-freeze` | Снимок заморозки |

Это **не** разрешение торговать на деньги.

---

## Если нужен «живой» автосканер рынка

Смотрите [`dup-market-radar`](https://github.com/Gruver87/dup-market-radar) и его [`START_HERE`](https://github.com/Gruver87/dup-market-radar/blob/main/docs/START_HERE.md).

---

## English one-liner

Paper-first KuCoin spot research bot. MEASUREMENT v1 stopped → no new buys. Sleeves keep their own P&L. Not Radar; not a profit promise.
