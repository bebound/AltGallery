---
name: update-image
description: Refresh an existing AltGallery app after the user replaces its icon or screenshots by hand
---

# Updating an App's Images

I've update the icon and/or the screenshots in the app, you need to re-render the news and update the config.toml as well as the readme to reflect the changes. Config.toml must include all of the screenshots. Don't need to check the size or content of the images.

Then convert the new artwork to WebP like any other app's:

```bash
uv run tools/to_webp.py apps/<AppName>/icon.png apps/<AppName>/images/*
```

The icon must be converted before re-rendering the news image (`render_news.py`
finds it by stem). Point `config.toml` and the README at the `.webp` files.
