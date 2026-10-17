import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "state.json"
        self.state_patcher = patch.object(app, "STATE_FILE", self.state_file)
        self.state_patcher.start()
        self.config_patcher = patch.object(app, "validate_config")
        self.config_patcher.start()

    def tearDown(self):
        self.config_patcher.stop()
        self.state_patcher.stop()
        self.temp_dir.cleanup()

    def test_detects_new_release_retirement_and_next_scheduled_box(self):
        app.save_state({
            "active": [1, 2],
            "retired": [3],
            "next_release": 4,
        })
        current_machines = {
            1: {"id": 1, "name": "Existing", "state": "active"},
            4: {"id": 4, "name": "JustReleased", "state": "active"},
            3: {"id": 3, "name": "OldRetired", "state": "retired"},
            6: {"id": 6, "name": "NewRetired", "state": "retired"},
        }
        upcoming_machines = {
            7: {
                "id": 7,
                "name": "ComingSoon",
                "releaseDate": "2026-10-17T19:00:00.000Z",
            }
        }

        def fake_fetch(_path="", extra_params=None):
            return upcoming_machines if extra_params else current_machines

        notifications = []
        with patch.object(app, "fetch_machines", side_effect=fake_fetch), patch.object(
            app, "post", side_effect=lambda **kwargs: notifications.append(kwargs)
        ):
            app.main()

        self.assertEqual(
            [item["title"] for item in notifications],
            [
                "🆕 New Machine Released",
                "📦 Machine Retired",
                "⏳ Upcoming HTB Machine Release",
            ],
        )
        self.assertEqual(
            [item["machine"]["id"] for item in notifications], [4, 6, 7]
        )
        self.assertEqual(
            app.load_state(),
            {"active": [1, 4], "retired": [3, 6], "next_release": 7},
        )

    def test_first_run_saves_baseline_without_alerts(self):
        current_machines = {1: {"id": 1, "name": "Current", "state": "active"}}
        upcoming_machines = {
            2: {"id": 2, "name": "Upcoming", "releaseDate": "2026-10-17T19:00:00Z"}
        }

        def fake_fetch(_path="", extra_params=None):
            return upcoming_machines if extra_params else current_machines

        with patch.object(app, "fetch_machines", side_effect=fake_fetch), patch.object(
            app, "post"
        ) as post:
            app.main()

        post.assert_not_called()
        self.assertEqual(
            app.load_state(),
            {"active": [1], "retired": [], "next_release": 2},
        )

    def test_notification_failure_does_not_advance_state(self):
        previous_state = {"active": [1], "retired": [], "next_release": None}
        app.save_state(previous_state)
        current_machines = {
            1: {"id": 1, "name": "Existing", "state": "active"},
            2: {"id": 2, "name": "New", "state": "active"},
        }

        def fake_fetch(_path="", extra_params=None):
            return {} if extra_params else current_machines

        with patch.object(app, "fetch_machines", side_effect=fake_fetch), patch.object(
            app, "post", side_effect=RuntimeError("Discord unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "Discord unavailable"):
                app.main()

        self.assertEqual(app.load_state(), previous_state)

    def test_same_next_release_and_machine_sets_do_not_repeat_alerts(self):
        current_machines = {
            1: {"id": 1, "name": "Current", "state": "active"},
            2: {"id": 2, "name": "Retired", "state": "retired"},
        }
        previous_state = {
            "active": [1],
            "retired": [2],
            "next_release": 3,
        }
        app.save_state(previous_state)
        upcoming_machines = {
            3: {"id": 3, "name": "Upcoming", "releaseDate": "2026-10-17T19:00:00Z"}
        }

        def fake_fetch(_path="", extra_params=None):
            return upcoming_machines if extra_params else current_machines

        with patch.object(app, "fetch_machines", side_effect=fake_fetch), patch.object(
            app, "post"
        ) as post:
            app.main()

        post.assert_not_called()
        self.assertEqual(app.load_state(), previous_state)


class DiscordEmbedTests(unittest.TestCase):
    def test_embed_includes_image_time_creator_points_tags_retirement_and_footer(self):
        machine = {
            "id": 990,
            "name": "Stream",
            "os": "Linux",
            "difficultyText": "Medium",
            "avatar": "/storage/avatars/stream.png",
            "releaseDate": "2026-10-10T19:00:00.000Z",
            "firstCreator": {"name": "creator"},
            "user_points": 0,
            "root_points": 0,
            "labels": [{"name": "Seasonal"}, "Linux"],
            "retiring": {"id": 903, "name": "DevHub"},
        }
        response = type("Response", (), {"raise_for_status": lambda self: None})()

        with (
            patch.object(app, "WEBHOOK", "https://discord.example/webhook"),
            patch.object(
                app,
                "FOOTER_MESSAGE",
                "Let's pwn together. Thanks, #!/bin/bash team.",
            ),
            patch.object(
                app.requests, "post", return_value=response
            ) as post_request,
        ):
            app.post("Test", machine, 0x00AEEF, "Test alert")

        payload = post_request.call_args.kwargs["json"]
        embed = payload["embeds"][0]
        self.assertEqual(
            embed["thumbnail"]["url"],
            "https://labs.hackthebox.com/storage/avatars/stream.png",
        )
        self.assertEqual(
            embed["footer"]["text"],
            "Let's pwn together. Thanks, #!/bin/bash team.",
        )
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertIn("<t:", fields["Release time"])
        self.assertEqual(fields["Creator"], "creator")
        self.assertEqual(fields["Season points"], "User: 0 · Root: 0")
        self.assertEqual(fields["Tags"], "Seasonal, Linux")
        self.assertIn("DevHub", fields["Retiring with this release"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})


if __name__ == "__main__":
    unittest.main()
