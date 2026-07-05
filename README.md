# togger-wrapped

Footy chat wrapped, built as a static site for GitHub Pages.

## GitHub Pages

This stays GitHub Pages-friendly:

1. Everything is static (`index.html`, images, JSON data files).
2. No server/runtime required.
3. New analysis is loaded from `data/summary.json` in the browser.

## Regenerate analysis data

Run this locally when you have a fresh WhatsApp export zip:

```bash
python3 scripts/analyse_chat.py \
  --zip "WhatsApp Chat - Joe's BBQ Togger.zip" \
  --output data/summary.json
```

Then commit and push; Pages will serve the updated wrapped automatically.
