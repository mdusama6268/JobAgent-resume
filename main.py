import argparse
import asyncio
import os
import sys
from pathlib import Path
from config import Config
from agent import JobAgent
from searcher import JobSearcher
from session_manager import SessionManager


def build_parser() -> argparse.ArgumentParser:
    """Builds command-line argument parser with subcommands and root flags."""
    parser = argparse.ArgumentParser(
        description="JOBAGENT: Autonomous Job Search, Session Management & Form Filling System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. 'apply' command
    apply_parser = subparsers.add_parser("apply", help="Automate filling out an online job application form")
    apply_parser.add_argument("--url", type=str, help="Target application URL")
    apply_parser.add_argument("--sample", action="store_true", help="Run against local sample_form.html")
    apply_parser.add_argument("--auto-submit", action="store_true", help="Automatically click Submit button upon filling")
    apply_parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    apply_parser.add_argument("--model", type=str, help="Override Ollama model name (default: llama3.2)")
    apply_parser.add_argument("--profile", type=str, help="Path to profile JSON")
    apply_parser.add_argument("--no-pause", action="store_true", help="Skip terminal pause prompt")

    # 2. 'search' command
    search_parser = subparsers.add_parser("search", help="Search job portals for target roles")
    search_parser.add_argument("--query", type=str, default="Operations Lead", help="Job title / keywords to search")
    search_parser.add_argument("--location", type=str, default="Remote", help="Job location or region")
    search_parser.add_argument("--limit", type=int, default=5, help="Number of results to extract")
    search_parser.add_argument("--batch", action="store_true", help="Batch search all target roles from profile.json")
    search_parser.add_argument("--test", action="store_true", help="Run in mock/test mode without live portal calls")

    # 3. 'login' command
    login_parser = subparsers.add_parser("login", help="Open browser to log in and save persistent cookies")
    login_parser.add_argument("--portal", type=str, default="LinkedIn", help="Portal name (e.g. LinkedIn, Naukri)")
    login_parser.add_argument("--url", type=str, default="https://www.linkedin.com/login", help="Login URL")

    # Legacy flags on root parser for direct backwards compatibility
    parser.add_argument("--url", type=str, help="Target application URL")
    parser.add_argument("--sample", action="store_true", help="Run against local sample_form.html")
    parser.add_argument("--auto-submit", action="store_true", help="Automatically click Submit button")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--model", type=str, help="Ollama model")
    parser.add_argument("--no-pause", action="store_true", help="Skip pause")

    return parser


async def run_apply(args):
    """Executes the autonomous form-filling agent."""
    cfg = Config()
    if getattr(args, "headless", False):
        cfg.BROWSER_HEADLESS = True
    if getattr(args, "auto_submit", False):
        cfg.AUTO_SUBMIT = True
    if getattr(args, "model", None):
        cfg.OLLAMA_MODEL = args.model
    if getattr(args, "profile", None):
        cfg.PROFILE_PATH = args.profile

    target_url = getattr(args, "url", None)
    if getattr(args, "sample", False):
        sample_path = Path(__file__).parent / "sample_form.html"
        target_url = sample_path.resolve().as_uri()
        print(f"[*] Running in SAMPLE mode using local test form: {target_url}")
    elif not target_url:
        sample_path = Path(__file__).parent / "sample_form.html"
        target_url = sample_path.resolve().as_uri()
        print(f"[*] Defaulting to local test form: {target_url}")

    agent = JobAgent(cfg)
    result = await agent.run(
        target_url=target_url,
        auto_submit=cfg.AUTO_SUBMIT,
        pause_on_completion=not getattr(args, "no_pause", False)
    )

    print("\n" + "=" * 60)
    print("Session Result Summary:")
    print(f"  - Filled:    {result.get('filled', 0)}")
    print(f"  - Skipped:   {result.get('skipped', 0)}")
    print(f"  - Failed:    {result.get('failed', 0)}")
    print(f"  - Submitted: {result.get('submitted', False)}")
    print("=" * 60 + "\n")


async def run_search(args):
    """Executes the job search module."""
    searcher = JobSearcher()
    if args.batch:
        await searcher.batch_search(location=args.location, test_mode=args.test)
    else:
        results = await searcher.search_jobs(
            query=args.query,
            location=args.location,
            limit=args.limit,
            test_mode=args.test
        )
        print(f"\n[*] Discovered {len(results)} jobs for '{args.query}' in '{args.location}':")
        for idx, job in enumerate(results, 1):
            print(f"  {idx}. {job['title']} @ {job['company']} ({job['location']})")
            print(f"     URL: {job['url']}")


async def run_login(args):
    """Opens persistent browser context for user login."""
    manager = SessionManager()
    await manager.interactive_login(portal_name=args.portal, portal_url=args.url)


async def main():
    parser = build_parser()
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("   JOBAGENT - Autonomous Job Search & Application System")
    print("=" * 65)

    if args.command == "search":
        await run_search(args)
    elif args.command == "login":
        await run_login(args)
    elif args.command == "apply" or args.url or args.sample:
        await run_apply(args)
    else:
        # Interactive Menu
        print("\nSelect an action:")
        print("  1. Run Form-Filler on Sample Form (with Auto-Submit)")
        print("  2. Run Form-Filler on a custom Job URL")
        print("  3. Search for Target Roles (AI Workflow Specialist, Operations Lead, Product Manager)")
        print("  4. Login to Job Portal (Save persistent session cookies)")
        print("  5. Exit\n")

        try:
            choice = input("Enter choice [1-5] (default: 1): ").strip()
        except EOFError:
            choice = "1"

        if choice in ("1", ""):
            args.sample = True
            args.auto_submit = True
            await run_apply(args)
        elif choice == "2":
            url_in = input("Enter target application URL: ").strip()
            if url_in:
                args.url = url_in
                auto_in = input("Auto-submit when filled? (y/n, default: n): ").strip().lower()
                args.auto_submit = auto_in in ("y", "yes", "true", "1")
                await run_apply(args)
        elif choice == "3":
            role_in = input("Enter role to search (default: Operations Lead): ").strip() or "Operations Lead"
            loc_in = input("Enter location (default: Remote): ").strip() or "Remote"
            args.query = role_in
            args.location = loc_in
            args.limit = 5
            args.batch = False
            args.test = False
            await run_search(args)
        elif choice == "4":
            portal_in = input("Enter portal name (default: LinkedIn): ").strip() or "LinkedIn"
            url_in = input("Enter login URL (default: https://www.linkedin.com/login): ").strip() or "https://www.linkedin.com/login"
            args.portal = portal_in
            args.url = url_in
            await run_login(args)
        else:
            print("Exiting.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Execution stopped by user.")
        sys.exit(0)
