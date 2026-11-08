# Whale companion artwork

Author: YunYueSama  
Repository: https://github.com/YunYueSama/codex-deepseek-pet  
Source revision: `7661c8b304c5400701f91da01b1a643a207331de`  
Source sheets:

| Source | SHA-256 |
| --- | --- |
| `assets/whale/idle-front.png` | `79D3952ACFE7620E0C2CFE7B80E9E6793D5F115252962F81CD56778402F4CDCD` |
| `assets/whale/dense-idle.png` | `FDD3990FEE0302D41D9809007F1303663440AF299E0FF979E3B67BD777D934EF` |

The two idle poses and dense-idle frames 1, 3, 5, and 7 were selected, trimmed of
transparent margins, and proportionally resampled into 80 x 84 transparent
canvases. Feet share a bottom anchor at y = 82, with two clear rows below them.
Hair, shoes, and tail remain uncropped. No artwork was redrawn. The open-eyed
idle PNG is byte-identical to the earlier static asset.

Prepared PNGs are provided for inspection. Corresponding C files embed the same
pixels as straight-alpha BGRA for LVGL 9.3, independent of the display's
RGB565/RGB888 output format. Each 26,880-byte array remains in flash; all six
frames total 161,280 bytes. The closed eyes use `whale_closed`; weight-shift poses
use `whale_shift_0` through `whale_shift_3`.

Frame order and timing reference the same revision's `src/renderer/motion.js`.
The firmware uses discrete poses without the upstream WebGL motion interpolation.

To reproduce all frames across platforms:

```bash
uv run --project scripts python scripts/characters/prepare_whale.py
```

The script automatically downloads and verifies the pinned upstream sheets, or you can specify local source paths with `--source` and `--motion-source`.

The original upstream license is preserved verbatim in [LICENSE](LICENSE), and
the upstream asset attribution and third-party reference boundaries are preserved
in [UPSTREAM_ASSET_LICENSE.txt](UPSTREAM_ASSET_LICENSE.txt). These are upstream
legal notices, not newly authored project documentation. The attribution also
applies to the screenshots containing this character. This project does not
claim official DeepSeek endorsement.
