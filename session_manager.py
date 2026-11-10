import asyncio
import logging
import os
import sys
from typing import Optional
from playwright.async_api import Playwright, BrowserContext, async_playwright
from config import Config, config as default_config

logger = logging.getLogger("JOBAGENT.Session")

class SessionManager:
    """
    Manages persistent browser user contexts in Playwright.
    Saves and reuses session state, cookies, and local storage in a local
    'browser_profile' folder to avoid repeated logins and bot checkpoints.
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.config = cfg or default_config
        self.user_data_dir = os.path.abspath(self.config.USER_DATA_DIR)
        os.makedirs(self.user_data_dir, exist_ok=True)
        logger.info(f"SessionManager initialized with profile directory: {self.user_data_dir}")

    async def launch_persistent_context(
        self,
        playwright: Playwright,
        headless: Optional[bool] = None,
        slow_mo: Optional[int] = None
    ) -> BrowserContext:
        """
        Launches a Chromium persistent browser context with realistic browser attributes
        and anti-bot detection avoidance settings.
        """
        is_headless = headless if headless is not None else self.config.BROWSER_HEADLESS
        action_delay = slow_mo if slow_mo is not None else self.config.BROWSER_SLOW_MO

        logger.info(f"Launching persistent browser context (headless={is_headless}, dir={self.user_data_dir})")

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=is_headless,
            slow_mo=action_delay,
            viewport={"width": 1280, "height": 850},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars"
            ],
            ignore_default_args=["--enable-automation"]
        )

        # Mask navigator.webdriver flag in new pages
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        return context

    async def interactive_login(self, portal_name: str, portal_url: str):
        """
        Opens a visible browser session pointing to the specified login page.
        Allows the user to log in manually; session cookies and tokens are automatically
        persisted to 'browser_profile/' for all future automated runs.
        """
        print("\n" + "=" * 65)
        print(f"[*] Starting Persistent Session Login for: {portal_name}")
        print(f"[*] Target URL: {portal_url}")
        print(f"[*] Profile Directory: {self.user_data_dir}")
        print("=" * 65)

        async with async_playwright() as p:
            # Force headless=False for manual user interaction
            context = await self.launch_persistent_context(p, headless=False, slow_mo=50)
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                logger.info(f"Navigating to login page: {portal_url}")
                await page.goto(portal_url, wait_until="domcontentloaded")

                print("\n>>> BROWSER WINDOW OPENED.")
                print(f">>> Please log in to your {portal_name} account in the opened browser window.")
                print(">>> Complete any 2FA or verification if prompted.")
                print(">>> Once logged in, return to this terminal and press [ENTER] to save session...\n")

                await asyncio.to_thread(input)

                # Wait briefly to ensure session cookies are synced to disk
                await page.wait_for_timeout(2000)
                logger.info(f"Session cookies for {portal_name} successfully saved to {self.user_data_dir}")
                print(f"[+] Login session saved successfully in '{self.user_data_dir}'!\n")

            except Exception as e:
                logger.error(f"Error during interactive login: {e}")
            finally:
                await context.close()

    async def test_context(self) -> bool:
        """Verifies that the persistent context can be booted and closed cleanly."""
        async with async_playwright() as p:
            ctx = await self.launch_persistent_context(p, headless=True)
            page = await ctx.new_page()
            await page.goto("about:blank")
            await ctx.close()
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = SessionManager()
    portal = sys.argv[1] if len(sys.argv) > 1 else "LinkedIn"
    url = sys.argv[2] if len(sys.argv) > 2 else "https://www.linkedin.com/login"
    asyncio.run(manager.interactive_login(portal, url))
