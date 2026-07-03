# averagechris.srht.site

The root homepage for <https://averagechris.srht.site/>: an about-me plus a
directory of my projects, each linking to its downloads page at
`https://averagechris.srht.site/<project>/`.

## Why this repo exists (and the big caveat)

Every project publishes its own downloads page with
`hut pages publish -s /<project>` (subdirectory publishing), which preserves
the rest of the site — including the root `index.html` this repo owns.

But **a root publish replaces the entire site**. So before publishing the
homepage, `build-pages` mirrors every subdirectory listed in `projects.toml`
from the live site (index page, `manifest.json`, and every linked download
artifact) into the tarball. That means:

- `projects.toml` must list **every** subdirectory ever published to the
  site, or a homepage publish will delete it. Use `listed = false` to mirror
  a subdirectory without showing a card.
- Project releases continue to use their existing subdirectory publish flow
  unchanged; they will never clobber the homepage.

## Usage

```sh
# add a new project card
nix run .#add-project -- my-project --description "What it does"

# build (mirrors the live site, generates index.html, packs dist/pages.tar.gz)
nix run .#build-pages

# preview locally without mirroring (do NOT publish this build)
nix run .#build-pages -- --skip-mirror
nix run .#serve            # http://localhost:8000

# publish to https://averagechris.srht.site/
nix run .#publish-pages
```

Pushing to this repo also republishes the site via `.builds/pages.yml`.

## Files

- `projects.toml` — site metadata (about, links) and the project registry
- `scripts/build_pages.py` — mirror + generate + tar
- `scripts/add_project.py` — append a project entry to `projects.toml`
