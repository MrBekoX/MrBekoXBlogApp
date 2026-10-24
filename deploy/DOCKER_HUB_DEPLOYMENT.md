# Build and optionally publish a release

Build on a workstation or CI runner with sufficient memory, never on t3.micro.
All three images must be built from the same checkout and share one release tag.
No provider credentials are passed as build arguments or copied into the images.
Dockerfile-specific ignore files exclude local `.env`, keys and build caches.
The frontend builds and runs on Node 24 LTS; Node 20 has reached end of life.

```powershell
cd D:\MrBekoXBlogApp\deploy
# Local build only. Replace the example tag with the reviewed commit/release ID.
.\deploy-to-hub.ps1 -ReleaseTag 20261024-reviewedsha -SiteUrl https://blog.example.com -AuthorName 'Approved Public Author'
```

The script builds `linux/amd64` images:

- `mrbeko/blog-app:api-20261024-reviewedsha`
- `mrbeko/blog-app:web-20261024-reviewedsha`
- `mrbeko/blog-app:agent-20261024-reviewedsha`

Set `-SiteUrl` to exactly `https://` plus the server `.env` `DOMAIN`, and set
`-AuthorName` to the approved public identity used by the canonical profile bundle.
The builder and manual workflow reject HTTP origins and the sample author name.
These public values are compiled into the client; do not supply private identity data.
Optional approved public social metadata can be supplied using `-GitHubUrl`,
`-TwitterUrl`, `-LinkedInUrl` and `-TwitterHandle`. Empty values omit the links;
URLs must use HTTPS without credentials, query strings or fragments. The manual
workflow exposes matching optional inputs. No private profile file is consumed
by either image-building path.

Public frontend URLs use the same origin: `/api/v1` and `/hubs/*`. The Python image includes Alembic migrations. Both API/worker code images contain
only the tracked example profile; production overrides it using one required
private readonly host bind mount. Personal profile/source bundles must never be
added to build contexts, copied into images, uploaded as artifacts or published.
The Dockerfile ignore rules exclude private sources and runtime checkpoints. The frontend image uses the internal `http://api:8080` rewrite;
these build-time Next.js values cannot be corrected by container environment
changes after build. An alternative deployment hostname for SignalR requires
`-PublicSignalRUrl https://...` and an aligned proxy/CORS policy.

Registry publishing is a separate, explicitly requested operation. Authenticate
with `docker login` first; the script never prompts for or captures your password.
Only when publishing is authorized:

```powershell
.\deploy-to-hub.ps1 -ReleaseTag 20261024-reviewedsha -SiteUrl https://blog.example.com -AuthorName 'Approved Public Author' -Push
# Publish already built images, without rebuilding:
.\deploy-to-hub.ps1 -ReleaseTag 20261024-reviewedsha -SiteUrl https://blog.example.com -AuthorName 'Approved Public Author' -SkipBuild -Push
```

Use `-ImageRepository registry.example.com/team/blog` for another repository.
Set matching `IMAGE_REPOSITORY` and `RELEASE_TAG` in the server `.env`. The manual
GitHub `Release image build` workflow uses GHCR; it builds all three images before
its optional push step, and does not SSH to or modify any server. Its
`push_images` input defaults to false. Its `site_url` and `author_name` inputs
are required and must match the reviewed production domain/public profile. It must be dispatched only when desired.

A successful image build is packaging evidence. It does not validate production
credentials, live embeddings, browser events or t3.micro resource behavior.
Continue with [the EC2 runbook](PRODUCTION_DEPLOYMENT.md) after image preparation.
