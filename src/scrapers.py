"""Scrape freelance job listings from multiple platforms."""
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    title: str
    description: str
    budget_min: float
    budget_max: float
    budget_type: str  # "hourly" | "fixed"
    platform: str
    url: str
    posted_at: str
    skills: list[str] = field(default_factory=list)
    client_country: str = ""
    client_rating: float = 0.0
    proposals_count: int = 0

    @property
    def budget_display(self) -> str:
        if self.budget_type == "hourly":
            return f"${self.budget_min:.0f}-${self.budget_max:.0f}/hr"
        return f"${self.budget_min:.0f}-${self.budget_max:.0f}"

    @property
    def score(self) -> float:
        """Heuristic score: higher = better opportunity."""
        s = 0.0
        if self.budget_min > 500:
            s += 0.3
        elif self.budget_min > 200:
            s += 0.15
        if self.proposals_count < 5:
            s += 0.25
        elif self.proposals_count < 15:
            s += 0.1
        if self.client_rating > 4.5:
            s += 0.2
        if self.budget_type == "fixed":
            s += 0.1
        return min(1.0, s)


class JobScraper:
    """Scrape jobs from multiple freelancing platforms."""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }

    @staticmethod
    def _make_id(platform: str, url: str) -> str:
        return hashlib.md5(f"{platform}:{url}".encode()).hexdigest()[:12]

    def fetch_upwork_rss(self, keywords: list[str]) -> list[Job]:
        """Fetch jobs from Upwork RSS feeds."""
        jobs = []
        for kw in keywords:
            url = f"https://www.upwork.com/ab/feed/topics/rss?q={kw}&sort=recency"
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    desc = entry.get("description", "")
                    link = entry.get("link", "")

                    budget_min, budget_max, budget_type = self._parse_upwork_budget(desc)
                    country = self._extract_country(desc)

                    jobs.append(Job(
                        id=self._make_id("upwork", link),
                        title=title,
                        description=desc[:500],
                        budget_min=budget_min,
                        budget_max=budget_max,
                        budget_type=budget_type,
                        platform="upwork",
                        url=link,
                        posted_at=entry.get("published", ""),
                        skills=[kw],
                        client_country=country,
                    ))
            except Exception as e:
                logger.warning(f"Upwork RSS error for '{kw}': {e}")
        return jobs

    def fetch_freelancer_rss(self, keywords: list[str]) -> list[Job]:
        """Fetch jobs from Freelancer.com public RSS."""
        jobs = []
        for kw in keywords:
            url = f"https://www.freelancer.com/rss.xml?q={kw}"
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:15]:
                    title = entry.get("title", "")
                    desc = entry.get("description", "")
                    link = entry.get("link", "")

                    budget_min, budget_max = self._parse_freelancer_budget(desc)

                    jobs.append(Job(
                        id=self._make_id("freelancer", link),
                        title=title,
                        description=desc[:500],
                        budget_min=budget_min,
                        budget_max=budget_max,
                        budget_type="fixed",
                        platform="freelancer",
                        url=link,
                        posted_at=entry.get("published", ""),
                        skills=[kw],
                    ))
            except Exception as e:
                logger.warning(f"Freelancer RSS error for '{kw}': {e}")
        return jobs

    def fetch_upwork_search(self, keywords: list[str], min_budget: int = 100) -> list[Job]:
        """Scrape Upwork search results page."""
        jobs = []
        for kw in keywords:
            try:
                params = {
                    "q": kw,
                    "sort": "recency",
                }
                url = f"https://www.upwork.com/nx/search/jobs/?{urlencode(params)}"
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select('[data-test="job-tile-list"] > div, .job-tile')

                for card in cards[:15]:
                    title_el = card.select_one("h2 a, .job-tile-title a")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    link = "https://www.upwork.com" + title_el.get("href", "")

                    desc_el = card.select_one(".description, .job-description-text")
                    desc = desc_el.get_text(strip=True) if desc_el else ""

                    budget = self._parse_upwork_tile_budget(card)

                    jobs.append(Job(
                        id=self._make_id("upwork", link),
                        title=title,
                        description=desc[:500],
                        budget_min=budget.get("min", 0),
                        budget_max=budget.get("max", 0),
                        budget_type=budget.get("type", "hourly"),
                        platform="upwork",
                        url=link,
                        posted_at=datetime.now().isoformat(),
                        skills=[kw],
                    ))
            except Exception as e:
                logger.warning(f"Upwork search error for '{kw}': {e}")
        return jobs

    def _parse_upwork_budget(self, description: str) -> tuple[float, float, str]:
        """Parse Upwork budget from RSS description."""
        import re
        hourly = re.search(r'Hourly Range.*?\$(\d+[\.\d]*)\s*-\s*\$(\d+[\.\d]*)', description)
        if hourly:
            return float(hourly.group(1)), float(hourly.group(2)), "hourly"
        fixed = re.search(r'Budget.*?\$(\d+[\.\d]*)\s*-\s*\$(\d+[\.\d]*)', description)
        if fixed:
            return float(fixed.group(1)), float(fixed.group(2)), "fixed"
        return 0, 0, "hourly"

    def _parse_freelancer_budget(self, description: str) -> tuple[float, float]:
        import re
        budget = re.search(r'Budget.*?\$(\d+[\.\d]*)\s*-\s*\$(\d+[\.\d]*)', description)
        if budget:
            return float(budget.group(1)), float(budget.group(2))
        return 0, 0

    def _extract_country(self, description: str) -> str:
        import re
        m = re.search(r'Country:\s*(\w+(?:\s+\w+)*)', description)
        return m.group(1) if m else ""

    def _parse_upwork_tile_budget(self, card) -> dict:
        text = card.get_text()
        import re
        hourly = re.search(r'\$(\d+[\.\d]*)\s*-\s*\$(\d+[\.\d]*)\s*/hr', text)
        if hourly:
            return {"min": float(hourly.group(1)), "max": float(hourly.group(2)), "type": "hourly"}
        fixed = re.search(r'\$(\d+[\.\d]*)\s*-\s*\$(\d+[\.\d]*)', text)
        if fixed and not re.search(r'/hr', text):
            return {"min": float(fixed.group(1)), "max": float(fixed.group(2)), "type": "fixed"}
        return {"min": 0, "max": 0, "type": "hourly"}

    def fetch_all(self, keywords: list[str]) -> list[Job]:
        jobs = []
        jobs.extend(self.fetch_upwork_rss(keywords))
        jobs.extend(self.fetch_freelancer_rss(keywords))
        # Deduplicate by URL
        seen = set()
        unique = []
        for j in jobs:
            if j.url not in seen:
                seen.add(j.url)
                unique.append(j)
        unique.sort(key=lambda j: j.score, reverse=True)
        return unique
