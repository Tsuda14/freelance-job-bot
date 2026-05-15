"""Freelance job automation — main orchestrator."""
import json
import logging
import os
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .matcher import JobMatcher, MatcherConfig
from .scrapers import Job, JobScraper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("freelance.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class FreelanceBot:
    """Automated freelance job hunting bot."""

    def __init__(self):
        self.scraper = JobScraper()
        self.matcher = JobMatcher(self._load_config())
        self.seen_ids: set[str] = set()
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self._load_seen()

    def _load_config(self) -> MatcherConfig:
        return MatcherConfig(
            skills=self._parse_list(os.getenv("YOUR_SKILLS", "python,javascript,react,api,automation")),
            experience_years=int(os.getenv("YOUR_EXPERIENCE_YEARS", "5")),
            rate=float(os.getenv("YOUR_RATE", "50")),
            delivery_days=int(os.getenv("YOUR_DELIVERY_DAYS", "7")),
            portfolio_example=os.getenv("YOUR_PORTFOLIO", "https://github.com/yourname"),
            min_budget=float(os.getenv("MIN_PROJECT_BUDGET", "200")),
            min_hourly_rate=float(os.getenv("MIN_HOURLY_RATE", "30")),
            name=os.getenv("YOUR_NAME", "Developer"),
        )

    @staticmethod
    def _parse_list(s: str) -> list[str]:
        return [item.strip() for item in s.split(",") if item.strip()]

    def _load_seen(self):
        path = self.data_dir / "seen_jobs.json"
        if path.exists():
            self.seen_ids = set(json.loads(path.read_text()))

    def _save_seen(self):
        path = self.data_dir / "seen_jobs.json"
        path.write_text(json.dumps(list(self.seen_ids)))

    def scan(self) -> list[Job]:
        keywords = self._parse_list(os.getenv("JOB_KEYWORDS",
            "python developer,api integration,web scraping,automation,backend developer,full stack developer"
        ))
        logger.info(f"Scanning for jobs with keywords: {keywords}")
        jobs = self.scraper.fetch_all(keywords)
        new_jobs = [j for j in jobs if j.id not in self.seen_ids]
        for j in new_jobs:
            self.seen_ids.add(j.id)
        self._save_seen()

        matched = self.matcher.filter(new_jobs)
        logger.info(f"Found {len(new_jobs)} new jobs, {len(matched)} matched")
        return matched

    def generate_proposals(self, jobs: list[Job]) -> list[dict]:
        proposals = []
        for job in jobs:
            proposal_text = self.matcher.generate_proposal(job)
            proposals.append({
                "job": job,
                "proposal": proposal_text,
                "score": self.matcher.score(job),
                "platform": job.platform,
                "url": job.url,
            })
        proposals.sort(key=lambda p: p["score"], reverse=True)
        return proposals

    def send_email_report(self, proposals: list[dict],
                          to_email: str | None = None) -> bool:
        if not to_email:
            to_email = os.getenv("REPORT_EMAIL")
        if not to_email:
            logger.info("No report email configured, skipping email.")
            return False

        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")

        if not smtp_user or not smtp_pass:
            logger.warning("SMTP not configured. Set SMTP_USER and SMTP_PASS in .env")
            return False

        html = self._build_report_html(proposals)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🤑 New Freelance Jobs — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info(f"Report sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _build_report_html(self, proposals: list[dict]) -> str:
        rows = ""
        for p in proposals[:10]:
            j = p["job"]
            rows += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #ddd">
                    <strong>{j.title[:80]}</strong><br>
                    <small>{j.budget_display} | {j.platform} | Score: {p['score']:.2f}</small>
                </td>
                <td style="padding:8px;border-bottom:1px solid #ddd">
                    <a href="{j.url}" target="_blank">View</a>
                </td>
            </tr>
            <tr>
                <td colspan="2" style="padding:8px;border-bottom:2px solid #ccc">
                    <pre style="white-space:pre-wrap;font-family:monospace;font-size:0.85em;max-height:200px;overflow-y:auto">{p['proposal'][:500]}</pre>
                </td>
            </tr>
            """
        return f"""
        <html><body style="font-family:sans-serif;max-width:800px;margin:0 auto">
        <h2>🔥 Top Freelance Opportunities</h2>
        <p>{len(proposals)} jobs matched. Top {min(10, len(proposals))} shown.</p>
        <table style="width:100%;border-collapse:collapse">{rows}</table>
        <p style="margin-top:20px;color:#666">
            Generated by Freelance Bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>
        </body></html>
        """

    def save_proposals(self, proposals: list[dict]):
        path = self.data_dir / f"proposals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(proposals, indent=2, default=str, ensure_ascii=False))
        logger.info(f"Saved {len(proposals)} proposals to {path}")

    def run_once(self) -> list[dict]:
        logger.info("=" * 50)
        logger.info("Starting job scan cycle")
        jobs = self.scan()
        proposals = self.generate_proposals(jobs)

        if proposals:
            for p in proposals[:5]:
                j = p["job"]
                logger.info(f"  ★ {j.title[:60]} — {j.budget_display} — Score: {p['score']:.2f}")
            self.save_proposals(proposals)
            self.send_email_report(proposals)
        else:
            logger.info("No matching jobs found this cycle.")

        return proposals

    def run_loop(self, interval_minutes: int = 30):
        logger.info(f"Starting freelance bot loop (interval: {interval_minutes}min)")
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
            logger.info(f"Waiting {interval_minutes} minutes...")
            time.sleep(interval_minutes * 60)


def main():
    import sys
    parser = __import__("argparse").ArgumentParser(description="Freelance Job Bot")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Minutes between scans")
    parser.add_argument("--output", type=str, help="Write results to file")
    args = parser.parse_args()

    bot = FreelanceBot()

    if args.once:
        proposals = bot.run_once()
        if proposals:
            print(f"\n=== Top 5 Matched Jobs ===\n")
            for i, p in enumerate(proposals[:5], 1):
                j = p["job"]
                print(f"{i}. {j.title}")
                print(f"   Budget: {j.budget_display} | Platform: {j.platform}")
                print(f"   Score: {p['score']:.2f} | {j.url}")
                print()
        if args.output:
            Path(args.output).write_text(json.dumps(proposals, indent=2, default=str))
    else:
        print(f"Starting continuous mode (interval: {args.interval}min)")
        bot.run_loop(args.interval)


if __name__ == "__main__":
    main()
