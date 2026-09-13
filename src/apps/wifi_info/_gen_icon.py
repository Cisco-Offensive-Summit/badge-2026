import math
import struct

WIDTH, HEIGHT = 128, 76
BLACK = (0, 0, 0)
DARK = (30, 30, 30)
CYAN = (0, 220, 220)
RED = (255, 60, 60)
YELLOW = (255, 200, 40)
GREEN = (0, 255, 70)

pixels = [[BLACK for _ in range(WIDTH)] for _ in range(HEIGHT)]  # [y][x], y=0 is top


def fill_rect(x0, y0, x1, y1, color):
    for y in range(max(y0, 0), min(y1, HEIGHT)):
        for x in range(max(x0, 0), min(x1, WIDTH)):
            pixels[y][x] = color


def set_px(x, y, color):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        pixels[y][x] = color


# outer border + title bar, matching the other terminal-style icons
fill_rect(0, 0, WIDTH, 2, CYAN)
fill_rect(0, HEIGHT - 2, WIDTH, HEIGHT, CYAN)
fill_rect(0, 0, 2, HEIGHT, CYAN)
fill_rect(WIDTH - 2, 0, WIDTH, HEIGHT, CYAN)
fill_rect(2, 2, WIDTH - 2, 14, DARK)
fill_rect(2, 14, WIDTH - 2, 15, CYAN)
fill_rect(8, 5, 14, 11, RED)
fill_rect(18, 5, 24, 11, YELLOW)
fill_rect(28, 5, 34, 11, GREEN)

# WiFi signal fan: concentric arcs opening upward + a solid dot
cx, cy = WIDTH // 2, 62
for radius in (12, 24, 36):
    thickness = 3
    for angle_step in range(0, 1801):
        angle = math.radians(angle_step / 10.0 + 180)
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        for t in range(thickness):
            set_px(x, y - t, CYAN)
            set_px(x + 1, y - t, CYAN)
fill_rect(cx - 4, cy - 4, cx + 4, cy + 4, CYAN)

row_size = WIDTH * 3
data_size = row_size * HEIGHT
file_size = 54 + data_size

with open(r"f:\apps\wifi_info\icon.bmp", "wb") as f:
    f.write(b"BM")
    f.write(struct.pack("<IHHI", file_size, 0, 0, 54))
    f.write(struct.pack("<IiiHHIIiiII", 40, WIDTH, HEIGHT, 1, 24, 0, data_size, 0, 0, 0, 0))
    for y in range(HEIGHT - 1, -1, -1):
        for (r, g, b) in pixels[y]:
            f.write(bytes((b, g, r)))

print("wrote icon.bmp", file_size, "bytes")
