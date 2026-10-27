import argparse
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.errors import MigrationError
from app.corpus.migrate import migrate_sql, migrate_vectors


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Copy an index to cloud stores")
    parser.add_argument("--source-qdrant", default="http://localhost:6333")
    parser.add_argument("--source-collection", default="documents")
    parser.add_argument("--target-qdrant", default=settings.qdrant_url)
    parser.add_argument(
        "--target-api-key",
        default=(settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None),
    )
    parser.add_argument("--target-collection", default=settings.qdrant_collection)
    parser.add_argument("--source-db", default="sqlite:///./data/registry_documents.db")
    parser.add_argument("--target-db", default=settings.database_url)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/migrate_checkpoint.json"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.source_qdrant.rstrip("/") == args.target_qdrant.rstrip("/"):
        raise MigrationError("Migration requires a separate target Qdrant endpoint")
    if make_url(args.source_db) == make_url(args.target_db):
        raise MigrationError("Migration requires a separate target database")
    target_host = urlparse(args.target_qdrant).hostname
    if args.target_collection == "documents" and target_host in {"localhost", "127.0.0.1", "::1"}:
        raise MigrationError("The local documents collection is protected")
    protected_db = Path("data/registry_documents.db").resolve()
    requested_target = make_url(args.target_db)
    if (
        requested_target.get_backend_name() == "sqlite"
        and Path(requested_target.database).resolve() == protected_db
    ):
        raise MigrationError("The local registry database is protected")
    source_url = make_url(args.source_db)
    if source_url.get_backend_name() == "sqlite":
        source_path = Path(source_url.database).resolve()
        target_url = make_url(args.target_db)
        if (
            target_url.get_backend_name() == "sqlite"
            and Path(target_url.database).resolve() == source_path
        ):
            raise MigrationError("Source and target database paths must differ")
        source_db = create_engine(f"sqlite:///file:{source_path.as_posix()}?mode=ro&uri=true")
    else:
        source_db = create_engine(source_url)
    target_url = make_url(args.target_db)
    if target_url.drivername == "postgresql":
        target_url = target_url.set(drivername="postgresql+psycopg")
    target_db = create_engine(target_url)
    try:
        with (
            closing(QdrantClient(url=args.source_qdrant)) as source,
            closing(
                QdrantClient(
                    url=args.target_qdrant,
                    api_key=args.target_api_key,
                )
            ) as target,
        ):
            count = migrate_vectors(
                source,
                target,
                args.source_collection,
                args.target_collection,
                args.checkpoint,
                args.batch,
                identity=f"{args.source_qdrant}|{args.target_qdrant}",
                replace=args.replace,
            )
            counts = migrate_sql(source_db, target_db, args.replace)
            print(f"Verified {count} vectors; SQL rows: {counts}")
    finally:
        source_db.dispose()
        target_db.dispose()


if __name__ == "__main__":
    main()
