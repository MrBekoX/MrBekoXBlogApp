# Release checklist

No deployment is performed by copying these files. Keep the API keys empty until
configured locally; missing values deliberately stop composition.

1. Read [the EC2 runbook](PRODUCTION_DEPLOYMENT.md), including existing-volume
   preservation, encrypted EBS, TLS/ALB boundary and t3.micro swap requirements.
   Configure `ALB_TRUSTED_CIDRS` with the ALB's actual node-subnet CIDRs and keep
   ALB X-Forwarded-For processing in append mode. Check the dedicated proxy
   subnet for overlap before applying.
2. Build all three images away from EC2 using
   [the release build guide](DOCKER_HUB_DEPLOYMENT.md). The manual GHCR workflow is the only publisher; local builds never push.
3. Prepare `uploads`/`keys` with UID:GID 1001:1001, fill `.env` from `.env.example`,
   and use the same immutable image release tag for API, web and agent. Build the
   frontend with a site URL matching `https://DOMAIN` and the approved author name.
4. Install the approved private author-profile bundle on encrypted EBS; set
   `AUTHOR_PROFILE_HOST_DIR` to its absolute path. It must remain outside Git,
   build contexts, images and registries; both services mount it read-only.
5. Run `bash deploy.sh --check` on Linux. For a brand-new installation without
   data volumes use `bash deploy.sh --check --first-install`.
6. Only after deployment approval, run the matching `--apply` command from the
   runbook. Existing database backup failures abort the upgrade.
7. Complete real-provider, persistent-retrieval, browser SignalR and memory/load
   acceptance before routing users. Static checks do not certify live behavior.

The default script action validates only; it neither pulls images nor starts
containers. A 1 GiB host without 2 GiB swap is rejected. No successful t3.micro
runtime or live-provider validation is implied by these files.
