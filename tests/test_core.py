import unittest

import core


class TestCore(unittest.TestCase):
    def test_01_no_duplicate_account(self):
        state = core.new_game()
        self.assertTrue(core.open_account(state, "A", 100))
        self.assertFalse(core.open_account(state, "A", 100))

    def test_02_no_transfer_without_balance(self):
        state = core.new_game()
        core.open_account(state, "A", 50)
        core.open_account(state, "B", 0)
        result = core.transfer(state, "A", "B", 100)
        self.assertFalse(result)
        self.assertEqual(state["accounts"]["A"]["balance"], 50)

    def test_03_interest_exact(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        self.assertEqual(core.interest(state, "A", 5), 5)

    def test_04_cancel_transfer_refunds(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.open_account(state, "B", 0)
        core.transfer(state, "A", "B", 30)
        core.cancel_transfer(state, "A", "B", 30)
        self.assertEqual(state["accounts"]["A"]["balance"], 100)
        self.assertEqual(state["accounts"]["B"]["balance"], 0)

    def test_05_frozen_account_not_operable(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        state["accounts"]["A"]["frozen"] = True
        self.assertFalse(core.can_operate(state, "A"))

    def test_06_fee_not_charged_on_failure(self):
        state = core.new_game()
        core.open_account(state, "A", 100)
        core.charge_fee(state, "A", 10, False)
        self.assertEqual(state["accounts"]["A"]["balance"], 100)

    def test_07_convert_once(self):
        state = core.new_game()
        self.assertEqual(core.convert(state, 100, 2), 200)

    def test_08_load_preserves_txn_id(self):
        state = core.new_game()
        state["txn_id"] = 6
        loaded = core.load_state(core.save_state(state))
        self.assertEqual(loaded["txn_id"], 6)


if __name__ == "__main__":
    unittest.main()
