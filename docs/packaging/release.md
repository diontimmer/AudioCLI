# Releasing to PyPI

AudioCLI uses a **tag-driven release workflow** with [PyPI Trusted Publishers (OIDC)](https://docs.pypi.org/trusted-publishers/) — no API tokens stored in the repo, no secrets to rotate. The day-to-day release flow is two commands.

## One-time setup

You only do this once per project. After it's configured, every future release is just a tag push.

### 1. Add a Trusted Publisher on PyPI

Go to [pypi.org/manage/project/audiocli/settings/publishing/](https://pypi.org/manage/project/audiocli/settings/publishing/) and click **Add a new publisher** under "Trusted publishers".

Fill in:

| Field | Value |
|---|---|
| Owner | `diontimmer` |
| Repository name | `AudioCLI` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` |

Save.

This tells PyPI: "any time GitHub Actions on `diontimmer/AudioCLI` runs the `release.yml` workflow inside the `pypi` environment, accept its OIDC token as proof of identity and let it publish under the `audiocli` project."

### 2. Create the `pypi` environment on the repo

In GitHub: **Settings → Environments → New environment**, name it `pypi`.

Optional but recommended:

- **Required reviewers**: add yourself, so every release needs one click of approval before it actually publishes. This is your "are you sure?" guard.
- **Deployment branches**: restrict to `main` (or `main` + `v*` tags) so a publish can't happen from a random branch.

The environment doesn't need any secrets — auth is handled by OIDC.

## Releasing

Once the one-time setup is done, every release is:

```shell
# 1. Bump version in pyproject.toml
#    (must match the tag you're about to push)

# 2. Update CHANGELOG.md with the new section

# 3. Commit the version bump
git commit -am "release: v2.1.0"

# 4. Tag and push
git tag v2.1.0
git push origin main
git push origin v2.1.0
```

The tag push triggers `.github/workflows/release.yml`, which:

1. Verifies the tag (e.g. `v2.1.0`) matches the version in `pyproject.toml`. Mismatch fails fast.
2. Builds `sdist` and `wheel` via `python -m build`.
3. Runs `twine check --strict` on the artifacts.
4. Pauses for manual approval (if you configured required reviewers on the `pypi` environment).
5. Publishes to PyPI via OIDC trusted publisher.
6. Creates a GitHub Release with release notes extracted from the matching `## [2.1.0]` section in `CHANGELOG.md`, with the built wheel + sdist attached.

## Manual re-trigger

If something goes wrong mid-flight (e.g. PyPI is down), the workflow can be re-run for an existing tag from the Actions tab via **Run workflow** → enter the tag name. PyPI is idempotent for the *same* version + artifacts; if the wheel content changed, you'd need to bump to a new version.

## Pre-releases

PyPI accepts PEP 440 pre-release suffixes. To cut an alpha:

```shell
# pyproject.toml: version = "2.1.0a1"
git tag v2.1.0a1
git push origin v2.1.0a1
```

`pip install audiocli` skips pre-releases by default. Users who want it run `pip install --pre audiocli`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Workflow fails at "Verify tag matches pyproject version" | Tag and `pyproject.toml` `[project].version` disagree. Fix one. |
| `twine check` fails | Bad README rendering (broken Markdown, missing description). Fix and retag. |
| PyPI upload fails with `403 invalid-publisher` | Trusted publisher config on PyPI doesn't match the workflow. Double-check owner / repo / workflow filename / environment name are exactly as listed above. |
| GitHub Release step fails | `softprops/action-gh-release` couldn't find the artifacts or the tag already had a release. Delete the partial release manually and re-run the workflow. |
