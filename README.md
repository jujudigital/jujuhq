# jujuhq static mirror

This repository contains a static mirror of https://jujuhq.com, recreated as closely as possible.

## Structure
- assets/css: Stylesheets
- assets/js: Scripts
- assets/img: Images
- assets/fonts: Web fonts
- scripts: helper scripts used to mirror and process the site

## Quick start
Open `index.html` locally in a browser. If you use a simple server, e.g. Python:

```bash
python3 -m http.server 8080
```

Then visit http://localhost:8080

## Notes
- Any assets that could not be fetched are listed in `BROKEN_ASSETS.md`.
- Paths are rewritten to local assets when possible.
