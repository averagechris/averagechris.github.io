# Website agent guide

This repository is the single Pages publisher for
<https://averagechris.srht.site/>. It owns project presentation, remote artifact
acquisition, caches/state, Zola rendering, refresh logic, and publication.

Fleet release policy, the full operational registry, audits, templates, and
bootstrap tooling live in <https://github.com/averagechris/fleet>. This repo's
`fleet-site.toml` is a generated projection containing only fields required for
site acquisition. Do not add local checkout paths, quirks, tracker policy, or
other operational fields. The flake temporarily forwards the pinned fleet
input's `lib` output for compatibility.

Release artifacts and refresh triggers still use SourceHut. Do not migrate that
backend incidentally, submit builds, trigger releases, or publish Pages unless
explicitly requested. Any SourceHut request must keep the existing user-agent,
retry, OAuth `--secrets`, and `sourcehut_auth.sh` behavior.

Use jj for version control. Validate site data with
`PYTHONPATH=scripts python3 -m averagechris_site.data --check` and run the Python
tests. Changes affecting rendered output require the structural comparison
described in `docs/architecture.md`.

Zola is the sole renderer. `generated/fleet.json`, `dist/`, artifact caches,
`release-artifacts.toml`, and `release-dates.toml` remain website concerns.
Website apps (`build-pages`, `publish-pages`, `refresh-pages`, `serve`) are
excluded from the generic cache closure, so force-build an edited app locally.
Never publish notes; leave drafts for review.
