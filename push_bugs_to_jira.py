"""
Push existing bugs from local JSON data to Jira — one issue per unique
(error_message + service_name) pair, across all 15 scenario files.

Usage:
    python push_bugs_to_jira.py
"""

import os
import sys
import json
import glob
import base64
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ── Jira config ─────────────────────────────────────────────
JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "KAN")

if not all([JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    print("ERROR: Missing Jira credentials in .env")
    sys.exit(1)

creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
HEADERS = {
    "Authorization": f"Basic {creds}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

SCENARIO_TITLES = {
    "null_pointer":       "Null Pointer Exceptions",
    "database_cascade":   "Database Cascade Failure",
    "auth_failures":      "Authentication Failures",
    "timeout_errors":     "Timeout Errors",
    "memory_issues":      "Memory Issues",
    "rate_limiting":      "Rate Limiting",
    "file_errors":        "File I/O Errors",
    "validation_errors":  "Validation Errors",
    "external_services":  "External Service Failures",
    "cache_issues":       "Cache Issues",
    "network_partition":  "Network Partition",
    "cpu_throttling":     "CPU Throttling",
    "disk_full":          "Disk Full",
    "ssl_cert_expired":   "SSL Certificate Expired",
    "deadlock":           "Deadlock",
}

SEVERITY_MAP = {
    "null_pointer": "High",       "database_cascade": "Critical",
    "auth_failures": "High",      "timeout_errors": "Medium",
    "memory_issues": "Critical",  "rate_limiting": "Medium",
    "file_errors": "Medium",      "validation_errors": "Low",
    "external_services": "High",  "cache_issues": "Medium",
    "network_partition": "Critical", "cpu_throttling": "High",
    "disk_full": "Critical",      "ssl_cert_expired": "High",
    "deadlock": "Critical",
}


# ── Discover issue type ─────────────────────────────────────
def get_issue_type_id():
    url = f"{JIRA_URL}/rest/api/3/issuetype"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    issue_types = resp.json()

    for preferred in ["Bug", "Task", "Story"]:
        for it in issue_types:
            if it.get("name", "").lower() == preferred.lower() and not it.get("subtask"):
                return it["id"], it["name"]

    for it in issue_types:
        if not it.get("subtask"):
            return it["id"], it["name"]

    print("ERROR: No valid issue type found")
    sys.exit(1)


# ── Collect unique bugs ─────────────────────────────────────
def collect_unique_bugs(data_dir):
    """
    Scan every scenario JSON and extract unique bugs keyed by
    (service_name, error_message). Returns a list of bug dicts.
    """
    scenario_files = sorted(glob.glob(os.path.join(data_dir, "scenario_*.json")))
    # key → accumulated info
    bugs = {}  # (service, error_msg) → dict

    for file_path in scenario_files:
        filename = os.path.basename(file_path)
        slug = filename.replace("scenario_", "").replace(".json", "")
        parts = slug.split("_", 1)
        scenario_num = parts[0]
        scenario_name = parts[1] if len(parts) > 1 else slug

        with open(file_path, "r") as f:
            logs = json.load(f)

        for log in logs:
            svc = log.get("service_name", "unknown")
            err = log.get("error_message", "Unknown error")
            key = (svc, err)

            if key not in bugs:
                bugs[key] = {
                    "service": svc,
                    "error_message": err,
                    "stack_trace": log.get("stack_trace", ""),
                    "environment": log.get("environment", "production"),
                    "scenario_name": scenario_name,
                    "scenario_num": scenario_num,
                    "scenario_title": SCENARIO_TITLES.get(scenario_name, scenario_name.replace("_", " ").title()),
                    "severity": SEVERITY_MAP.get(scenario_name, "Medium"),
                    "occurrences": 0,
                    "regions": set(),
                    "first_seen": log.get("timestamp", ""),
                    "last_seen": log.get("timestamp", ""),
                    "sample_metadata": log.get("metadata", {}),
                }

            bugs[key]["occurrences"] += 1
            meta = log.get("metadata", {})
            if "region" in meta:
                bugs[key]["regions"].add(meta["region"])
            ts = log.get("timestamp", "")
            if ts and ts > bugs[key]["last_seen"]:
                bugs[key]["last_seen"] = ts
            if ts and (not bugs[key]["first_seen"] or ts < bugs[key]["first_seen"]):
                bugs[key]["first_seen"] = ts
            if not bugs[key]["stack_trace"] and log.get("stack_trace"):
                bugs[key]["stack_trace"] = log["stack_trace"]

    return list(bugs.values())


# ── Create Jira issue ───────────────────────────────────────
def create_jira_issue(bug, issue_type_id):
    title = f"[{bug['service']}] {bug['error_message']}"
    if len(title) > 255:
        title = title[:252] + "..."

    desc_lines = [
        f"**Error:** {bug['error_message']}",
        f"**Service:** {bug['service']}",
        f"**Scenario:** {bug['scenario_title']}",
        f"**Severity:** {bug['severity']}",
        f"**Environment:** {bug['environment']}",
        f"**Occurrences:** {bug['occurrences']}",
        f"**Region(s):** {', '.join(sorted(bug['regions'])) if bug['regions'] else 'N/A'}",
        f"**First seen:** {bug['first_seen']}",
        f"**Last seen:** {bug['last_seen']}",
    ]

    if bug["stack_trace"]:
        desc_lines += ["", "**Stack trace:**", "```", bug["stack_trace"][:800], "```"]

    if bug["sample_metadata"]:
        desc_lines += ["", "**Sample metadata:**"]
        for k, v in bug["sample_metadata"].items():
            desc_lines.append(f"- {k}: {v}")

    # Build ADF
    adf_content = []
    for line in "\n".join(desc_lines).split("\n"):
        adf_content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": line}],
        })

    priority_map = {"Critical": "Highest", "High": "High", "Medium": "Medium", "Low": "Low"}
    jira_priority = priority_map.get(bug["severity"], "Medium")

    labels = [
        f"scenario-{bug['scenario_num']}",
        bug["scenario_name"],
        bug["service"].replace(" ", "-"),
        "auto-imported",
    ]

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": title,
            "description": {"version": 1, "type": "doc", "content": adf_content},
            "issuetype": {"id": issue_type_id},
            "labels": labels,
        }
    }

    try:
        payload["fields"]["priority"] = {"name": jira_priority}
    except Exception:
        pass

    url = f"{JIRA_URL}/rest/api/3/issue"
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=20)

    if not resp.ok:
        error_body = resp.text[:300]
        if "priority" in error_body.lower():
            payload["fields"].pop("priority", None)
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=20)

    resp.raise_for_status()
    return resp.json()


# ── Main ────────────────────────────────────────────────────
def main():
    print(f"🔗 Jira: {JIRA_URL}")
    print(f"📁 Project: {JIRA_PROJECT_KEY}")
    print()

    issue_type_id, issue_type_name = get_issue_type_id()
    print(f"📋 Issue type: {issue_type_name} (id={issue_type_id})")
    print()

    data_dir = os.path.join(os.path.dirname(__file__), "services", "bug_rca", "data")
    bugs = collect_unique_bugs(data_dir)

    print(f"Found {len(bugs)} unique bugs (service × error_message) across all scenarios\n")
    print("=" * 70)

    created = []
    failed = []

    for i, bug in enumerate(bugs, 1):
        print(f"\n[{i}/{len(bugs)}] {bug['service']} → {bug['error_message'][:60]}")
        print(f"         Scenario: {bug['scenario_title']} | Severity: {bug['severity']} | Hits: {bug['occurrences']}")

        try:
            result = create_jira_issue(bug, issue_type_id)
            key = result.get("key", "???")
            created.append(key)
            print(f"         ✅ {key}")
        except Exception as e:
            failed.append(bug["error_message"][:40])
            print(f"         ❌ {e}")

    print("\n" + "=" * 70)
    print(f"✅ Created: {len(created)} issues → {', '.join(created)}")
    if failed:
        print(f"❌ Failed:  {len(failed)} → {', '.join(failed)}")
    print(f"\n🌐 View: {JIRA_URL}/jira/software/projects/{JIRA_PROJECT_KEY}/board")


if __name__ == "__main__":
    main()
