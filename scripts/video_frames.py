"""Extract sample frames from videos in the wa-ingest media lake.

Usage:
  uv run --with opencv-python-headless python scripts/video_frames.py [pattern]

Writes frames at 25%/75% of each video to <media-dir>/_frames/<video_stem>_fNN.jpg
(next to the video, folder is gitignore-able) or to a temp dir if not writable.
"""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "data" / "media"
FRACTIONS = (0.25, 0.75)


def extract(video: Path) -> None:
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 0:
        print(f"{video.name}: no frames readable")
        return
    outdir = video.parent / "_frames"
    outdir.mkdir(exist_ok=True)
    for frac in FRACTIONS:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * frac))
        ok, frame = cap.read()
        if ok:
            p = outdir / f"{video.stem}_f{int(frac * 100)}.jpg"
            cv2.imwrite(str(p), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(p)
    cap.release()


def main() -> None:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*/*.mp4"
    for v in sorted(MEDIA.glob(pattern)):
        if "_frames" not in v.parts:
            extract(v)


if __name__ == "__main__":
    main()
