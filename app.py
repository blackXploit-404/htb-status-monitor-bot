import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
STATE_FILE = PROJECT_DIR / "state.json"

load_dotenv(ENV_FILE)

HTB_TOKEN = os.getenv("HTB_TOKEN")
WEBHOOK = os.getenv("WEBHOOK") or os.getenv("DISCORD_WEBHOOK")
FOOTER_MESSAGE = os.getenv("FOOTER_MESSAGE") or (
    "Let's pwn together. Thanks, #!/bin/bash team." 
)

BASE_URL = "https://labs.hackthebox.com/api/v5/machines" # as i found this is the latest base url for machine related queries.

HEADERS = {
    "Authorization": f"Bearer {HTB_TOKEN}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (htb-status-monitor-bot)",
}

REQUEST_TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("htb-notifier")


def validate_config():
    """Hey mf , make sure required creds are configured properly."""

    missing = []

    if not HTB_TOKEN:
        missing.append("HTB_TOKEN")

    if not WEBHOOK:
        missing.append("WEBHOOK or DISCORD_WEBHOOK")

    if missing:
        log.error(
            "Missing environment variables: %s",
            ", ".join(missing),
        )
        log.error("Check your .env file.")
        sys.exit(1)


session = requests.Session()
session.headers.update(HEADERS)


def fetch(path, extra_params=None):
    """Fetch a paginated collection from the HTB machines endpoint."""

    items = []
    page = 1

    while True:
        url = f"{BASE_URL}{path}"

        params = {
            "per_page": 100,
            "page": page,
        }
        if extra_params:
            params.update(extra_params)

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 401:
            raise RuntimeError(
                "HTB authentication failed. Check your HTB_TOKEN."
            )

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, list):
            batch = payload
            last_page = page
        elif isinstance(payload, dict):
            batch = payload.get("data")

            if batch is None:
                batch = payload.get("info")

            if batch is None:
                batch = []

            if not isinstance(batch, list):
                raise ValueError(
                    f"Unexpected API response for {path}"
                )

            meta = payload.get("meta") or {}
            last_page = meta.get("last_page", page)

        else:
            raise ValueError(
                f"Unexpected response type for {path}"
            )

        items.extend(batch)

        log.info(
            "Fetched page %s from %s (%s items)",
            page,
            path,
            len(batch),
        )

        if not batch or page >= int(last_page):
            break

        page += 1

    return items


def fetch_machines(path="", extra_params=None):
    """Return a dictionary of machines indexed by their ID."""

    machines = fetch(path, extra_params=extra_params)
    result = {}

    for machine in machines:
        machine_id = machine.get("id")

        if machine_id is None:
            log.warning(
                "Skipping machine without an ID: %s",
                machine.get("name", "Unknown"),
            )
            continue

        result[machine_id] = machine

    return result


def post(title, machine, color, description):
    """Send a machine notification to Discord."""

    name = str(machine.get("name") or "Unknown machine")
    os_name = str(machine.get("os") or "Unknown")
    difficulty = str(
        machine.get("difficultyText") or "Unknown"
    )

    machine_url = (
        "https://app.hackthebox.com/machines/"
        + requests.utils.quote(name, safe="")
    )

    avatar = machine.get("avatar") or machine.get("image")
    machine_image_url = None
    if isinstance(avatar, str) and avatar.strip():
        machine_image_url = requests.compat.urljoin(
            "https://labs.hackthebox.com", avatar.strip()
        )

    embed = {
        "title": title,
        "description": description,
        "url": machine_url,
        "color": color,
        "fields": [
            {
                "name": "Machine",
                "value": name[:1024],
                "inline": True,
            },
            {
                "name": "OS",
                "value": os_name[:1024],
                "inline": True,
            },
            {
                "name": "Difficulty",
                "value": difficulty[:1024],
                "inline": True,
            },
        ],
        "footer": {"text": FOOTER_MESSAGE[:2048]},
    }

    if machine_image_url:
        embed["thumbnail"] = {"url": machine_image_url}

    release_date = (
        machine.get("releaseDate")
        or machine.get("release")
        or machine.get("release_date")
    )
    if release_date:
        release_value = str(release_date)[:1024]
        try:
            release_datetime = datetime.fromisoformat(
                str(release_date).replace("Z", "+00:00")
            )
            release_timestamp = int(release_datetime.timestamp())
            release_value = (
                f"<t:{release_timestamp}:F> "
                f"(<t:{release_timestamp}:R>)"
            )
        except (TypeError, ValueError, OverflowError):
            pass
        embed["fields"].append({
            "name": "Release time",
            "value": release_value,
            "inline": True,
        })

    creator = (
        machine.get("firstCreator")
        or machine.get("creator")
        or machine.get("maker")
    )
    if isinstance(creator, list):
        creator = creator[0] if creator else None
    if isinstance(creator, dict):
        creator = creator.get("name")
    if creator:
        embed["fields"].append({
            "name": "Creator",
            "value": str(creator)[:1024],
            "inline": True,
        })

    user_points = machine.get("user_points", machine.get("userPoints"))
    root_points = machine.get("root_points", machine.get("rootPoints"))
    if user_points is not None or root_points is not None:
        points_value = (
            f"User: {user_points if user_points is not None else '—'} · "
            f"Root: {root_points if root_points is not None else '—'}"
        )
    else:
        points = machine.get("points")
        points_value = f"{points} points" if points is not None else None
    if points_value:
        embed["fields"].append({
            "name": (
                "Season points"
                if user_points is not None or root_points is not None
                else "Points"
            ),
            "value": points_value[:1024],
            "inline": True,
        })

    labels = machine.get("labels") or machine.get("tags") or []
    if isinstance(labels, list):
        label_names = [
            str(label.get("name") or label.get("label"))
            if isinstance(label, dict)
            else str(label)
            for label in labels
        ]
        label_names = [label for label in label_names if label and label != "None"]
        if label_names:
            embed["fields"].append({
                "name": "Tags",
                "value": ", ".join(label_names)[:1024],
                "inline": False,
            })

    retiring = machine.get("retiring")
    if isinstance(retiring, dict) and retiring.get("name"):
        retiring_name = str(retiring["name"])
        retiring_id = retiring.get("id")
        retiring_value = (
            f"[{retiring_name}](https://app.hackthebox.com/machines/{retiring_id})"
            if retiring_id
            else retiring_name
        )
        embed["fields"].append({
            "name": "Retiring with this release",
            "value": retiring_value[:1024],
            "inline": False,
        })

    response = requests.post(
        WEBHOOK,
        json={
            "embeds": [embed],
            "allowed_mentions": {"parse": []},
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    log.info("Discord notification sent: %s", name)


def load_state():
    """Load the previously recorded machine IDs."""

    if not STATE_FILE.exists():
        return None

    try:
        state = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        if not isinstance(state, dict):
            raise ValueError("State must be a JSON object")

        active = state.get("active", [])
        retired = state.get("retired", [])
        next_release = state.get("next_release")

        if not isinstance(active, list):
            raise ValueError("'active' must be a list")

        if not isinstance(retired, list):
            raise ValueError("'retired' must be a list")

        if next_release is not None and not isinstance(next_release, (int, str)):
            raise ValueError("'next_release' must be an ID or null")

        return {
            "active": active,
            "retired": retired,
            "next_release": next_release,
        }

    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(
            f"Could not read {STATE_FILE}. "
            "Back it up and repair it before continuing."
        ) from error


def save_state(state):
    """Save state atomically to avoid partial JSON files."""

    temporary_file = STATE_FILE.with_suffix(".tmp")

    temporary_file.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )

    temporary_file.replace(STATE_FILE)


def main():
    validate_config()

    log.info("Fetching machines from %s...", BASE_URL)
    machines = fetch_machines("")
    active = {
        machine_id: machine
        for machine_id, machine in machines.items()
        if not str(machine.get("state") or "").lower().startswith("retired")
    }
    retired = {
        machine_id: machine
        for machine_id, machine in machines.items()
        if str(machine.get("state") or "").lower().startswith("retired")
    }

    unreleased = fetch_machines("", extra_params={"state": "unreleased"})
    scheduled = [
        machine for machine in unreleased.values()
        if machine.get("releaseDate") or machine.get("release")
    ]
    next_release = min(
        scheduled,
        key=lambda machine: str(
            machine.get("releaseDate") or machine.get("release")
        ),
        default=None,
    )

    log.info(
        "Found %s active and %s retired machines.",
        len(active),
        len(retired),
    )
    if next_release:
        log.info(
            "Next scheduled machine: %s (%s)",
            next_release.get("name", "Unknown"),
            next_release.get("releaseDate") or next_release.get("release"),
        )

    new_state = {
        "active": sorted(active.keys()),
        "retired": sorted(retired.keys()),
        "next_release": next_release.get("id") if next_release else None,
    }

    old_state = load_state()

    if old_state is None:
        save_state(new_state)
        log.info(
            "Initial state saved. No notifications sent."
        )
        return

    old_active = set(old_state["active"])
    old_retired = set(old_state["retired"])

    new_machines = [
        machine
        for machine_id, machine in active.items()
        if machine_id not in old_active
        and machine_id not in old_retired
    ]

    retired_machines = [
        machine
        for machine_id, machine in retired.items()
        if machine_id not in old_retired
    ]

    upcoming_machine = None
    if (
        next_release
        and str(old_state.get("next_release")) != str(next_release.get("id"))
    ):
        upcoming_machine = next_release

    log.info(
        "Detected %s new machines, %s newly retired machines, "
        "and %s next scheduled release.",
        len(new_machines),
        len(retired_machines),
        1 if upcoming_machine else 0,
    )

    for machine in new_machines:
        post(
            title="🆕 New Machine Released",
            machine=machine,
            color=0x9FEF00,
            description=(
                "A new machine has appeared in the active "
                "Hack The Box machine list."
            ),
        )

    for machine in retired_machines:
        post(
            title="📦 Machine Retired",
            machine=machine,
            color=0xFF5555,
            description=(
                "This machine has appeared in the retired "
                "Hack The Box machine list."
            ),
        )

    if upcoming_machine:
        post(
            title="⏳ Upcoming HTB Machine Release",
            machine=upcoming_machine,
            color=0x00AEEF,
            description=(
                "This is the next scheduled Hack The Box machine. "
                "Discord will show the release time in your local timezone."
            ),
        )

    save_state(new_state)

    log.info("State updated successfully.")
    log.info("Monitoring cycle completed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
        sys.exit(130)
    except requests.RequestException as error:
        log.error("Network or HTTP request failed: %s", error)
        sys.exit(1)
    except (RuntimeError, ValueError) as error:
        log.error("%s", error)
        sys.exit(1)
