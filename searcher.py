import argparse
import asyncio
import json
import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Page, BrowserContext
from config import Config, config as default_config
from session_manager import SessionManager

logger = logging.getLogger("JOBAGENT.Searcher")

class JobSearcher:
    """
    Asynchronous job discovery engine powered by Playwright and persistent sessions.
    Searches job portals for target roles (AI Workflow Specialist, Operations Lead, Product Manager)
    and extracts structured job postings for automated application.
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.config = cfg or default_config
        self.session_manager = SessionManager(self.config)
        self.profile = self._load_profile(self.config.PROFILE_PATH)

    def _load_profile(self, path: str) -> Dict[str, Any]:
        """Loads profile data to read default target roles and regions."""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        limit: int = 5,
        test_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Executes a live search for the given query and location.
        Falls back to structured mock results if running in test_mode or if network is unavailable.
        """
        if test_mode:
            logger.info(f"Running mock discovery for query='{query}', location='{location}'")
            return self._generate_mock_jobs(query, location, limit)

        logger.info(f"Searching for roles: query='{query}', location='{location}' (limit={limit})")
        encoded_query = urllib.parse.quote(query)
        encoded_loc = urllib.parse.quote(location)
        search_url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_query}&location={encoded_loc}"

        jobs: List[Dict[str, Any]] = []

        async with async_playwright() as p:
            context: BrowserContext = await self.session_manager.launch_persistent_context(
                p,
                headless=self.config.BROWSER_HEADLESS,
                slow_mo=self.config.BROWSER_SLOW_MO
            )
            page: Page = context.pages[0] if context.pages else await context.new_page()

            try:
                logger.info(f"Navigating to job portal: {search_url}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.PAGE_TIMEOUT)
                await page.wait_for_timeout(2000)

                # Scroll down slightly to trigger lazy-loaded cards
                await page.evaluate("window.scrollBy(0, 800);")
                await page.wait_for_timeout(1000)

                # Extract job listing elements
                raw_cards = await page.evaluate("""
                () => {
                    const cards = Array.from(document.querySelectorAll('.base-card, .job-search-card, [data-entity-urn*="jobPosting"]'));
                    return cards.slice(0, 15).map(card => {
                        const titleEl = card.querySelector('.base-search-card__title, .job-card-list__title, h3, h4');
                        const companyEl = card.querySelector('.base-search-card__subtitle, .job-card-container__company-name, .job-search-card__subtitle');
                        const locationEl = card.querySelector('.job-search-card__location, .job-card-container__metadata-item');
                        const linkEl = card.querySelector('a.base-card__full-link, a[href*="/jobs/view/"], a');

                        return {
                            title: titleEl ? titleEl.innerText.trim() : '',
                            company: companyEl ? companyEl.innerText.trim() : '',
                            location: locationEl ? locationEl.innerText.trim() : '',
                            url: linkEl ? linkEl.href : ''
                        };
                    }).filter(item => item.title && item.url);
                }
                """)

                for card in raw_cards:
                    if len(jobs) >= limit:
                        break
                    jobs.append({
                        "title": card["title"],
                        "company": card["company"] or "Company Not Disclosed",
                        "location": card["location"] or location,
                        "url": card["url"],
                        "query": query
                    })

                logger.info(f"Extracted {len(jobs)} live job postings for '{query}'.")

            except Exception as e:
                logger.warning(f"Live portal search encountered an issue ({e}). Returning fallback search results.")
                jobs = self._generate_mock_jobs(query, location, limit)
            finally:
                await context.close()

        if not jobs:
            logger.info("No live jobs extracted; using fallback search results for offline demonstration.")
            jobs = self._generate_mock_jobs(query, location, limit)

        return jobs

    def _generate_mock_jobs(self, query: str, location: str, limit: int) -> List[Dict[str, Any]]:
        """Generates realistic mock job postings tailored to Huzefa's background."""
        mock_templates = [
            {
                "title": f"Senior {query}",
                "company": "Apex Mobility & Tech",
                "location": location,
                "url": "https://careers.apextech.example/jobs/operations-lead-101",
                "description": "Leading cross-functional operations, automation pipelines, and scaling tech execution."
            },
            {
                "title": f"Lead {query} - Logistics & Platforms",
                "company": "HyperRail Global",
                "location": location,
                "url": "https://careers.hyperrail.example/apply/402",
                "description": "Seeking an operations and tech leader with experience scaling regional distribution and partner networks."
            },
            {
                "title": f"{query} - Automated Systems",
                "company": "NextGen Workflows",
                "location": "Remote",
                "url": "https://nextgen.example/jobs/ai-ops-55",
                "description": "Drive end-to-end automation, Python/Playwright agent integration, and operations excellence."
            }
        ]
        return mock_templates[:limit]

    async def batch_search(
        self,
        queries: Optional[List[str]] = None,
        location: str = "Remote",
        limit_per_query: int = 3,
        save_file: str = "discovered_jobs.json",
        test_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Searches across all target roles and exports the findings to a JSON file.
        """
        search_terms = queries or self.profile.get("target_roles") or self.config.SEARCH_KEYWORDS
        all_jobs: List[Dict[str, Any]] = []

        print("\n" + "=" * 65)
        print("   JOB SEARCHER: Batch Discovery Mode")
        print(f"   Target Roles: {', '.join(search_terms)}")
        print(f"   Location: {location}")
        print("=" * 65 + "\n")

        for q in search_terms:
            logger.info(f"--- Searching query: {q} ---")
            results = await self.search_jobs(query=q, location=location, limit=limit_per_query, test_mode=test_mode)
            all_jobs.extend(results)

        # Save to disk
        with open(save_file, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=2)

        logger.info(f"Saved total of {len(all_jobs)} discovered jobs to '{save_file}'")
        return all_jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="JOBAGENT Job Discovery Module")
    parser.add_argument("--query", type=str, default="Operations Lead", help="Job title to search for")
    parser.add_argument("--location", type=str, default="Remote", help="Job location / region")
    parser.add_argument("--limit", type=int, default=5, help="Max jobs to return")
    parser.add_argument("--batch", action="store_true", help="Run batch search for all profile target roles")
    parser.add_argument("--test", action="store_true", help="Run in mock/test mode without external portal calls")
    args = parser.parse_args()

    searcher = JobSearcher()
    if args.batch:
        asyncio.run(searcher.batch_search(location=args.location, test_mode=args.test))
    else:
        results = asyncio.run(searcher.search_jobs(query=args.query, location=args.location, limit=args.limit, test_mode=args.test))
        print(json.dumps(results, indent=2))
