"""Render the existing LH25 wordmark for payment-channel branding."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "runtime" / "branding" / "lh25-store.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (512, 512), "#101d28")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 480, 480), radius=80, outline="#92ded0", width=5)
    font_path = Path("C:/Windows/Fonts/segoeuib.ttf")
    large = ImageFont.truetype(str(font_path), 126) if font_path.is_file() else ImageFont.load_default(size=100)
    small = ImageFont.truetype(str(font_path), 46) if font_path.is_file() else ImageFont.load_default(size=42)
    draw.text((256, 225), "LH25", anchor="mm", fill="#92ded0", font=large)
    draw.text((256, 335), "STORE", anchor="mm", fill="#f0f5fa", font=small)
    image.save(output)
    print(output)


if __name__ == "__main__":
    main()
