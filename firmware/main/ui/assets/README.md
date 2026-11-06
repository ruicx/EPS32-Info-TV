# Whale companion artwork

Author: YunYueSama  
Repository: https://github.com/YunYueSama/codex-deepseek-pet  
Source revision: `7661c8b304c5400701f91da01b1a643a207331de`  
Source file: `assets/whale/idle-front.png`  
Source SHA-256: `79D3952ACFE7620E0C2CFE7B80E9E6793D5F115252962F81CD56778402F4CDCD`

The supplied two-frame transparent sheet was modified by selecting the left,
open-eyed full-body pose, trimming transparent margins, and proportionally
resampling into an 80 x 84 transparent canvas. Hair, shoes, and tail remain
uncropped. No artwork was redrawn. The character is static in this revision.

`whale_idle.png` is the prepared asset for inspection. `whale_idle.c` embeds the
same pixels as straight-alpha BGRA for LVGL 9.3, independent of the display's
RGB565/RGB888 output format. Its 26,880-byte pixel array remains in flash.

To reproduce both files on Windows after downloading the pinned source sheet:

```powershell
./scripts/prepare_character.ps1 -SourcePath .local/design/whale-source/idle-front.png
```

The original upstream license is preserved verbatim in [LICENSE](LICENSE), and
the upstream asset attribution and third-party reference boundaries are preserved
in [UPSTREAM_ASSET_LICENSE.txt](UPSTREAM_ASSET_LICENSE.txt). These are upstream
legal notices, not newly authored project documentation. The attribution also
applies to the screenshots containing this character. This project does not
claim official DeepSeek endorsement.
