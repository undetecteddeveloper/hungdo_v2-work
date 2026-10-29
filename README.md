# Hứng Đồ v2

A small neon arcade game: slide a catcher bar left and right to catch falling orbs, diamonds and stars, dodge bombs, grab power-ups (shield, heart, slow, wide bar, magnet) and survive boss fights with lasers. English and Vietnamese UI. Made with Python, pygame-ce and Claude Code.

## Where to open the game

The game runs from source on Windows, macOS or Linux:

```bash
git clone https://github.com/undetecteddeveloper/hungdo_v2-work.git
cd hungdo_v2-work
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install pygame-ce numpy
python main.py
```

No account or install beyond Python 3 is needed. There is no prebuilt .exe in this repo.

## Controls

- Menu: W/S or arrow keys to select, Enter to confirm
- In game: A/D or arrow keys to move, Esc or P to pause
- The in-game "How to play" screen lists every item

## Tests

```bash
pip install pytest
python -m pytest
```

## Credits

All third-party art, fonts and sounds with their licenses are listed in [CREDITS.md](CREDITS.md).
