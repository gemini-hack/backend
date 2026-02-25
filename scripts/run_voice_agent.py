import subprocess
import sys
import time
import argparse
from pathlib import Path

# Backoff configuration
INITIAL_DELAY = 1.0
MAX_DELAY = 30.0
BACKOFF_FACTOR = 2.0
HEALTHY_THRESHOLD = 60.0


def main():
    """Supervise the MIRA voice agent and auto-restart on crash.

    The livekit-rtc Rust layer can trigger FFI panics (e.g. ``ParseIntError``
    on disconnect) that kill the process at the OS level. This wrapper runs
    the agent as a subprocess and restarts it with exponential backoff.

    Example:
        $ python scripts/run_voice_agent.py
        $ python scripts/run_voice_agent.py --max-restarts 0
    """

    parser = argparse.ArgumentParser(description="Auto-restart wrapper for MIRA voice agent")
    parser.add_argument(
        "--max-restarts", type=int, default=20,
        help="Maximum consecutive crash restarts (0 = unlimited). Resets after stable run.",
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "app.agents.livekit_gemini.main", "start"]

    restart_count = 0
    delay = INITIAL_DELAY

    print(f"[supervisor] Starting MIRA voice agent (max restarts: {args.max_restarts or 'unlimited'})")

    while True:
        start_time = time.monotonic()
        print(f"[supervisor] Launching worker (attempt {restart_count + 1})...")

        result = subprocess.run(cmd, cwd=backend_dir)
        elapsed = time.monotonic() - start_time

        # Clean exit (e.g. Ctrl+C or graceful shutdown)
        if result.returncode == 0:
            print("[supervisor] Worker exited cleanly.")
            break

        # Crash detected
        print(
            f"[supervisor] Worker crashed with exit code {result.returncode} "
            f"after {elapsed:.1f}s"
        )

        # If worker ran long enough, reset backoff
        if elapsed >= HEALTHY_THRESHOLD:
            restart_count = 0
            delay = INITIAL_DELAY
            print("[supervisor] Was healthy for >60s — resetting backoff.")

        restart_count += 1

        if args.max_restarts and restart_count > args.max_restarts:
            print(f"[supervisor] Exceeded {args.max_restarts} consecutive restarts. Giving up.")
            sys.exit(1)

        print(f"[supervisor] Restarting in {delay:.1f}s...")
        time.sleep(delay)
        delay = min(delay * BACKOFF_FACTOR, MAX_DELAY)


if __name__ == "__main__":
    main()
