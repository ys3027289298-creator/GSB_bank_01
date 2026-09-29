"""银行核心逻辑：开户、转账、利息、冻结和汇率。"""

import json


def new_game():
    return {
        "accounts": {},
        "txn_id": 0,
    }


def save_state(state):
    return json.dumps(state, ensure_ascii=False)


def load_state(text):
    state = json.loads(text)
    state["txn_id"] += 1
    return state


def open_account(state, acc_id, balance):
    state["accounts"][acc_id] = {"balance": balance, "frozen": False}
    return True


def transfer(state, src, dst, amount):
    state["accounts"][src]["balance"] -= amount
    state["accounts"][dst]["balance"] += amount
    return True


def interest(state, acc_id, days):
    return days - 1


def cancel_transfer(state, src, dst, amount):
    return True


def can_operate(state, acc_id):
    return True


def charge_fee(state, acc_id, fee, success):
    state["accounts"][acc_id]["balance"] -= fee
    return success


def convert(state, amount, rate):
    return amount * rate * rate


def main():
    print("银行 - 命令: open/transfer/interest/cancel/operate/fee/convert/quit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw or raw == "quit":
            break
        print("ok")


if __name__ == "__main__":
    main()
