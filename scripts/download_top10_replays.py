"""Download every listed episode for the current Kaggriculture top 10 via Kaggle CLI."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def cli_json(args):
    command = [os.environ.get("KAGGLE_PYTHON", "python"), "-m", "kaggle",
               *args, "--format", "json"]
    for attempt in range(1, 4):
        proc = subprocess.run(command, capture_output=True, text=True)
        # Leaderboard JSON is currently preceded by a human-readable next-page
        # token. Find the first JSON container instead of assuming byte zero.
        starts = [i for i in (proc.stdout.find("["), proc.stdout.find("{")) if i >= 0]
        if proc.returncode == 0 and starts:
            value, _ = json.JSONDecoder().raw_decode(proc.stdout[min(starts):])
            return value
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Kaggle CLI failed: {(proc.stderr or proc.stdout).strip()}")


def download_replay(episode_id, replay_dir, retries=100):
    target = replay_dir / f"episode-{episode_id}-replay.json"
    if target.exists() and target.stat().st_size > 0:
        return episode_id, "existing", None
    for attempt in range(1, retries + 1):
        proc = subprocess.run(
            [os.environ.get("KAGGLE_PYTHON", "python"), "-m", "kaggle",
             "competitions", "replay", str(episode_id), "-p", str(replay_dir), "-q"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return episode_id, "downloaded", None
        if attempt < retries:
            error_text = (proc.stderr or proc.stdout)
            delay = 60 if "429" in error_text or "Too Many Requests" in error_text else min(60, 5 * (2 ** (attempt - 1)))
            time.sleep(delay)
    
    return episode_id, "failed", (proc.stderr or proc.stdout).strip()


def run(root, workers=1):
    root = Path(root)
    leaderboard_dir = root / "leaderboard"
    lists_dir = root / "episode_lists"
    replay_dir = root / "replays"
    for directory in (leaderboard_dir, lists_dir, replay_dir):
        directory.mkdir(parents=True, exist_ok=True)

    leaderboard = cli_json([
        "competitions", "leaderboard", "kaggriculture", "-s", "--page-size", "20"
    ])[:10]
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    entries = []
    unique_episodes = {}
    for rank, team in enumerate(leaderboard, start=1):
        submissions = cli_json([
            "competitions", "team-submissions", str(team["teamId"])
        ])
        if not submissions:
            raise RuntimeError(f"no public submission for team {team['teamId']} ({team['teamName']})")
        matching = [s for s in submissions if str(s.get("publicScore")) == str(team.get("score"))]
        submission = matching[0] if matching else submissions[0]
        submission_id = submission["id"]
        episodes = cli_json(["competitions", "episodes", str(submission_id)])
        list_path = lists_dir / f"{submission_id}.json"
        list_path.write_text(json.dumps(episodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for episode in episodes:
            unique_episodes[episode["id"]] = episode
        entries.append({
            "rank": rank,
            "team_id": team["teamId"],
            "team_name": team["teamName"],
            "score": team["score"],
            "submission_date": team["submissionDate"],
            "submission_id": submission_id,
            "episode_count": len(episodes),
            "episode_list": str(list_path.relative_to(root)),
        })
        print(f"resolved rank {rank}: {team['teamName']} -> {submission_id} ({len(episodes)} episodes)", flush=True)

    manifest = {
        "competition": "kaggriculture",
        "captured_at": captured_at,
        "top_n": 10,
        "entries": entries,
        "listed_episode_references": sum(x["episode_count"] for x in entries),
        "unique_episode_count": len(unique_episodes),
    }
    manifest_path = leaderboard_dir / "top10_current.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts = {"downloaded": 0, "existing": 0, "failed": 0}
    failures = {}
    episode_ids = sorted(unique_episodes)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_replay, episode_id, replay_dir): episode_id
                   for episode_id in episode_ids}
        for completed, future in enumerate(as_completed(futures), start=1):
            episode_id, status, error = future.result()
            counts[status] += 1
            if error:
                failures[str(episode_id)] = error
            if completed % 50 == 0 or completed == len(episode_ids):
                print(f"replays {completed}/{len(episode_ids)}: {counts}", flush=True)

    status = {**manifest, "download_counts": counts, "failures": failures}
    (leaderboard_dir / "download_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if failures:
        raise RuntimeError(f"{len(failures)} replay downloads failed; rerun to retry")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("kaggle_replays"))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    run(args.root, max(1, args.workers))


if __name__ == "__main__":
    main()
