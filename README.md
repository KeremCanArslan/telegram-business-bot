# telegram-business-bot

A Telegram bot for small restaurants and cafés: customers browse the menu, order with a cart, book a table and get answers to common questions. The owner is notified instantly in Telegram, and every order and booking is saved to CSV (opens in Excel). The bot interface is in Turkish.

## Features

- Menu by category, cart with quantities, delivery rules (minimum order, delivery fee)
- Table booking with available time slots and a capacity check per slot
- FAQ answered by keyword matching
- "Message the owner" option
- Instant owner notification for orders, bookings and messages
- All business details in one file: `isletme.json` (name, address, menu, opening hours, capacity, FAQ). Adapting the bot to a new business means editing this file only.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # put the token from @BotFather into BOT_TOKEN
.venv/bin/python bot.py         # send /kimim to the bot, copy the number into ADMIN_CHAT_ID, restart
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Türkçe

Restoran ve kafeler için Telegram botu: menü, sepetli sipariş, kapasite kontrollü masa rezervasyonu, sık sorulan sorular ve yetkiliye mesaj. Siparişler ve rezervasyonlar CSV dosyasına yazılır ve işletme sahibine Telegram'dan anında bildirilir. Yeni bir işletmeye uyarlamak için yalnız `isletme.json` dosyası değiştirilir.

## License

MIT
