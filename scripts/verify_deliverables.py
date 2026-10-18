"""
verify_deliverables.py
Checks that all EchoForge required deliverables are present and non-empty.
Exit code 0 = all checks pass. Exit code 1 = one or more checks fail.
"""

import os
import sys

REQUIRED_FILES = [
    "README.md",
    "requirements.txt",
    ".env.example",
    "docker-compose.yml",
    "Dockerfile",
    "docs/schema.md",
    "docs/submission.md",
    "docs/demo_script.md",
    "app/main.py",
    "app/components/graph_viz.py",
    "app/components/ui_helpers.py",
    "db/connection.py",
    "db/schema.py",
    "db/seed.py",
    "db/queries.py",
    "db/traversal.py",
    "db/branch_service.py",
    "db/history.py",
    "agents/base_agent.py",
    "agents/scenario_agent.py",
    "agents/critic_agent.py",
    "agents/outcome_evaluator.py",
    "agents/coordinator.py",
    "core/comparison.py",
    "tests/test_agents.py",
    "tests/test_history.py",
    "tests/test_traversal.py",
    "tests/test_integration.py",
    "scripts/init_db.py",
    "pyproject.toml",
    ".gitignore",
]

MIN_SIZE_BYTES = 100

def main() -> int:
    # Determine repo root: script lives in scripts/, so parent is root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    all_pass = True
    results = []

    for rel_path in REQUIRED_FILES:
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(abs_path):
            results.append((rel_path, "FAIL", "File not found"))
            all_pass = False
            continue
        size = os.path.getsize(abs_path)
        if size < MIN_SIZE_BYTES:
            results.append((rel_path, "FAIL", f"Too small ({size} bytes < {MIN_SIZE_BYTES})"))
            all_pass = False
        else:
            results.append((rel_path, "PASS", f"{size:,} bytes"))

    # Print results
    sep = "=" * 70
    print(sep)
    print("EchoForge Deliverable Verification")
    print(sep)
    col_w = max(len(r[0]) for r in results) + 2
    for path, status, detail in results:
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"  {marker} {path:<{col_w}}  ({detail})")

    print(sep)
    passed = sum(1 for r in results if r[1] == "PASS")
    failed = len(results) - passed
    print(f"  Passed: {passed}/{len(results)}   Failed: {failed}/{len(results)}")
    print(sep)

    if all_pass:
        print("\nALL PASS: All deliverables present and non-empty. Ready for submission.")
        return 0
    else:
        print(f"\nFAIL: {failed} deliverable(s) failed. Fix the issues above before submission.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
