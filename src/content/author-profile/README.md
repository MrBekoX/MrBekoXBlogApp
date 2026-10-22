# Synthetic author profile

This directory contains fictional demonstration data. The profile feature, schemas and validation remain reusable.

Keep private biography files outside Git. Deploy an approved corpus using AuthorProfile:Directory for the API and an absolute AGENT_PROFILE_DIR for the Python agent. Do not commit private credentials, contact data or production exports.

After editing the sample, synchronize source.sha256 and provenance.raw_sha256, then run:

    python src/content/author-profile/tools/update_manifest.py --bump
    python src/content/author-profile/tools/update_manifest.py --check

All supplied sections and contact links are synthetic. example.invalid is a placeholder.
