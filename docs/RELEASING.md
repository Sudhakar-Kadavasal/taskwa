# Release checklist (maintainer)

1. **Green suite** — `python3 -m pytest tests/ -q` → all pass.
2. **CHANGELOG.md** — add the new version section, date it.
3. **VERSION** — bump the number (matches the changelog).
4. **Commit & tag**
   ```bash
   git add -A && git commit -m "Release vX.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```
5. **GitHub release** — Releases → *Draft a new release* → pick the tag →
   paste the CHANGELOG section → attach nothing (source archives are
   automatic) → Publish.
6. **Verify CI** — the Actions tab shows tests + Docker build green on the
   tag.
7. **Live upgrade test** — on the production install:
   `git pull && docker compose up -d --build`, then the three checks in
   `UPGRADE.md`.

## Someday / deliberately deferred

- Multi-arch prebuilt images on GHCR (removes the local build step for
  installers) — add once release cadence stabilises.
- Real screenshots in the Installation Guide replacing the drawn
  illustrations.
