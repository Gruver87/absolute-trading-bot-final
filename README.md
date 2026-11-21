# Спот-бот KuCoin

[![ci](https://github.com/Gruver87/absolute-trading-bot-final/actions/workflows/ci.yml/badge.svg)](https://github.com/Gruver87/absolute-trading-bot-final/actions/workflows/ci.yml)

Бумажный спот по умолчанию. Ордер на KuCoin уходит только если в `.env` стоит ровно `SPOT_LIVE=1` и процесс запущен с `--live`. Это не обещание прибыли и не прогноз. Цепь DUP бот не импортирует. Лицензия — все права у автора, это не MIT.

**Research branches (не main / не unlock):** [`research/v2-holdout`](https://github.com/Gruver87/absolute-trading-bot-final/tree/research/v2-holdout) (A3 freeze, holdout NOT_READY until post-cut tape), [`research/trend-following`](https://github.com/Gruver87/absolute-trading-bot-final/tree/research/trend-following) (Donchian gate FAIL). Tag `v2-candidate-a3-freeze`.

Повтор без `--once` крутит цикл раз в `SPOT_INTERVAL_SEC` (по умолчанию 60 секунд).

## Решение

Новые покупки выключены. Стратегия MEASUREMENT v1 на текущей ленте остановлена (нет края); `SPOT_ENTRIES=1` процесс не включает. Актуальный статус протокола — [docs/PROTOCOL_STATUS.md](docs/PROTOCOL_STATUS.md). Цикл продаёт только уже открытую монету.

Исторические цифры окон и модель прогона v1 — в [docs/MEASUREMENT.md](docs/MEASUREMENT.md) (не переписывать молча).

## Деньги

Суммы котировки хранятся целыми: `1 USDT = 1_000_000`. Float и булево значение на этом пути отвергаются. Цена одной монеты хранится в `1e-12` USDT, касса по-прежнему в миллионных: так стоп 3.5% существует и на дешёвой монете. Все пороги ниже — в bps, `100 bps = 1%`.

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python -m spotbot --once --sleeves
```

| Команда | Что делает |
|---|---|
| `python -m spotbot --once` | Один бумажный цикл RSI |
| `python -m spotbot --mode liquidity --once` | Один цикл ликвидности, отдельная книга |
| `python -m spotbot --sleeves --once` | Три рукава, у каждого своя книга |
| `python -m spotbot.ops_main` | Только страница наблюдения |
| `python -m spotbot.replay_main --symbol BTCUSDT` | Прогон правила по свечам, без ордеров |
| `python scripts/unseen_gate.py` | Готовность невиденной ленты (гейта); без `--run` свечи не гоняет; пишет строку в `data/gate_history.jsonl` |
| `python scripts/unseen_gate.py --run` | Два окна гейта через `replay_main`; входы не включает; журналирует восемь медиан |
| `python scripts/kucoin_keyed_smoke.py` | Ключи: публичные часы + `GET /accounts`; ордера не ставит; при `SPOT_LIVE=1` отказывает |
| `python scripts/bot_gate.py` | Honesty needles (PROTOCOL_STATUS / Agent Skills) — не edge claim |
| `.\scripts\test_all.ps1` | `bot_gate` + pytest; входы не включает |
| `.\scripts\link_agent_skills.ps1` | Зеркало Cursor skills из `dup-agent-skills` |
| `python -m pytest tests/ -q` | Проверка правил. Корень проекта на пути импорта |

Ключи KuCoin в исходниках не лежат. Токен Telegram процесс не загружает. Публичные свечи работают без ключей.

## KuCoin: что важно оператору

- В `.env` для live нужны **три** секрета: `KUCOIN_API_KEY`, `KUCOIN_API_SECRET`, `KUCOIN_API_PASSPHRASE`, плюс обычно `KUCOIN_API_KEY_VERSION=2` (подпись passphrase как у KuCoin API v2).
- В конфиге и книге пары остаются без дефиса (`BTCUSDT`). На провод KuCoin клиент сам шлёт `BTC-USDT`.
- Живые ордера идут через Spot HF (`/api/v1/hf/orders/sync`, fills через `/api/v1/hf/fills`). Id ордера KuCoin — hex, не только цифры.
- Свечи: `type=5min` и время в **секундах**; на странице до 1500 баров за запрос. Публичный вес свечей выше, чем у старого MEXC-пути — при частых `replay`/`unseen_gate --run` не крутите цикл без паузы.
- HTTP 429 по-прежнему останавливает цикл; ждём `Retry-After` (минимум две минуты, если заголовок не разобран).

## Куда смотреть

| Файл | О чём |
|---|---|
| [docs/PROTOCOL_STATUS.md](docs/PROTOCOL_STATUS.md) | Статус протокола: стоп v1, черновик v2 в Project Context |
| [docs/TRADING.md](docs/TRADING.md) | Рукава, входы, выходы, сверка цен, дневной предел, фильтры пар |
| [docs/BOOK.md](docs/BOOK.md) | Книги, живая заявка, лимит биржи, страница наблюдения |
| [docs/MEASUREMENT.md](docs/MEASUREMENT.md) | Исторические окна v1 и как считается прогон |
| [docs/REFUSALS.md](docs/REFUSALS.md) | Что процесс отвергает до того, как двигать кассу |
| [docs/AGENT_SKILLS.md](docs/AGENT_SKILLS.md) | Cursor skills (стоп v1 / без silent retune) · `.\scripts\link_agent_skills.ps1` |

## Переменные

Пустые ключи в `.env.example`.

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `KUCOIN_API_KEY`, `KUCOIN_API_SECRET`, `KUCOIN_API_PASSPHRASE` | пусто | Нужны только для живых ордеров |
| `KUCOIN_API_KEY_VERSION` | 2 | Версия ключа KuCoin (1 или 2) |
| `SPOT_SYMBOLS` | BTC, ETH, SOL | Список бумажного цикла без `--sleeves` |
| `SPOT_PAPER_CASH_USDT` | 1000 | Стартовая бумажная касса |
| `SPOT_INTERVAL_SEC` | 60 | Пауза между циклами |
| `SPOT_LIVE` | 0 | Живые ордера только вместе с `--live` и значением `1` |
| `SPOT_ENTRIES` | 0 | Не включает входы. Знак на соседних окнах не держится |
| `SPOT_KILL` | 0 | `1` или файл `data/STOP` — пауза новых покупок; выходы идут |
| `SPOT_TAKER_BPS` | 5 | Запасная комиссия, если у пары своей ещё нет |
| `SPOT_DAILY_LOSS_BPS` | 500 | Дневной предел убытка, 5% |
| `SPOT_DRAWDOWN_BPS` | 1000 | Просадка от пика кассы, 10% |
| `SPOT_STOP_COOLDOWN_SEC` | 900 | Пауза входов после стопа |
| `SPOT_STOP_LOCK_COUNT` | 3 | Сколько стопов одной пары запирают её |
| `SPOT_STOP_LOCK_SEC` | 14400 | На сколько секунд пара запирается |
| `SPOT_SPREAD_BPS` | 30 | Шире этого спреда покупка не идёт |
| `SPOT_OPS_PORT` | 19280 | Страница наблюдения, только localhost |
