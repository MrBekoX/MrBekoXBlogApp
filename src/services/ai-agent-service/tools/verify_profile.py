"""Validate a private runtime profile and its owner routing without model calls."""

import argparse
import asyncio
from pathlib import Path

from agent_core.entrypoints import prepare_and_route
from agent_core.models import BudgetProfile, ExecutionContext, RunIntent
from agent_core.profile import load_profile_source
from agent_core.profile.detection import ProfileIdentity


async def verify(directory: Path) -> None:
    document = load_profile_source(directory)
    identity = ProfileIdentity.from_document(document)
    context = ExecutionContext(
        run_id="private-profile-verification", conversation_id="private-profile-verification",
        question=document.owner.name + " kimdir?", language="tr", mode_preference="auto",
        budget_profile=BudgetProfile(name="offline-validation", max_model_calls=1,
                                     max_total_tokens=1000, max_duration_seconds=10),
    )
    prepared = await prepare_and_route(context, profile_identity=identity)
    if prepared.route.intent is not RunIntent.PROFILE:
        raise RuntimeError("Canonical owner routing failed; personal content was not logged")
    print("Python profile contract and canonical owner routing verified without a model request.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    asyncio.run(verify(args.directory))
