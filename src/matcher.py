"""AI-powered job matching and proposal generation.

Uses heuristic scoring to rank jobs and generate tailored proposals.
"""
import re
from dataclasses import dataclass
from typing import Optional

from jinja2 import Template


PROPOSAL_TEMPLATES = {
    "python": Template("""\
Subject: {{ subject }}

Hi there,

I read your job post about "{{ job.title }}" and I'm confident I can deliver exactly what you need.

My background:
- {{ experience_years }}+ years of Python development experience
- Built {{ relevant_projects }} similar projects
- Strong expertise in {{ matching_skills }}

For your specific needs, I would:
1. Start by understanding your {{ specific_need }}
2. Deliver a working prototype within {{ delivery_days }} days
3. Provide clean, well-documented code with tests

My rate is {{ rate }}/hr and I'm available to start immediately.

Here's a similar project I've done: {{ portfolio_example }}

Would you like to schedule a quick call to discuss your project in detail?

Best regards,
{{ name }}
"""),

    "web": Template("""\
Subject: {{ subject }}

Hi,

I saw your posting for "{{ job.title }}" and I'd love to help.

I'm a full-stack developer with {{ experience_years }}+ years building modern web applications. I've worked on {{ relevant_projects }} and can bring that experience to your project.

What I'll deliver:
- Responsive, pixel-perfect UI/UX
- Fast, secure backend ({{ matching_skills }})
- Thorough testing and documentation
- Post-launch support

Timeline: {{ delivery_days }} days for initial version
Rate: {{ rate }}/hr

Portfolio: {{ portfolio_example }}

Let me know if you'd like to chat more about your project!

Best,
{{ name }}
"""),

    "default": Template("""\
Subject: {{ subject }}

Hello,

I'm writing about your project "{{ job.title }}". I have strong experience in {{ matching_skills }} and have completed {{ relevant_projects }}.

I can deliver your project in {{ delivery_days }} days at {{ rate }}/hr. My approach focuses on understanding your exact needs first, then delivering high-quality results.

Portfolio: {{ portfolio_example }}

I'm available to start right away. Let me know a good time to discuss!

Best,
{{ name }}
"""),
}


@dataclass
class MatcherConfig:
    skills: list[str]
    experience_years: int
    rate: float  # per hour
    delivery_days: int
    portfolio_example: str
    min_budget: float
    min_hourly_rate: float
    name: str = "Developer"


class JobMatcher:
    """Match jobs to skills and generate proposals."""

    def __init__(self, config: MatcherConfig):
        self.config = config

    def score(self, job) -> float:
        """Score a job (0-1) based on keyword match and budget."""
        score = job.score  # base score from platform metrics
        text = (job.title + " " + job.description).lower()

        # Skill match
        matched = 0
        for skill in self.config.skills:
            if skill.lower() in text:
                matched += 1
        if matched > 0:
            score += 0.15 * min(matched, 3)

        # Budget filter
        if job.budget_type == "hourly" and job.budget_min < self.config.min_hourly_rate:
            score -= 0.5
        elif job.budget_type == "fixed" and job.budget_min < self.config.min_budget:
            score -= 0.5

        return min(1.0, max(0, score))

    def filter(self, jobs: list, min_score: float = 0.3) -> list:
        """Filter and rank jobs by match score."""
        scored = [(self.score(j), j) for j in jobs]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [j for s, j in scored if s >= min_score]

    def match_category(self, job) -> str:
        """Determine which template category fits best."""
        text = (job.title + " " + job.description).lower()
        if any(w in text for w in ["python", "django", "flask", "fastapi", "data", "ml", "ai"]):
            return "python"
        if any(w in text for w in ["web", "react", "vue", "angular", "html", "css", "frontend", "javascript", "typescript"]):
            return "web"
        return "default"

    def extract_skills(self, job) -> list[str]:
        """Extract relevant skills from job description."""
        text = (job.title + " " + job.description).lower()
        found = []
        for skill in self.config.skills:
            if skill.lower() in text:
                found.append(skill)
        return found if found else self.config.skills[:3]

    def extract_specific_need(self, job) -> str:
        """Try to identify the specific need from job description."""
        text = job.description.lower()
        patterns = [
            (r'(?:need|want|looking for|require).*?([A-Za-z\s]{10,40})[\.\n]', "needs"),
            (r'project.*?about\s+([A-Za-z\s]{10,40})[\.\n]', "project about"),
        ]
        for pattern, _ in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return "requirements and goals"

    def generate_proposal(self, job, template_name: str | None = None) -> str:
        """Generate a tailored proposal for the job."""
        if template_name is None:
            template_name = self.match_category(job)
        tpl = PROPOSAL_TEMPLATES.get(template_name, PROPOSAL_TEMPLATES["default"])

        matching_skills = self.extract_skills(job)
        subject = f"Re: {job.title[:60]}"

        return tpl.render(
            subject=subject,
            job=job,
            matching_skills=", ".join(matching_skills[:5]),
            experience_years=self.config.experience_years,
            relevant_projects=self._estimate_projects(matching_skills),
            delivery_days=self.config.delivery_days,
            rate=self.config.rate,
            portfolio_example=self.config.portfolio_example,
            name=self.config.name,
            specific_need=self.extract_specific_need(job),
        )

    def _estimate_projects(self, skills: list[str]) -> str:
        n = len(skills)
        if n >= 5:
            return "15+"
        elif n >= 3:
            return "8-10"
        return "several"
