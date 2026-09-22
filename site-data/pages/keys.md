My PGP key:

```text
Fingerprint: E026 151F 7880 7B8E 6012 590F 6237 45A8 3D6C 9C02
Type:        ed25519
UID:         Chris Cummings <chris@thesogu.com>
Download:    https://meta.sr.ht/~averagechris.pgp
```

Import it with:

```sh
curl -s https://meta.sr.ht/~averagechris.pgp | gpg --import
```

My SSH public keys are published by SourceHut here:

```text
https://meta.sr.ht/~averagechris.keys
```

Project release downloads live under each project subdirectory, usually like this:

```text
https://averagechris.github.io/<project>/downloads/<artifact-name>
```

Every project downloads page publishes a `manifest.json` with per-artifact sha256 values, and `.sha256` files sit alongside the tarballs. For example:

```sh
curl -fsSLO https://averagechris.github.io/gander/downloads/gander-v0.3.0-aarch64-darwin.tar.gz
curl -fsSLO https://averagechris.github.io/gander/downloads/gander-v0.3.0-aarch64-darwin.tar.gz.sha256
shasum -a 256 -c gander-v0.3.0-aarch64-darwin.tar.gz.sha256
```

Or, if you want to compare against the JSON manifest instead of the sidecar file:

```sh
curl -fsSLO https://averagechris.github.io/gander/downloads/gander-v0.3.0-aarch64-darwin.tar.gz
curl -fsSL https://averagechris.github.io/gander/manifest.json | grep -A1 aarch64-darwin
shasum -a 256 gander-v0.3.0-aarch64-darwin.tar.gz
```

That verifies the bytes you downloaded against the hash I published. It does not yet verify a signature.

Honest status: release artifacts are currently checksummed, not signed. Signed manifests are planned, probably with signify/minisign or PGP. I would like the release process to be boring enough that future me cannot creatively forget the important step.
