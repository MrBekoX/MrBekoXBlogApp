# Local builds and the canonical GHCR publication path

Build on a workstation or CI runner with sufficient memory. The three
application images must use one reviewed commit and release tag. Private profile
sources/bundles, provider keys, environment files and runtime checkpoints are
excluded from every build context and must never enter image layers or artifacts.

## Local builds

The historical `deploy-to-hub.ps1` filename is retained for existing callers. The
script now builds locally only; `-Push` and `-SkipBuild` fail before Docker access
and redirect publication to the single manual GHCR workflow.

```powershell
cd D:\MrBekoXBlogApp\deploy
.\deploy-to-hub.ps1 -ReleaseTag 20261024-reviewedsha -SiteUrl https://blog.example.com -AuthorName 'Approved Public Author'
```

The default local tags are `blogapp-local:api-RELEASE`, `blogapp-local:web-RELEASE`
and `blogapp-local:agent-RELEASE`. A custom `-ImageRepository` changes local tag
names only. The script does not authenticate to or push to any registry.

`-SiteUrl` must match `https://DOMAIN` in the production environment. `-AuthorName`
and optional `-GitHubUrl`, `-TwitterUrl`, `-LinkedInUrl`, `-TwitterHandle` values
are explicitly approved PUBLIC site metadata. They are compiled into the web
image; private biographies and account details must not be supplied. Empty social
values omit those links. SignalR and API calls use the same site origin.

`-TurnstileSiteKey` accepts an optional PUBLIC site key for build-argument parity.
The matching workflow input is `turnstile_site_key`. This is reserved configuration:
a Turnstile widget and server verification are not implemented, and this field
does not enable CAPTCHA enforcement. Never supply a server secret here.

## One authorized publisher

`Release image build` in `.github/workflows/image-build.yml` is the only registry
publisher. It has no push/PR trigger and never SSHes to or starts an application
on a server. Run it manually from `main` only when image publication is authorized.
`push_images` defaults to false.

1. The `build` job has `contents: read` only. It builds all three images from the
   triggering commit using immutable base-image digests and no registry credentials.
2. It exports the newly built images to fixed tar files and scans those exact
   files with the pinned Trivy action/binary. HIGH/CRITICAL vulnerabilities or
   detected secrets fail the job; unfixed findings are not suppressed.
3. Only `push_images=true` permits transfer of the scanned code-image tar files
   and checksums through a one-day GitHub artifact. Private runtime data is never
   included. A successful build with `push_images=false` uploads no image artifact.
4. A separate `publish` job requires both explicit publication and the `main`
   branch. Only that job receives `packages: write`. It does not check out source
   or rebuild images. It verifies artifact checksums, exact image IDs supplied by
   the successful build job and commit labels before logging into GHCR.
5. It pushes the same scanned images as
   `ghcr.io/<owner>/<repository>:{api,agent,web}-RELEASE`.

Set the server's `IMAGE_REPOSITORY` to this lowercase GHCR repository and
`RELEASE_TAG` to the same reviewed release. Build-time Next.js public values
cannot be corrected by changing container environment variables after the build.
The private approved profile is supplied separately using the identical read-only
host mount in both API and worker; code images contain only the tracked example.

A security scan can block publication even when compilation succeeds. Existing
application dependency advisories and vendor licensing decisions must be resolved
through the project review process; the publisher has no bypass for them. This
workflow has not been dispatched as part of preparation, and no scan result or
vulnerability-free image claim is implied.

## Immutable dependency maintenance

Action commits were verified against their official repositories and base/service
manifest index digests against the primary registries on 2026-10-24. Workflows
retain version comments beside immutable commits; Dockerfiles retain readable
tags beside index digests. These pins preserve image architecture selection.

When updating a pin, resolve the official action reference or registry manifest,
review the source/release change, update the pin, and rerun source, package,
configuration and newly built image checks. Registry metadata can be inspected
without pulling an image or starting a Docker daemon:

```bash
docker buildx imagetools inspect node:24-alpine
```

Relevant primary sources are the [Docker Actions repositories](https://github.com/docker),
[Trivy action](https://github.com/aquasecurity/trivy-action/releases/tag/v0.36.0)
and [Trivy binary release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.1).
Continue with [the EC2 runbook](PRODUCTION_DEPLOYMENT.md) after separately
reviewing and authorizing publication. A build/scan does not validate production
credentials, real provider behavior, browser events or t3.micro capacity.
