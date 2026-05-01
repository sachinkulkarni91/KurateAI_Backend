"""
Jira integration client for Bug RCA Service.
Fetches bug/issue data from Jira Cloud REST API v3.
"""

import os
import logging
import base64
from typing import Optional, List, Dict, Any
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class JiraClient:
    """Lightweight Jira Cloud REST API client."""

    def __init__(
        self,
        url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        project_key: Optional[str] = None,
    ):
        self.base_url = (url or os.getenv("JIRA_URL", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL", "")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN", "")
        self.project_key = project_key or os.getenv("JIRA_PROJECT_KEY", "KAN")

        if not all([self.base_url, self.email, self.api_token]):
            raise RuntimeError(
                "Jira credentials missing. Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"
            )

        # Basic auth header: base64(email:api_token)
        creds = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ── Core API calls ───────────────────────────────────────
    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}/rest/api/3{path}"
        resp = requests.get(url, headers=self.headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_body: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}/rest/api/3{path}"
        resp = requests.post(url, headers=self.headers, json=json_body or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── Fetch bugs ───────────────────────────────────────────
    def get_bugs(
        self,
        status: Optional[str] = None,
        max_results: int = 50,
        issue_type: str = "Bug",
    ) -> List[Dict[str, Any]]:
        """
        Fetch bugs from Jira using JQL via POST /search/jql
        (the old GET /search was deprecated — returns 410 Gone).
        """
        # Build JQL
        jql_parts = [f'project = "{self.project_key}"']

        if issue_type:
            jql_parts.append(f'issuetype = "{issue_type}"')

        if status:
            jql_parts.append(f'status = "{status}"')

        jql_parts.append("ORDER BY created DESC")
        jql = " AND ".join(jql_parts[:-1]) + " " + jql_parts[-1]

        logger.info(f"Jira JQL: {jql}")

        try:
            data = self._post("/search/jql", json_body={
                "jql": jql,
                "maxResults": max_results,
                "fields": [
                    "summary", "description", "status", "priority",
                    "assignee", "reporter", "created", "updated",
                    "issuetype", "labels", "components", "resolution",
                ],
            })
        except requests.exceptions.HTTPError as e:
            # If issue type 'Bug' doesn't exist, retry without type filter
            if e.response is not None and e.response.status_code == 400 and issue_type:
                logger.warning(f"Issue type '{issue_type}' not found, fetching all issues")
                return self.get_bugs(status=status, max_results=max_results, issue_type=None)
            raise

        issues = data.get("issues", [])
        return [self._normalize(issue) for issue in issues]

    # ── Get single issue ─────────────────────────────────────
    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Fetch a single Jira issue by key."""
        data = self._get(f"/issue/{issue_key}")
        return self._normalize(data)

    # ── Get all statuses for the project ─────────────────────
    def get_statuses(self) -> List[str]:
        """Return the list of available statuses for the project."""
        try:
            data = self._get(f"/project/{self.project_key}/statuses")
            statuses = set()
            for issue_type in data:
                for s in issue_type.get("statuses", []):
                    statuses.add(s["name"])
            return sorted(statuses)
        except Exception as e:
            logger.warning(f"Could not fetch statuses: {e}")
            return ["To Do", "In Progress", "Done"]

    # ── Normalize Jira response → simple dict ────────────────
    @staticmethod
    def _normalize(issue: Dict) -> Dict[str, Any]:
        fields = issue.get("fields", {})

        # Extract plain-text description from Atlassian Document Format
        description = ""
        desc_field = fields.get("description")
        if desc_field and isinstance(desc_field, dict):
            # ADF → plain text extraction
            for block in desc_field.get("content", []):
                for inline in block.get("content", []):
                    if inline.get("type") == "text":
                        description += inline.get("text", "")
                description += "\n"
        elif isinstance(desc_field, str):
            description = desc_field

        assignee = fields.get("assignee")
        reporter = fields.get("reporter")
        priority = fields.get("priority")
        resolution = fields.get("resolution")
        components = fields.get("components", [])

        return {
            "key": issue.get("key", ""),
            "id": issue.get("id", ""),
            "summary": fields.get("summary", ""),
            "description": description.strip(),
            "status": fields.get("status", {}).get("name", "Unknown"),
            "priority": priority.get("name", "Medium") if priority else "Medium",
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "assignee": assignee.get("displayName", "Unassigned") if assignee else "Unassigned",
            "reporter": reporter.get("displayName", "Unknown") if reporter else "Unknown",
            "labels": fields.get("labels", []),
            "components": [c.get("name", "") for c in components],
            "resolution": resolution.get("name") if resolution else None,
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "url": f"{issue.get('self', '').split('/rest/')[0]}/browse/{issue.get('key', '')}",
        }


def get_jira_client() -> JiraClient:
    """Factory — returns a configured JiraClient or raises RuntimeError."""
    return JiraClient()
