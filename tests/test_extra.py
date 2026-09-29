import io
import json
import unittest
from unittest import mock

import core


class TestGuards(unittest.TestCase):
    def test_duplicate_open_keeps_balance(self):
        state = core.new_game()
        self.assertTrue(core.open_account(state, "A", 100))
        self.assertFalse(core.open_account(state, "A", 999))
        self.assertEqual(state["accounts"]["A"]["balance"], 100)

    def test_open_rejects_bad_id_and_balance(self):
        state = core.new_game()
        with self.assertRaises(ValueError):
            core.open_account(state, "", 10)
        with self.assertRaises(ValueError):
            core.open_account(state, "B", -1)
        with self.assertRaises(ValueError):
            core.open_account(state, "C", True)

    def test_capacity_boundary(self):
        state = core.new_game()
        with mock.patch.object(core, "MAX_ACCOUNTS", 3):
            self.assertTrue(core.open_account(state, "A", 0))
            self.assertTrue(core.open_account(state, "B", 0))
            self.assertTrue(core.open_account(state, "C", 0))
            with self.assertRaises(OverflowError):
                core.open_account(state, "D", 0)
        self.assertEqual(len(state["accounts"]), 3)

    def test_transfer_frozen_or_missing_or_zero(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.open_account(state, "B", 0)
        self.assertFalse(core.transfer(state, "A", "X", 10))
        self.assertFalse(core.transfer(state, "X", "A", 10))
        core.set_frozen(state, "B", True)
        self.assertFalse(core.transfer(state, "A", "B", 10))
        self.assertEqual(state["accounts"]["A"]["balance"], 100)
        with self.assertRaises(ValueError):
            core.transfer(state, "A", "A", 10)
        with self.assertRaises(ValueError):
            core.transfer(state, "A", "B", 0)

    def test_transfer_idempotent_by_key(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.open_account(state, "B", 0)
        self.assertTrue(core.transfer(state, "A", "B", 30, key="t1"))
        # 重复提交同一请求：不再次扣款
        self.assertTrue(core.transfer(state, "A", "B", 30, key="t1"))
        self.assertEqual(state["accounts"]["A"]["balance"], 70)
        self.assertEqual(state["accounts"]["B"]["balance"], 30)
        # 失败请求同样幂等
        self.assertFalse(core.transfer(state, "A", "B", 999, key="t2"))
        self.assertFalse(core.transfer(state, "A", "B", 999, key="t2"))
        self.assertEqual(state["accounts"]["A"]["balance"], 70)

    def test_cancel_idempotent_and_safe(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.open_account(state, "B", 0)
        core.transfer(state, "A", "B", 30, key="t1")
        self.assertTrue(core.cancel_transfer(state, "A", "B", 30, key="c1"))
        self.assertTrue(core.cancel_transfer(state, "A", "B", 30, key="c1"))
        self.assertEqual(state["accounts"]["A"]["balance"], 100)
        self.assertEqual(state["accounts"]["B"]["balance"], 0)
        # 对方账户没有对应在途金额时取消失败
        self.assertFalse(core.cancel_transfer(state, "A", "B", 5, key="c2"))
        self.assertEqual(state["accounts"]["A"]["balance"], 100)
        self.assertEqual(state["accounts"]["B"]["balance"], 0)

    def test_interest_settlement_idempotent(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        self.assertEqual(core.interest(state, "A", 5), 5)
        self.assertEqual(core.interest(state, "A", 5), 0)
        self.assertEqual(state["accounts"]["A"]["balance"], 105)
        core.open_account(state, "B", 100)
        core.set_frozen(state, "B", True)
        self.assertEqual(core.interest(state, "B", 5), 0)
        self.assertEqual(state["accounts"]["B"]["balance"], 100)

    def test_fee_rules(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        self.assertFalse(core.charge_fee(state, "A", 10, False))
        self.assertTrue(core.charge_fee(state, "A", 10, True))
        self.assertEqual(state["accounts"]["A"]["balance"], 90)
        self.assertFalse(core.charge_fee(state, "A", 999, True))
        with self.assertRaises(ValueError):
            core.charge_fee(state, "A", -1, True)

    def test_convert_once_and_guards(self):
        state = core.new_game()
        self.assertEqual(core.convert(state, 100, 2), 200)
        self.assertEqual(core.convert(state, 0, 2), 0)
        with self.assertRaises(ValueError):
            core.convert(state, -5, 2)
        with self.assertRaises(ValueError):
            core.convert(state, 100, -1)

    def test_save_load_roundtrip_and_txn_uniqueness(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.open_account(state, "B", 0)
        core.transfer(state, "A", "B", 30, key="t1")
        txn_id_before = state["txn_id"]
        loaded = core.load_state(core.save_state(state))
        self.assertEqual(loaded["txn_id"], txn_id_before)
        self.assertEqual(loaded["accounts"]["A"]["balance"], 70)
        # 读档后重放旧请求不会重复入账，新请求拿到不冲突的新流水号
        self.assertTrue(core.transfer(loaded, "A", "B", 10, key="t1"))
        self.assertEqual(loaded["accounts"]["A"]["balance"], 70)
        self.assertTrue(core.transfer(loaded, "A", "B", 10, key="t3"))
        self.assertGreater(loaded["txn_id"], txn_id_before)
        self.assertEqual(loaded["date"], core.FIXED_DATE)

    def test_load_empty_or_bad_data(self):
        with self.assertRaises(ValueError):
            core.load_state("")
        with self.assertRaises(ValueError):
            core.load_state("   ")
        with self.assertRaises(ValueError):
            core.load_state(None)
        with self.assertRaises(ValueError):
            core.load_state(json.dumps({"accounts": {"A": {"balance": -1}}}))
        with self.assertRaises(ValueError):
            core.load_state("not-json")

    def test_failed_txn_does_not_increment_txn_id(self):
        state = core.new_game()
        core.open_account(state, "A", 10)
        core.open_account(state, "B", 0)
        before = state["txn_id"]
        core.transfer(state, "A", "B", 999, key="x")
        self.assertEqual(state["txn_id"], before)


class TestMenu(unittest.TestCase):
    def _run_menu(self, lines):
        state = core.new_game()
        stdin = io.StringIO("\n".join(lines) + "\n")
        stdout = io.StringIO()
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", stdout), \
                mock.patch.object(core, "_STATE", state):
            core.main()
        return stdout.getvalue()

    def test_illegal_and_empty_commands(self):
        out = self._run_menu(["", "frobnicate A B", "open A", "open A notanumber", "quit"])
        self.assertIn("error: empty command", out)
        self.assertIn("error: unknown or malformed command", out)
        self.assertIn("invalid", out)
        self.assertNotIn("Traceback", out)

    def test_happy_path_and_duplicate_input(self):
        out = self._run_menu([
            "open A 100",
            "open A 100",
            "open B 0",
            "transfer A B 30 t1",
            "transfer A B 30 t1",
            "balance A",
            "balance B",
            "freeze B 1",
            "operate B",
            "transfer A B 5 t2",
            "freeze B 0",
            "cancel A B 30 c1",
            "cancel A B 30 c1",
            "balance A",
            "balance B",
            "interest A 5",
            "convert 100 2",
            "fee A 10 0",
            "balance A",
            "quit",
        ])
        self.assertIn("error: account exists", out)
        self.assertIn("ok 70", out)       # A after one (idempotent) transfer
        self.assertIn("ok 30", out)       # B got 30 exactly once
        self.assertIn("error: not operable", out)
        self.assertIn("error: transfer failed", out)  # frozen destination
        self.assertIn("ok 100", out)      # A refunded by cancel, once
        self.assertIn("ok 0", out)        # B returned to 0
        self.assertIn("ok interest=5", out)
        self.assertIn("ok 200", out)
        self.assertIn("ok 105", out)      # fee not charged on failure


if __name__ == "__main__":
    unittest.main()
