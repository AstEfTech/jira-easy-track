# Jira Easy Track

A dead-simple Jira time tracker: one Python file, zero dependencies, **no activity monitoring**.

No background agent, no screenshots, no window or keystroke tracking, no timers running all day. You tell it how many hours you spent on each task, and it spreads them across your working days and logs them to Jira, when you decide.

## How it works

1. **Connect**: enter your Jira Cloud URL, email and [API token](https://id.atlassian.com/manage-profile/security/api-tokens).
2. **Tasks**: load your issues (default: assigned to you; the JQL is editable) and pick the fields to display (Key and Summary by default). For each task set:
   - **Total** hours, spread over the whole period, and/or
   - **Per day** hours, logged on every working day (e.g. a daily 1h meeting).
   - **Timing**: even, towards the start / middle / end of the period, or random.
   - **Pin** a task to always keep it in the list.
3. **Schedule**: choose the period, working day start/end, an optional break, working weekdays and days off. Optionally enable a realistic spread so different days get different hours.
   - **Task tracking window**: a task is tracked only between its first move into status 1 (default `In Progress`) and its first move into status 2 (default `Done`), inside the selected period. Both statuses are picked from your Jira's status list. When tasks are loaded, their status history is read and **Range** is preset: Task window if the task has such a transition, Whole period otherwise. You can change it per task on the Tasks tab.
4. **Preview**: review the generated per-day distribution, remove entries you don't want, then approve to push the worklogs to Jira. A Stop button interrupts sending at any time.
5. **Clear**: find and delete your own worklogs for a period (with a Stop button as well).

## Quick start

Requires Python 3.8+.

```
python jira-track.py
```

The browser opens at `http://127.0.0.1:4777`. Press `Ctrl+C` in the terminal to quit.

## Config file (optional)

The **Save to config file** button stores the connection, JQL, displayed fields, pinned tasks and working day settings in `jira-track.config.json` next to the script. It is loaded on every start and kept up to date automatically. Set `JIRA_TRACK_CONFIG` to use a different path.

The token is stored in plain text, so the config file is excluded via `.gitignore`. Do not commit or share it.

## Notes

- A tiny local server (bound to `127.0.0.1` only) serves the UI and proxies requests to Jira, because Jira Cloud blocks direct browser calls (CORS). Nothing is sent anywhere except your Jira site.
- Jira Cloud only (REST API v3). Worklogs are created without changing the issue's remaining estimate.
- Times use your browser's time zone.
