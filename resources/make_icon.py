"""Генерация иконки DI_Check: документ с галочкой на тёмной плашке.

Запуск: .venv/Scripts/python.exe -X utf8 resources/make_icon.py
Результат: resources/app.ico (16..256 px) и frontend/public/icon.png (favicon).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 256  # размер мастер-канвы

# палитра приложения (Tailwind zinc + emerald + sky)
BG = (24, 24, 27, 255)        # zinc-900
BORDER = (82, 82, 91, 255)    # zinc-500
SHEET = (250, 250, 250, 255)  # zinc-50
FOLD = (196, 197, 202, 255)   # zinc-400-ish
LINE = (161, 161, 170, 255)   # zinc-400
CHECK = (16, 185, 129, 255)   # emerald-500


def draw_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # тёмная скруглённая плашка
    d.rounded_rectangle([6, 6, 250, 250], radius=52, fill=BG, outline=BORDER, width=5)

    # лист документа со срезанным верхним правым углом
    sheet = [(76, 40), (166, 40), (204, 78), (204, 216), (76, 216)]
    d.polygon(sheet, fill=SHEET)
    # загнутый уголок
    d.polygon([(166, 40), (166, 78), (204, 78)], fill=FOLD)

    # строки текста на листе
    for i, (y, w) in enumerate([(96, 96), (120, 96), (144, 64)]):
        x0 = 96 if i == 0 or True else 96
        d.rounded_rectangle([x0, y, x0 + w, y + 12], radius=6, fill=LINE)

    # галочка (наплывает на нижний правый край листа) — с тёмной обводкой для контраста
    check = [(112, 156), (144, 188), (204, 112)]
    d.line(check, fill=(9, 9, 11, 255), width=34, joint="curve")
    d.line(check, fill=CHECK, width=22, joint="curve")
    # круглые "пробки" на концах линии, чтобы срезы были аккуратными
    for x, y in (check[0], check[2]):
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=CHECK)

    return img


def main() -> None:
    master = draw_master()
    out_dir = ROOT / "resources"
    out_dir.mkdir(exist_ok=True)
    master.save(
        out_dir / "app.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    pub = ROOT / "frontend" / "public"
    pub.mkdir(exist_ok=True)
    master.save(pub / "icon.png")
    print("OK: resources/app.ico, frontend/public/icon.png")


if __name__ == "__main__":
    main()
