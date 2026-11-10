import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    """
    Configuration settings for JOBAGENT.
    Values can be overridden using environment variables or CLI arguments.
    """
    # Ollama API settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    # Browser automation settings (Playwright)
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "false").lower() in ("true", "1", "yes")
    BROWSER_SLOW_MO: int = int(os.getenv("BROWSER_SLOW_MO", "100"))  # Milliseconds delay per action for visibility
    PAGE_TIMEOUT: int = int(os.getenv("PAGE_TIMEOUT", "30000"))      # Timeout in milliseconds (30s)

    # Persistent browser profile (preserves login sessions, cookies, avoids bot checkpoints)
    USER_DATA_DIR: str = os.getenv("USER_DATA_DIR", os.path.abspath("browser_profile"))

    # Autonomous submission toggle (if True, automatically clicks Submit application)
    AUTO_SUBMIT: bool = os.getenv("AUTO_SUBMIT", "false").lower() in ("true", "1", "yes")

    # Job discovery / search settings
    SEARCH_KEYWORDS: List[str] = field(default_factory=lambda: [
        "AI Workflow Specialist",
        "Operations Lead",
        "Product Manager",
        "Program Manager"
    ])
    DEFAULT_LOCATION: str = os.getenv("DEFAULT_LOCATION", "Remote")

    # Candidate profile
    PROFILE_PATH: str = os.getenv("PROFILE_PATH", "profile.json")

# Default global configuration instance
config = Config()
