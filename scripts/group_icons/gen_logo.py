"""gen_logo.py - generate the universal SD monogram emblem via Qwen-Image-2.1.

Outputs RGBA transparent candidates into candidates/ for review.
Run with: D:\\Python312\\python.exe gen_logo.py
"""
import sys
from pathlib import Path

import torch
from diffusers import QwenImage21Pipeline

OUT = Path(__file__).parent / "candidates"
OUT.mkdir(exist_ok=True)

PROMPT = """This is an RGBA image with transparency. A premium minimalist brand monogram logo:
the two capital letters "S" and "D" interlocked into a single elegant lettermark emblem.
The letters are drawn in polished metallic antique gold with smooth gradients, bright
highlight edges and darker bronze inner shadows, giving a solid embossed metal feel.
The S overlaps and weaves into the D so they read as one unified mark.
Beneath and behind the letters, a subtle accent motif: three thin flowing arc lines
suggesting printed fabric threads passing through, in the same antique gold, very
restrained and minimal.
Flat 2D vector-style logo design, perfectly centered on the canvas, generous empty
margin around the mark, crisp clean edges, luxury brand identity quality.
No additional text, no words, no numbers, no border, no frame, no circle, no badge,
no background elements, no shadow cast on background, no watermark.
The image has alpha channel and the background is transparent."""

NEGATIVE = "text other than the letters S and D, words, watermark, signature, busy background, opaque background, white background, colored background, frame, border, circle, badge, shadows on background, extra letters, lowercase, blurry, jpeg artifacts, 3d scene, mockup, photo"

def main():
    seeds = [int(x) for x in sys.argv[1:]] or [7, 21, 42]
    steps = 30
    pipe = QwenImage21Pipeline.from_pretrained(
        "Qwen/Qwen-Image-2.1", torch_dtype=torch.bfloat16
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    for seed in seeds:
        img = pipe(
            prompt=PROMPT,
            negative_prompt=NEGATIVE,
            width=1024, height=1024,
            num_inference_steps=steps,
            true_cfg_scale=4.0,
            generator=torch.Generator("cuda").manual_seed(seed),
        ).images[0]
        dest = OUT / f"logo_seed{seed}.png"
        img.save(dest)
        print(f"saved {dest}", flush=True)

if __name__ == "__main__":
    main()
