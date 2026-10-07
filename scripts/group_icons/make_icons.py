"""make_icons.py - compose 640x640 WhatsApp group icons.

Layout: universal SD gold emblem (seed 7) centered in the upper area on a deep
charcoal-navy radial gradient, group acronym below in small letter-spaced
Bahnschrift, everything inside WhatsApp's circular crop safe zone.

Run with: D:\\pritam\\venv\\python.exe make_icons.py [seed]
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
LOGO = HERE / "candidates" / "logo_seed7.png"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

SIZE = 640
CENTER = SIZE // 2

# (chat_id, group name, subtext below logo - Swastik/Digital dropped)
GROUPS = [
    ("120363427704545189", "Swastik Digital", "SWASTIK DIGITAL"),
    ("120363430269391388", "Grey inward Swastik digital", "GREY INWARD"),
    ("120363410428955545", "Swastik digital production", "PRODUCTION"),
    ("120363412544066919", "Swastik digi pre processing (white)", "PRE PROCESSING WHITE"),
    ("120363373350099610", "Swastik grey / white report", "GREY / WHITE REPORT"),
    ("120363409903031213", "Swastik digital white & finish", "WHITE & FINISH"),
    ("120363427833719866", "Miss print /problem like dagi", "MISS PRINT / DAGI"),
    ("120363412940169494", "Swastik pc problems", "PC PROBLEMS"),
    ("120363435178550008", "Swastik Digital Pc Problems", "PRODUCTION PC PROBLEMS"),
    ("120363430911077311", "Swastik AC maintenance and upkeep", "AC MAINTENANCE"),
    ("120363431408589948", "Swastik IT Material order", "IT MATERIAL ORDER"),
    ("120363027742217699", "Swastik (IT) issue and reports", "IT ISSUES & REPORTS"),
    ("120363184191482756", "DIWAN B DEVELOPMENT", "DIWAN B DEVELOPMENT"),
    ("120363411486701693", "Sunrise swastik krisha", "SUNRISE KRISHA"),
    ("120363284178032488", "Digital Hybrid design Group", "HYBRID DESIGN GROUP"),
    ("120363236860121186", "Swastik Digital Paper Print & Fusing", "PAPER PRINT & FUSING"),
]

FONT_PATH = r"C:\Windows\Fonts\bahnschrift.ttf"
GOLD = (216, 178, 92)
GOLD_DIM = (160, 132, 74)


def radial_background() -> Image.Image:
    """Deep charcoal-navy radial gradient: warm dark center -> near-black edge."""
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    inner = (34, 39, 52)     # center
    outer = (11, 13, 19)     # edge
    maxd = (SIZE * 0.75) ** 2
    for y in range(SIZE):
        for x in range(SIZE):
            d = (x - CENTER) ** 2 + (y - CENTER) ** 2
            t = min(d / maxd, 1.0)
            t = t * t * (3 - 2 * t)  # smoothstep
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(inner, outer))
    return img


def load_emblem(box: int) -> Image.Image:
    """Trim the transparent emblem and fit it into a square `box`."""
    rgba = Image.open(LOGO).convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    rgba = rgba.crop(bbox)
    rgba.thumbnail((box, box), Image.LANCZOS)
    return rgba


def draw_text_tracked(draw, xy_center, text, font, tracking, fill):
    """Draw text with letter spacing, centered at xy_center."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    asc, desc = font.getmetrics()
    x = xy_center[0] - total / 2
    y = xy_center[1] - (asc + desc) / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def make_icon(acronym: str, emblem: Image.Image) -> Image.Image:
    img = radial_background()

    # emblem centered horizontally, optical center in upper 55%
    ex = CENTER - emblem.width // 2
    ey = 92 + (300 - emblem.height) // 2
    # soft gold glow behind the emblem
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gmask = emblem.getchannel("A").point(lambda a: min(a, 90))
    glow.paste(Image.new("RGBA", emblem.size, (212, 175, 55, 255)), (ex, ey), gmask)
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    img.alpha_composite(emblem, (ex, ey))

    draw = ImageDraw.Draw(img)

    # thin gold divider
    draw.line([(CENTER - 34, 452), (CENTER + 34, 452)], fill=GOLD_DIM, width=2)

    # acronym: shrink to fit 400px, tracking scales with font size
    size = 46
    while True:
        tracking = min(10, max(3, round(size * 0.22)))
        font = ImageFont.truetype(FONT_PATH, size)
        widths = [draw.textlength(c, font=font) for c in acronym]
        if sum(widths) + tracking * (len(acronym) - 1) <= 400 or size <= 20:
            break
        size -= 2

    # subtle drop shadow for legibility, then gold text
    ty = 496
    draw_text_tracked(draw, (CENTER + 2, ty + 3), acronym, font, tracking, (0, 0, 0))
    draw_text_tracked(draw, (CENTER, ty), acronym, font, tracking, GOLD)

    # circular-crop safe-zone debug overlay (kept OFF for final)
    # draw.ellipse([4, 4, SIZE - 4, SIZE - 4], outline=(255, 0, 0, 128), width=2)

    return img.convert("RGB")


def main():
    alpha = Image.open(LOGO).getchannel("A")
    lo, hi = alpha.getextrema()
    print(f"emblem alpha extrema: {lo}..{hi}")
    emblem = load_emblem(300)

    thumbs = []
    for chat_id, name, acro in GROUPS:
        icon = make_icon(acro, emblem)
        dest = OUT / f"{chat_id}.jpg"
        icon.save(dest, "JPEG", quality=92)
        print(f"{acro:<5} {dest.name}  ({name})")
        thumbs.append((acro, icon))

    # 4x4 montage for review
    m = Image.new("RGB", (SIZE * 4, SIZE * 4), (0, 0, 0))
    for i, (_, icon) in enumerate(thumbs):
        m.paste(icon, ((i % 4) * SIZE, (i // 4) * SIZE))
    m.thumbnail((1600, 1600), Image.LANCZOS)
    m.save(HERE / "montage.png")
    print("montage -> montage.png")


if __name__ == "__main__":
    main()
