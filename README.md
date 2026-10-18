# Jira Easy Track

Tired of tracking your jira time, splitting the task time between days manually?
Here is a dead-simple Jira time tracker: one Python file, zero dependencies, **no activity monitoring**.

No background agent, no screenshots, no window or keystroke tracking, no timers running all day.
You tell it how many hours you spent on each task, and it spreads them across your working days and logs them to Jira, when you decide.

![me](media/Jira_Easy_Track.gif)

## How it works

1. **Setup**: enter your Jira Cloud URL, email and [API token](https://id.atlassian.com/manage-profile/security/api-tokens) and press **Test and save**. Here you also set the working day (start/end, an optional break, step of 5-60 minutes) and the working weekdays, and can save everything to a config file.
2. **Tasks**:
   - **Period**: dates "From" and "To", plus optional days off / holidays and extra working days (`YYYY-MM-DD`, comma-separated).
   - **Task source**: an editable JQL (default: assigned to you), the fields to display (Key and Summary by default) and adding a task by key. Press **Load tasks** to fetch them.
   - For each task set:
     - **Total** hours, spread over the working days of the period (if left empty, the task's original estimate from Jira is used; type `0` to track nothing), and/or
     - **Per day** hours, logged on every working day (e.g. a daily 1h meeting).
     - **Timing**: even, towards the start / middle / end, or random.
     - **Range**: **Task window** (only the days inside the task's tracking window) or **Whole period**.
     - **Tracking window**: the dates of the task's window (`from – to`, or a single date if both are the same day; `from – now` if the task has not reached status 2 yet). Shown only when Range is **Task window**.
     - **Pin** a task to always keep it in the list. Pinned tasks (with their **Per day** hours) are saved to the config file; the **only pinned** checkbox (on by default) shows just them, and **Load tasks** switches it off to show the JQL results.
   - Hours formats: `8`, `1.5`, `1:30`, `1h 30m`, `45m`.
   - The filter box narrows the list by any displayed field; **only with hours** hides tasks without hours. **Clear data** removes loaded tasks, entered hours, cached history and the current distribution from the browser.

   Then press **Calculate distribution**. 
   Collapsible sections on this page:
   - **Task tracking window**: a task is tracked only between its first move into status 1 (default `In Progress`) and its first move into status 2 (default `Done`), inside the selected period. Both statuses are picked from your Jira's status list (**Load statuses**). A checkbox (on by default) lists only tasks whose window overlaps the selected period (applies when **only pinned** is off). When tasks are loaded, their status history is read and **Range** is preset: Task window if the task has such a transition, Whole period otherwise. You can change it per task.
   - **Distribution options**: optionally enable a realistic spread so different days get different hours.
3. **Preview**: review the generated distribution as a table (tasks by days) or a list (by days), remove entries or whole cells you don't want, then approve to push the worklogs to Jira. A Stop button interrupts sending at any time; failed or remaining entries can be sent in the next run.
4. **Clear**: find and delete your own worklogs for a period (with a Stop button as well).

## Quick start

Requires Python 3.8+.

```
python jira-track.py
```

The browser opens at `http://127.0.0.1:4777` (set `JIRA_TRACK_PORT` to change it; a free port is picked if it is busy; `--no-open` skips opening the browser). Press `Ctrl+C` in the terminal or the **Stop app** button to quit.

## Config file (optional)

The **Save to config file** button stores the connection, JQL, displayed fields, pinned tasks (with their per day hours), working day settings (including the realistic spread option) and the tracking window statuses in `jira-track.config.json` next to the script. Once saved, it is loaded on every start and kept up to date automatically. Set `JIRA_TRACK_CONFIG` to use a different path.

The token is stored in plain text, so the config file is excluded via `.gitignore`. Do not commit or share it.

## Notes

- A tiny local server (bound to `127.0.0.1` only) serves the UI and proxies requests to Jira, because Jira Cloud blocks direct browser calls (CORS). Nothing is sent anywhere except your Jira site.
- Without a config file, the token is kept only in the browser's localStorage and sent to Jira through the local server.
- Jira Cloud only (REST API v3). Worklogs are created without changing the issue's remaining estimate.
- Times use your browser's time zone.
