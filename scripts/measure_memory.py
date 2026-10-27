"""Measure container startup and model warm-up RSS using optional psutil."""

import argparse

from app.container import Container
from app.core.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["full", "lite"], default="lite")
    args = parser.parse_args()
    try:
        import psutil
    except ImportError:
        print("Skipped: install psutil to measure memory.")
        return
    from threading import Event, Thread

    process = psutil.Process()
    peak = process.memory_info().rss
    stop = Event()

    def sample() -> None:
        nonlocal peak
        while not stop.wait(0.01):
            peak = max(peak, process.memory_info().rss)

    sampler = Thread(target=sample, daemon=True)
    sampler.start()
    try:
        container = Container.build(
            Settings(
                _env_file=None,
                deployment_profile=args.profile,
                app_env="local",
                qdrant_url=":memory:",
                database_url="sqlite:///:memory:",
                llm_provider_order=[],
            )
        )
        try:
            container.warm_models()
            peak = max(peak, process.memory_info().rss)
        finally:
            container.close()
    finally:
        stop.set()
        sampler.join()
    print(f"profile={args.profile} peak_rss_mib={peak / 1024**2:.1f}")


if __name__ == "__main__":
    main()
