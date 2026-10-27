"""Publish the minimal Docker build context to a public Space."""

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi

from app.core.config import Settings
from app.core.errors import ConfigurationError

SECRETS = (
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "DATABASE_URL",
    "ADMIN_TOKEN",
)
ALLOW_PATTERNS = ["Dockerfile", "pyproject.toml", "uv.lock", "app/**", "scripts/download_models.py"]


def deploy_space(repo_id: str, root: Path, settings: Settings, dry_run: bool = False) -> str:
    secrets = {}
    for name in SECRETS:
        value = getattr(settings, name.lower())
        if value:
            secrets[name] = (
                value.get_secret_value() if hasattr(value, "get_secret_value") else value
            )
    variables = {
        "APP_ENV": "prod",
        "QDRANT_COLLECTION": settings.qdrant_collection,
        "WARMUP": "true",
        "MODEL_CACHE_DIR": "/app/.cache/models",
        "LLM_PROVIDER_ORDER": json.dumps(settings.llm_provider_order),
        "EMBEDDING_MODEL": settings.embedding_model,
        "RERANKER_MODEL": settings.reranker_model,
        "NLI_MODEL": settings.nli_model,
        "LLM_PRIMARY_MODEL": settings.llm_primary_model,
        "LLM_FALLBACK_MODEL": settings.llm_fallback_model,
        "OPENROUTER_MODEL": settings.openrouter_model,
    }
    if dry_run:
        print("Upload patterns: " + ", ".join(ALLOW_PATTERNS))
        paths = {
            path
            for pattern in ALLOW_PATTERNS
            for path in root.glob(pattern.replace("/**", "/**/*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        for path in sorted(paths):
            print(path.relative_to(root).as_posix())
        print("deploy/space/README.md -> README.md")
        print("Secrets: " + ", ".join(sorted(secrets)))
        print("Variables: " + ", ".join(sorted(variables)))
    else:
        if not settings.hf_token:
            raise ConfigurationError("HF_TOKEN is required")
        if settings.qdrant_url == ":memory:" or settings.database_url.startswith("sqlite:"):
            raise ConfigurationError("Deployment requires persistent remote databases")
        api = HfApi(token=settings.hf_token.get_secret_value())
        api.create_repo(
            repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True
        )
        for name, value in secrets.items():
            api.add_space_secret(repo_id, key=name, value=value)
        for name, value in variables.items():
            api.add_space_variable(repo_id, key=name, value=value)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(root),
            allow_patterns=ALLOW_PATTERNS,
            ignore_patterns=["**/__pycache__/**", "**/*.pyc"],
        )
        api.upload_file(
            repo_id=repo_id,
            repo_type="space",
            path_in_repo="README.md",
            path_or_fileobj=str(root / "deploy/space/README.md"),
        )
    url = f"https://huggingface.co/spaces/{repo_id}"
    print(url)
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id", help="HF username/space-name")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    deploy_space(args.repo_id, Path(__file__).resolve().parents[1], Settings(), args.dry_run)


if __name__ == "__main__":
    main()
