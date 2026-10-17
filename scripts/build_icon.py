"""Build the small mint bar-chart application icon using only the standard library."""
import struct
from pathlib import Path


def bitmap(size):
    pixels = bytearray()
    for y in reversed(range(size)):
        for x in range(size):
            nx, ny = x / size, y / size
            inside = .03 <= nx <= .97 and .03 <= ny <= .97
            bar = any(left <= nx <= left + .13 and top <= ny <= .77
                      for left, top in ((.19, .49), (.435, .23), (.68, .37)))
            r, g, b, a = (98, 229, 191, 255) if bar else (16, 23, 28, 255 if inside else 0)
            pixels.extend((b, g, r, a))
    mask = bytes(((size + 31) // 32) * 4 * size)
    header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    return header + pixels + mask


if __name__ == '__main__':
    sizes = (16, 32, 48, 64)
    images = [bitmap(size) for size in sizes]
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in zip(sizes, images):
        entries.append(struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path = Path(__file__).resolve().parents[1] / 'src/codex_insights/assets/insights.ico'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries + images))
