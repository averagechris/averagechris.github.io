# Site rendering plan

This site should stay static on SourceHut Pages while becoming easier to make
weird, polished, and interactive. The durable source of truth is site data and
content; renderers are adapters that can be replaced.

## Hard requirements

- The published artifact is static files only: HTML, CSS, JS, WASM, JSON,
  images, downloads, `state.json`, and `siteconfig.json`.
- There is no runtime server logic on SourceHut Pages: no Axum server, no
  Leptos server functions, no dynamic API endpoints, and no database-backed
  requests.
- The site must remain fast without JavaScript. JavaScript and WASM enhance
  pages; they do not provide the only usable rendering of core content.
- SourceHut Pages' CSP is restrictive. Treat third-party runtime resources as
  unavailable: no CDN scripts, remote stylesheets, hosted fonts, or cross-origin
  fetch dependencies. Same-origin static assets may be used only after QA proves
  they load under the live Pages headers.
- The fleet publisher remains responsible for SourceHut-specific inputs:
  latest semver tags, tag artifacts, docs copied from pinned fleet SHAs,
  release fingerprints, and race-safe refresh/publish behavior.
- Canonical content and metadata must outlive any renderer. Replacing Zola with
  Hugo, full Leptos, or a custom renderer should not require rewriting project
  metadata, note metadata, release metadata, or page bodies.

## Decisions

- Use **Zola** as the static rendering adapter for the site shell, templates,
  layouts, shared header/footer/navigation, and ordinary pages.
- Use **Leptos islands** for interactive pieces that benefit from Rust/WASM:
  dashboards, search/filtering, install command builders, timelines, graphs, and
  browser-local tools.
- Do not render the whole Zola site inside a Leptos island. Zola renders the
  static HTML first; islands mount into explicit placeholders after the page is
  already useful.
- Page bodies may be HTML, Markdown, TOML-backed structured blocks, or a mix.
  Pick the representation that makes a page easiest to maintain. HTML is fine
  for bespoke pages.
- Shared visual chrome belongs to renderer components. In Zola this means
  templates, macros, and includes. Portable repeated content should be promoted
  into renderer-agnostic data blocks rather than copied as layout HTML.
- Add a small progressive navigation enhancer for the “almost SPA” feel only
  after static rendering is stable. It should intercept same-origin page links,
  fetch the target HTML, replace the main content region, update title/history,
  and keep persistent chrome in place. It must fall back to normal navigation
  and must not block first paint.
- Publish QA builds to `averagechris-qa.srht.site` for refactor validation until
  a custom staging domain is configured.

## Canonical data model milestone

Tasks:

- Define the renderer-agnostic site data directories and file naming rules.
- Split durable data from renderer-specific templates. Suggested shape:

  ```text
  site-data/
    site.toml
    projects.toml
    pages/
      now.toml
      now.html
    notes/
      2026-07-03-sccache-rust-ate-my-mac.toml
      2026-07-03-sccache-rust-ate-my-mac.html

  generated/
    fleet.json
    project-artifacts.json
    release-state.json

  renderers/
    zola/
      config.toml
      templates/
      static/
  ```

- Decide the minimal metadata required for every page: slug, title,
  description, date where relevant, listed/draft status, and body format.
- Decide the minimal metadata required for every project: path, name,
  description, repo, tier, downloads flag, extra links, and any future card
  presentation hints.
- Keep existing fleet metadata authoritative for release-tier behavior. Do not
  duplicate release mechanics into Zola front matter.
- Write a schema document or checked loader that rejects ambiguous/missing
  required metadata before rendering.

Requirements:

- A renderer adapter can materialize Zola input from canonical data without
  making Zola front matter the source of truth.
- Content may contain raw HTML, but full page chrome is not embedded in page
  bodies.
- Draft/unlisted content cannot be published accidentally.

## Zola renderer milestone

Tasks:

- Add Zola to the Nix build environment.
- Add a materialization step that reads `site-data/` plus generated fleet JSON
  and writes a temporary Zola site tree.
- Port the root homepage, content pages, notes index/detail pages, project cards,
  project downloads pages, tools page, 404 page, and `siteconfig.json` output.
- Move shared chrome into Zola templates/macros: document shell, masthead,
  footer, project card, download table, note list, and shared metadata tags.
- Preserve current URLs unless a redirect/compatibility decision is documented.
- Keep `nix run .#build-pages` as the stable public build command.

Requirements:

- The generated `dist/site` can be served by `nix run .#serve` and uploaded by
  existing SourceHut Pages publishing commands.
- `state.json` keeps recording the exact durable fleet inputs used for the
  build.
- The Zola renderer is replaceable; canonical data remains outside
  renderer-owned files.

## Leptos islands milestone

Tasks:

- Add a tiny island build pipeline that emits same-origin JS/WASM bundles into
  the static site output.
- Define an island manifest format so templates can mount islands by name,
  script path, WASM path, and static JSON input path.
- Build one first island, preferably a fleet/project widget with obvious value:
  release dashboard, project filter, install command builder, or artifact matrix.
- Ensure islands lazy-mount only when their placeholder exists on the current
  page.
- Ensure islands consume static JSON files generated at build time, not runtime
  server endpoints.
- Keep an inline-data fallback available for island inputs that are small enough
  to embed, in case a live SourceHut Pages CSP/MIME quirk blocks a same-origin
  `fetch()` or WASM asset pattern.

Requirements:

- The site remains useful if JS/WASM fails or is disabled.
- Island assets are self-hosted under the published site; no CDN or Node runtime
  dependency is introduced.
- Islands do not require Leptos server functions.
- Islands do not depend on cross-origin `fetch()`. Any runtime `fetch()` must be
  same-origin and backed by static files in the published tarball.

## Progressive navigation milestone

Tasks:

- Add stable page regions to templates, e.g. persistent chrome plus a
  replaceable `<main id="page-main">`.
- Add a small same-origin navigation enhancer after static pages are stable.
- On enhanced navigation, replace only the main content region, update
  `document.title`, maintain browser history, restore focus sensibly, and scroll
  like a normal page load unless the link requested an anchor.
- Re-run or remount page-specific enhancements and Leptos islands after a body
  swap.
- Respect `prefers-reduced-motion` and avoid heavy transition effects.

Requirements:

- Every link still works as a normal page load without JavaScript.
- The enhancer only handles safe same-origin HTML navigations. Downloads,
  external links, modified clicks, forms, and non-HTML resources use the
  browser default.
- Initial page load speed is more important than transition cleverness. The
  enhancer must be small, dependency-free or Rust/WASM only, and loaded after
  core content.

## SourceHut Pages QA milestone

Tasks:

- Publish production only from `refs/heads/main` via `.builds/pages.yml`.
- Keep production refresh publishing branch-gated to `refs/heads/main` for the
  git.sr.ht integration via `.builds/refresh-pages.yml`; manual/scheduler
  submissions can still use the refresh manifest.
- Add `.builds/qa-pages.yml` to publish `averagechris-qa.srht.site` from
  `refs/heads/qa`, `refs/heads/site-refactor`, or
  `refs/heads/site-rendering-refactor`.
- Build QA with `nix run .#build-pages -- --domain averagechris-qa.srht.site`
  so absolute links and metadata point at the QA domain.

Requirements:

- Refactor branches cannot accidentally publish the production domain via the
  git.sr.ht build integration.
- QA publishes use the same static artifact shape as production.
- The QA domain is temporary and can be replaced by a custom staging domain by
  changing one manifest environment variable.

## Validation milestone

Tasks:

- Compare old and new rendered URL inventories before switching production.
- Check core pages in a no-JS browser mode.
- Check at least one Leptos island on the QA domain after SourceHut Pages
  publishes it, including JS/WASM loading under the Pages CSP.
- Verify release/download URLs and SHA files for every fleet project.
- Verify `state.json` fingerprints and refresh skip behavior.
- Capture the live QA `Content-Security-Policy` header and confirm every chosen
  asset-loading pattern is permitted by that header, including Zola CSS/JS,
  Leptos JS/WASM, static JSON fetches, and the progressive navigation fetch.
- Keep `nix run .#build-pages`, `nix run .#serve`, and `nix run .#publish-pages`
  stable for callers throughout the refactor.

Requirements:

- Production cutover only happens after QA has equivalent static coverage for
  existing pages and downloads.
- Any URL changes are deliberate and documented.
- Performance regressions are treated as refactor blockers, not follow-up polish.
