from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new('RGBA', (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, 255, 255), radius=64, fill='#245849')
draw.polygon([(128, 40), (152, 104), (216, 128), (152, 152), (128, 216), (104, 152), (40, 128), (104, 104)], fill='#dcebba')
draw.ellipse((176, 40, 208, 72), fill='white')
image.save(Path(__file__).with_name('rona.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
