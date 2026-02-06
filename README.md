# jujuhq static mirror

This repository contains a static mirror of https://jujuhq.com, recreated as closely as possible.

## Structure
- assets/css: Stylesheets
- assets/js: Scripts
- assets/img: Images
- assets/fonts: Web fonts
- scripts: helper scripts used to mirror and process the site

### Pages
- `/` → `index.html`
- `/contact-us/` → `contact-us/index.html`
- `/irresistible/` → `irresistible/index.html`
- `/privacy-policy/` → `privacy-policy/index.html`
- `/404.html` → `404.html`

## Quick start
Open `index.html` locally in a browser. If you use a simple server, e.g. Python:

```bash
python3 -m http.server 8080
```

Then visit http://localhost:8080

You can also visit:
- http://localhost:8080/contact-us/
- http://localhost:8080/irresistible/
- http://localhost:8080/privacy-policy/

## Notes
- Any assets that could not be fetched are listed in `BROKEN_ASSETS.md`.
- Paths are rewritten to local assets when possible.

## Scripts
- `scripts/fetch_google_fonts.py`: generates `assets/css/fonts.css` and downloads the referenced font files into `assets/fonts/`.
- `scripts/build_local_pages.py`: rebuilds the three internal pages into root-level folders (pretty URLs), removes external/tracker head dependencies, and rewrites any `wp-content/uploads/...` background images to local `assets/img/`.
