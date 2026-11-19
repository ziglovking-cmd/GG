import unittest
from unittest.mock import call, patch

from app import accounts, db, inviting
from app.bootstrap import invitations as services
from app.domain import invitations as policy


class StartupStaggerTests(unittest.TestCase):
    def tearDown(self):
        for campaign_id in (13, 14, 99):
            inviting.STATE.pop(campaign_id, None)

    def test_two_campaigns_are_interleaved_in_ten_account_waves(self):
        first = [
            policy.startup_stagger_delay(index, 0, 2, jitter=0)
            for index in (0, 9, 10, 19, 20, 49)
        ]
        second = [
            policy.startup_stagger_delay(index, 1, 2, jitter=0)
            for index in (0, 9, 10, 19, 20, 46)
        ]

        self.assertEqual(first, [0, 0, 600, 600, 1200, 2400])
        self.assertEqual(second, [300, 300, 900, 900, 1500, 2700])

    def test_start_slots_follow_launch_order_not_campaign_id(self):
        rows = [{"id": 13}, {"id": 14}]
        with patch.object(db, "q", return_value=rows):
            first = services.scheduler.running_campaign_slot({"id": 14, "target_chat_id": 777})
            second = services.scheduler.running_campaign_slot({"id": 13, "target_chat_id": 777})

        self.assertEqual(first, (0, 2))
        self.assertEqual(second, (1, 2))

    def test_startup_schedule_is_persisted_through_account_timer(self):
        campaign = {"id": 99, "target_chat_id": 777}
        account_ids = list(range(1, 13))

        def defer(account_id, seconds, now=None):
            return int(now) + int(seconds)

        with (
            patch.object(services.scheduler, "running_campaign_slot", return_value=(1, 2)),
            patch.object(policy.random, "randint", return_value=0),
            patch.object(accounts, "defer_next_attempt", side_effect=defer) as save,
        ):
            scheduled = services.scheduler.schedule_startup_stagger(
                campaign, account_ids, now=1_000
            )

        self.assertEqual(scheduled[1], 1_300)
        self.assertEqual(scheduled[10], 1_300)
        self.assertEqual(scheduled[11], 1_900)
        self.assertEqual(save.call_args_list[:10], [
            call(account_id, 300, now=1_000) for account_id in range(1, 11)
        ])
        self.assertEqual(save.call_args_list[10:], [
            call(account_id, 900, now=1_000) for account_id in range(11, 13)
        ])


if __name__ == "__main__":
    unittest.main()
