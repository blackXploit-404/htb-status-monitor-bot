# HTB Status Monitor Bot

This is a simple script that checks the Hack The Box machines API and posts Discord embeds for the next scheduled (unreleased) machine, newly released machines, and newly retired machines. Scheduled release alerts use HTB's unreleased-machine feed and show the release time in each Discord user's local timezone. It uses a Discord **webhook**, so there is no need to create or host a Discord bot application separately.

## Configure Discord

In Discord, just headover to **Server Settings → Integrations → Webhooks**, create a webhook in the channel where updates should appear, and copy its URL. and make sure to keep the url private.

## Configure your HTB token

Create an API token in your Hack The Box account settings. Store it in an environment variable.

For local setup follow this - 

```sh
cp .env.example .env
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

## Note : 
The script reads/writes `state.json`, including the ID of the next scheduled release to prevent repeat alerts. On its first run without a state file, it records the current machines as a baseline and sends no alerts. Later runs compare with that saved state. Keep `state.json` between runs; losing it means the next run becomes a fresh baseline.

## Run it automatically with GitHub Actions

The included `.github/workflows/htb.yml` runs every 5 ( you can change the interval as you want ) minutes and can also be started manually from the repository's **Actions** tab. To enable it:

1. Push this project to a GitHub repository.
2. In **Settings → Secrets and variables → Actions**, add repository secrets named `HTB_TOKEN` and `DISCORD_WEBHOOK`. Optionally add a repository variable named `FOOTER_MESSAGE` to customize the embed sign-off.
3. In **Settings → Actions → General → Workflow permissions**, allow read and write access so the workflow can save updated `state.json`.
4. Open **Actions → HTB status bot → Run workflow** to start a manual run. The existing `state.json` is used as the starting point; review it if you want a clean baseline with no initial alerts.

Thats all.

## Contributing

Contributions are welcome. For any changes, open an issue first to discuss the approach. For a change you'd like to submit:

1. Fork the repository and create a branch for your change. [This is required ]
2. Set up a virtual environment and install dependencies as described above. Copy `.env.example` to `.env` and use your own credentials only if you need to run the bot; automated tests do not need live HTB or Discord credentials.
3. Make the change and add or update tests when behavior changes. Keep `tests/test_app.py` in the repository so future contributors can check that the bot still behaves as expected. Run the test suite with `python -m unittest discover -s tests`.
4. Open a pull request describing the change and the checks you ran.

