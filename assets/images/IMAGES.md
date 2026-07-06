# Site Images — modulargreenhouses.com

Downloaded at full original resolution from the Wix CDN by
`scripts/download_site_images.py` (run `download-site-images.bat` from the
project root). A machine-readable map is written to `manifest.json`.

## Product line categories

| Folder | Product | Width | Sizes | Pricing (site, Jul 2026) |
|---|---|---|---|---|
| `raised-bed/` | Modular Raised Bed Greenhouse | 4' | 4x4 to 4x24 in 4' increments | $999–$3,499 |
| `barn-style/` | Barn Style Modular Greenhouse (new launch) | 6'5" | 6x4, 6x8, 6x12, 6x16, 6x20+ | $1,999–$3,699 (launch specials $1,499–$2,999) |
| `a-frame/` | A-frame Modular Greenhouse ("regular" sizes) | 8' | 8x8 to 8x28, pop-out & cathedral options | $3,280–$7,380 |
| `gallery/` | Install / customer photos, mixed models | — | — | — |
| `branding/` | Logo, hero shots, site imagery | — | — | — |

## Web-ready derivatives (already generated)

`ui/public/assets/` contains optimized versions wired into the site:
`hero.jpg` (2400px, from `branding/hero-banner.jpg`), `models/*.jpg`
(card images for raised-bed, barn-style, a-frame), and `gallery/*.jpg`
(8 picks for the homepage gallery section). Regenerate any of these from
the full-res originals in this folder.

`manifest.json` now includes a `model` tag per gallery photo
(`a-frame`, `raised-bed`, `interior-crops`, `custom-balcony`, `indoor-rack`) —
most install shots are the 8' A-frame.

## Notes for the new site build

- Filenames named by product where the source site labeled them
  (e.g. `raised-bed-4x4-side-closed.jpeg`, `barn-6x4-side.jpeg`,
  `a-frame-8x8-main.jpg`). Gallery photos are numbered; several likely show
  A-frame installs — recategorize as you review them.
- `ui/public/site.css` in the repo expects `/assets/hero.jpg` — copy your
  pick from `branding/` (e.g. `hero-banner.jpg`, 5482x3655) and rename.
- Full-res originals are large (some 4000px+/5MB+). Generate web-optimized
  derivatives (~1600px wide, quality 80) before shipping on the new site.
- Barn Style images on the source site are the launch photos from the Reno
  Home & Garden Show section plus the 9-image grid on the homepage.
