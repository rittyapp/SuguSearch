"""薄い青のモダンな虫眼鏡アイコンを多サイズ生成し sugusearch.ico にまとめる。"""

from pathlib import Path

from PIL import Image, ImageDraw

# 出力先はリポジトリ直下の assets/（このスクリプトは script/ にある）
OUT = Path(__file__).resolve().parent.parent / "assets"
ICON_DIR = OUT / "icons"
OUT.mkdir(exist_ok=True)
ICON_DIR.mkdir(exist_ok=True)

# Windows で使う小〜最大（256）の代表サイズ
SIZES = [16, 20, 24, 32, 40, 48, 64, 72, 96, 128, 256]


def create_icon(size: int) -> Image.Image:
    """薄い青のモダンな虫眼鏡アイコン（透過）。"""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx = int(s * 0.42)
    cy = int(s * 0.42)
    r = int(s * 0.30)
    stroke = max(2, int(s * 0.11))
    handle_w = max(2, int(s * 0.12))

    blue = (96, 165, 250, 255)  # #60A5FA
    blue_dark = (37, 99, 235, 255)  # #2563EB
    blue_soft = (191, 219, 254, 255)  # #BFDBFE
    white = (255, 255, 255, 230)

    # 影（中サイズ以上）
    if s >= 32:
        shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        off = max(1, s // 48)
        sd.ellipse(
            [
                cx - r - stroke // 2 + off,
                cy - r - stroke // 2 + off,
                cx + r + stroke // 2 + off,
                cy + r + stroke // 2 + off,
            ],
            outline=(15, 23, 42, 40),
            width=stroke,
        )
        hx0 = cx + int(r * 0.72) + off
        hy0 = cy + int(r * 0.72) + off
        hx1 = int(s * 0.88) + off
        hy1 = int(s * 0.88) + off
        sd.line([(hx0, hy0), (hx1, hy1)], fill=(15, 23, 42, 35), width=handle_w)
        img = Image.alpha_composite(img, shadow)
        d = ImageDraw.Draw(img)

    # レンズ内側
    inner = max(0, r - stroke // 2 - 1)
    if inner > 1:
        d.ellipse(
            [cx - inner, cy - inner, cx + inner, cy + inner],
            fill=blue_soft,
        )
        hr = max(1, inner // 3)
        d.ellipse(
            [
                cx - inner + hr // 2,
                cy - inner + hr // 2,
                cx - inner + hr * 2,
                cy - inner + hr * 2,
            ],
            fill=white,
        )

    # リング
    d.ellipse(
        [
            cx - r - stroke // 2,
            cy - r - stroke // 2,
            cx + r + stroke // 2,
            cy + r + stroke // 2,
        ],
        outline=blue_dark,
        width=stroke,
    )
    if s >= 48:
        d.ellipse(
            [
                cx - r - stroke // 2,
                cy - r - stroke // 2,
                cx + r + stroke // 2,
                cy + r + stroke // 2,
            ],
            outline=blue,
            width=max(1, stroke // 3),
        )

    # ハンドル
    hx0 = cx + int(r * 0.70)
    hy0 = cy + int(r * 0.70)
    hx1 = int(s * 0.90)
    hy1 = int(s * 0.90)
    d.line([(hx0, hy0), (hx1, hy1)], fill=blue_dark, width=handle_w)
    cap = max(1, handle_w // 2)
    d.ellipse([hx1 - cap, hy1 - cap, hx1 + cap, hy1 + cap], fill=blue_dark)
    d.ellipse([hx0 - cap, hy0 - cap, hx0 + cap, hy0 + cap], fill=blue_dark)

    return img


def main() -> None:
    images_by_size = {}
    for size in SIZES:
        im = create_icon(size)
        path = ICON_DIR / f"sugusearch_{size}.png"
        im.save(path, format="PNG")
        images_by_size[size] = im
        print("wrote", path)

    master = ICON_DIR / "sugusearch_master.png"
    images_by_size[256].save(master, format="PNG")
    print("wrote", master)

    # マルチサイズ ICO（Pillow は各サイズ画像を渡すのが確実）
    ico_path = OUT / "sugusearch.ico"
    # 大きい順で保存するとエクスプローラー表示が安定しやすい
    ordered = sorted(SIZES, reverse=True)
    imgs = [images_by_size[s] for s in ordered]
    imgs[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ordered],
        append_images=imgs[1:],
    )
    print("wrote", ico_path, "bytes", ico_path.stat().st_size)

    # 読み直し確認
    with Image.open(ico_path) as ico:
        print("ICO default size:", ico.size)
        # 各サイズを取り出して存在確認
        for size in SIZES:
            try:
                ico.size = (size, size)  # type: ignore[misc]
                ico.load()
                print(f"  contains {size}x{size}: OK")
            except Exception as e:
                print(f"  contains {size}x{size}: {e}")


if __name__ == "__main__":
    main()
