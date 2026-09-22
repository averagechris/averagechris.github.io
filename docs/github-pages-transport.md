# GitHub Pages transport

The site registry remains a generated fleet projection. A repository opts in
with `provider = "github"`, `github_repo = "owner/name"`, and an explicit
`expected_platforms` release contract; omitted provider continues to mean
SourceHut and retains its flexible four-platform discovery. Gander expects
`aarch64-darwin` and `x86_64-linux` and has a complete, published GitHub Release.

GitHub drafts are ignored. A release is published only after every configured
asset and its `.sha256` sidecar is complete. Refresh uses the API asset listing
(rather than interpreting download redirects), pins `main`, and accepts only
semver release tags. Candidate building is non-publishing; the Actions deploy
job alone publishes its `dist/site` artifact. Actions authenticates API reads
with its scoped `GITHUB_TOKEN`, and only published tags are peeled. SourceHut
keeps its existing publisher as a manually submitted rollback path; no
SourceHut `main` push automatically submits it.
