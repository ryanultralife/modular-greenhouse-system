#!/usr/bin/env python3
"""Download categorized product images from modulargreenhouses.com (Wix CDN).

Run on your own machine (the Claude sandbox blocks static.wixstatic.com):

    python scripts/download_site_images.py

Images land in assets/images/<category>/ at FULL original resolution,
with a manifest written to assets/images/manifest.json.

Categories
----------
raised-bed  4' wide Modular Raised Bed Greenhouse ($999+)
barn-style  6'5" wide Barn Style Greenhouse (new product, $1999+)
a-frame     8' wide A-frame Modular Greenhouse - the "regular" sizes ($3280+)
gallery     Install/customer photos (mixed models)
branding    Logo, hero shots, misc site imagery

No dependencies beyond the standard library.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

CDN = "https://static.wixstatic.com/media/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# (output filename, wix media id)  -- fetching the bare media id returns the
# original full-resolution upload, bypassing all Wix resize/crop transforms.
IMAGES: dict[str, list[tuple[str, str]]] = {
    "raised-bed": [
        ("raised-bed-4x4-side-closed.jpeg", "e27686_b5284e6dc10d4c1bb2ca0fa032493b78~mv2.jpeg"),
        ("raised-bed-4x4-open.jpeg",        "e27686_6df1599e3d454359ab2f123f4171742e~mv2.jpeg"),
        ("raised-bed-hero.jpeg",            "e27686_8c8fad63afdf4a0682c91c4cee9bee9c~mv2.jpeg"),
    ],
    "barn-style": [
        ("barn-6x4-side.jpeg", "e27686_9944f0acc3ed425c89dad8eb600a7b27~mv2.jpeg"),
        ("barn-style-02.jpeg", "e27686_ee32ceebb6f943fe8c5a76ccec49a0da~mv2.jpeg"),
        ("barn-style-03.jpeg", "e27686_95584c48eefd4e378160d30e9f2a772a~mv2.jpeg"),
        ("barn-style-04.jpeg", "e27686_173a34660adc4583963b5064db948640~mv2.jpeg"),
        ("barn-style-05.jpeg", "e27686_f1a806be2755434dbdb436ca6d49518b~mv2.jpeg"),
        ("barn-style-06.jpeg", "e27686_223f82883db9487fa6cc737a37c20ee2~mv2.jpeg"),
        ("barn-style-07.jpeg", "e27686_1ac81ab9327f438ca6ec7a7648bb6382~mv2.jpeg"),
        ("barn-style-08.jpeg", "e27686_a1135ad497104e3b8ac2af99519f190c~mv2.jpeg"),
        ("barn-style-09.jpeg", "e27686_2cdff8c997fd4daab8daead577bfe6a8~mv2.jpeg"),
    ],
    "a-frame": [
        ("a-frame-shop-card.jpg", "e27686_235b19ee423e4ae5b1ec61029ab70ded~mv2_d_2048_2048_s_2.jpg"),
        ("a-frame-8x8-main.jpg",  "e27686_1852f203534e4304b511d86f341894d0~mv2_d_3024_2886_s_4_2.jpg"),
        ("a-frame-8x8-02.jpg",    "e27686_b326a3e5f0ae47c28a9dc6247fa63d70~mv2_d_4032_3024_s_4_2.jpg"),
        ("a-frame-8x12-main.jpg", "e27686_a5e45bb90c424ac7b9e4d23686ce96dc~mv2_d_2048_1365_s_2.jpg"),
        ("a-frame-8x12-02.jpg",   "e27686_c75ecec95ca640a1a082bcdc1f38cffb~mv2_d_5616_3744_s_4_2.jpg"),
        ("a-frame-8x12-03.jpg",   "e27686_dd9f7d1ade4f43a68784a6e33b5157ea~mv2_d_3363_5044_s_4_2.jpg"),
        ("a-frame-8x12-04.jpg",   "e27686_42f401f5bb4a4405b5ddaa21a85d6500~mv2_d_4270_2847_s_4_2.jpg"),
        ("a-frame-8x12-05.jpg",   "e27686_e53fbf7355994c3d9c35d25575f30454~mv2_d_2048_1368_s_2.jpg"),
        ("a-frame-8x12-06.jpg",   "e27686_826d6724f7ec4ddaba4829c54ab9f59d~mv2_d_2048_1365_s_2.jpg"),
        ("a-frame-8x12-07.jpg",   "e27686_ec3682a3c9af4614af576b7ab6548a5a~mv2_d_2048_1365_s_2.jpg"),
        ("a-frame-8x12-08.jpg",   "e27686_b709c5f16fd34574b4f047399361a206~mv2_d_2048_1365_s_2.jpg"),
        ("a-frame-8x12-09.jpg",   "e27686_948cbfe60fb04d64ac8c16e9256516c8~mv2_d_2048_2048_s_2.jpg"),
    ],
    "gallery": [
        ("gallery-01.jpg", "e27686_92c1c0e0f3e04e278587641e1c493a06~mv2.jpg"),
        ("gallery-02.jpg", "e27686_bd75b15f71df48a9a2f59a2090d62ae1~mv2.jpg"),
        ("gallery-03.jpg", "e27686_7e394beec298406e91e8276afbb7c504~mv2.jpg"),
        ("gallery-04.jpg", "e27686_54a5fb1e311d4f20ac2db26ddcd0daf0~mv2_d_1719_2311_s_2.jpg"),
        ("gallery-img-6152.jpg", "e27686_3d96d72c6cf349a9b52e7a8f6c572681~mv2.jpg"),
        ("gallery-img-6379.jpg", "e27686_a8d0f7a504b249d29e0cec7ac1d1449f~mv2.jpg"),
        ("gallery-img-6441.jpg", "e27686_bf850ce944c34ea79555354ef58b9fed~mv2.jpg"),
        ("gallery-08.jpg", "e27686_2b785d323ca348a1be12bdd8c9f3e486~mv2.jpg"),
        ("gallery-09.jpg", "e27686_ed7525f6474b4a16b74fb6d5b85d21b1~mv2.jpg"),
        ("gallery-10.jpg", "e27686_e603eb109e9f4fd69aeb9078d08b34ac~mv2.jpg"),
        ("gallery-11.jpg", "e27686_ed12385edb404acda284b860b423563c~mv2_d_2048_1368_s_2.jpg"),
        ("gallery-12.jpg", "e27686_e0ea277121644f1a8c672379da010617~mv2_d_2000_1333_s_2.jpg"),
        ("gallery-13.jpg", "e27686_6f4e68d1c43b436c95ebd49035369083~mv2_d_2000_1333_s_2.jpg"),
        ("gallery-14.jpg", "e27686_81fd2bdb9004458a8f9c17e2a56c5267~mv2_d_2048_1368_s_2.jpg"),
        ("gallery-15.jpg", "e27686_2c5a3d28abe64652a321ad72bd588462~mv2_d_2048_1368_s_2.jpg"),
        ("gallery-16.jpg", "e27686_d1f3552fe5de427ea1dff5879284be6d~mv2_d_2048_1368_s_2.jpg"),
        ("gallery-17.jpg", "e27686_1601bfb7fdae4b1db7dce1cc4c3222d6~mv2_d_1368_2048_s_2.jpg"),
        ("gallery-18.jpg", "e27686_16560f11163c4e489e3256422bf8b7fa~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-19.jpg", "e27686_a4e293f082fc491daabd6b60fadc46c2~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-20.jpg", "e27686_86f88f71ea8c4749800ac09e4bcf91f0~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-21.jpg", "e27686_bad554757cc146519c973fcdadec5cef~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-22.jpg", "e27686_0e98d7056a8c4abfbc525bf9c578e1f9~mv2.jpg"),
        ("gallery-23.jpg", "e27686_b1e74b274c00466ba7284ee7657cbd26~mv2.jpg"),
        ("gallery-24.jpg", "e27686_7bcd4aedf9e24c129d73b0879e8b7228~mv2.jpg"),
        ("gallery-25.jpg", "e27686_aba7006bfffe4a63b64da6cefa7cde95~mv2.jpg"),
        ("gallery-26.jpg", "e27686_7959322c057f4fee9ea62881db78aa8a~mv2.jpg"),
        ("gallery-27.jpg", "e27686_c5e4798e94de40d587b838fa700b4077~mv2.jpg"),
        ("gallery-28.jpg", "e27686_221730b3d7e9429aafa73e4caa65c909~mv2.jpg"),
        ("gallery-29.jpg", "e27686_d73ed42de7574b53a7aaf7a3a92d1a96~mv2.jpg"),
        ("gallery-30.jpg", "e27686_ac7cb16602c94904a93ec1b77a06da0c~mv2.jpg"),
        ("gallery-31.jpg", "e27686_17fd1663fcd74fa28e9fdb6e3b3b2bfa~mv2.jpg"),
        ("gallery-32.jpg", "e27686_57bc64f79b7e443480af99e08db26b36~mv2.jpg"),
        ("gallery-33.jpg", "e27686_2f1ad0eb84684ee19ad8c53d58a18caa~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-34.jpg", "e27686_e4b09cdf809d4893af50864a89c47ee3~mv2.jpg"),
        ("gallery-35.jpg", "e27686_b194e8b40c7e4131a5295ec2175ba647~mv2_d_4032_3024_s_4_2.jpg"),
        ("gallery-36.jpg", "e27686_41e2ec8e311143f09a69753063f4ed73~mv2_d_1282_1920_s_2.jpg"),
        ("gallery-37.jpg", "e27686_9860772864c64d2699c43407220ffae3~mv2_d_2048_1368_s_2.jpg"),
    ],
    "branding": [
        ("logo-white.png",   "e27686_652772bec12d4d74a4cd4d409f888688~mv2.png"),
        ("hero-og.jpg",      "e27686_6157aafa77094d8f8d2e580edf71e081~mv2_d_2000_1333_s_2.jpg"),
        ("hero-banner.jpg",  "e27686_abd9113129234138b2dea55ca4d1db60~mv2_d_5482_3655_s_4_2.jpg"),
        ("hero-field.jpg",   "e27686_79d47827e8be4c2f857704510b52a16b~mv2_d_2000_1319_s_2.jpg"),
        ("header-bg.jpg",    "e27686_66fa2a5dfacd42da85dd4ad31da58e7e~mv2_d_2048_1368_s_2.jpg"),
    ],
}


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            dest.write_bytes(data)
            return len(data)
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                print(f"  FAILED {url}: {exc}")
                return 0
            time.sleep(2 * (attempt + 1))
    return 0


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "assets" / "images"
    manifest: list[dict] = []
    total = ok = 0

    for category, items in IMAGES.items():
        out_dir = root / category
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n== {category} ({len(items)} images) ==")
        for filename, media_id in items:
            total += 1
            dest = out_dir / filename
            url = CDN + media_id
            if dest.exists() and dest.stat().st_size > 0:
                print(f"  skip (exists): {filename}")
                ok += 1
            else:
                size = download(url, dest)
                if size:
                    ok += 1
                    print(f"  {filename}  ({size // 1024} KB)")
            manifest.append({
                "category": category,
                "file": f"{category}/{filename}",
                "source": url,
            })

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nDone: {ok}/{total} images in {root}")
    print("Manifest: assets/images/manifest.json")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
