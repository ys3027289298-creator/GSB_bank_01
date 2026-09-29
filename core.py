"""银行核心逻辑：开户、转账、利息、冻结和汇率。"""

import json

MAX_BALANCE = 10 ** 12  # 容量上限，防止溢出


def new_game():
    return {
        "accounts": {},
        "txn_id": 0,
        "ledger": [],
    }


def save_state(state):
    return json.dumps(state, ensure_ascii=False)


def load_state(text):
    if not text or not text.strip():
        return new_game()
    state = json.loads(text)
    state.setdefault("accounts", {})
    state.setdefault("txn_id", 0)
    state.setdefault("ledger", [])
    return state


def _next_txn_id(state):
    state["txn_id"] += 1
    return state["txn_id"]


def open_account(state, acc_id, balance):
    if not acc_id or acc_id in state["accounts"]:
        return False
    if not isinstance(balance, (int, float)) or balance < 0 or balance > MAX_BALANCE:
        return False
    state["accounts"][acc_id] = {"balance": balance, "frozen": False}
    return True


def can_operate(state, acc_id):
    acc = state["accounts"].get(acc_id)
    return acc is not None and not acc["frozen"]


def transfer(state, src, dst, amount, txn_id=None):
    if txn_id is not None and any(t["id"] == txn_id for t in state["ledger"]):
        return False  # 重复提交，幂等拒绝
    if src == dst:
        return False
    if src not in state["accounts"] or dst not in state["accounts"]:
        return False
    if not can_operate(state, src) or not can_operate(state, dst):
        return False
    if not isinstance(amount, (int, float)) or amount <= 0:
        return False
    if state["accounts"][src]["balance"] < amount:
        return False
    if state["accounts"][dst]["balance"] + amount > MAX_BALANCE:
        return False
    state["accounts"][src]["balance"] -= amount
    state["accounts"][dst]["balance"] += amount
    state["ledger"].append({
        "id": txn_id if txn_id is not None else _next_txn_id(state),
        "type": "transfer",
        "src": src,
        "dst": dst,
        "amount": amount,
        "status": "done",
    })
    return True


def cancel_transfer(state, src, dst, amount):
    for txn in state["ledger"]:
        if (txn["type"] == "transfer" and txn["status"] == "done"
                and txn["src"] == src and txn["dst"] == dst
                and txn["amount"] == amount):
            txn["status"] = "cancelled"
            state["accounts"][src]["balance"] += amount
            state["accounts"][dst]["balance"] -= amount
            return True
    return False  # 无匹配流水或已取消，幂等


def interest(state, acc_id, days):
    if acc_id not in state["accounts"] or not can_operate(state, acc_id):
        return 0
    if not isinstance(days, int) or days <= 0:
        return 0
    settled = sum(
        t["amount"] for t in state["ledger"]
        if t["type"] == "interest" and t["src"] == acc_id
    )
    if days <= settled:
        return 0  # 已结算过的天数不重复计息，幂等
    state["ledger"].append({
        "id": _next_txn_id(state),
        "type": "interest",
        "src": acc_id,
        "dst": acc_id,
        "amount": days,
        "status": "done",
    })
    return days


def charge_fee(state, acc_id, fee, success):
    if not success:
        return False
    acc = state["accounts"].get(acc_id)
    if acc is None or not can_operate(state, acc_id):
        return False
    if not isinstance(fee, (int, float)) or fee < 0 or acc["balance"] < fee:
        return False
    acc["balance"] -= fee
    return True


def convert(state, amount, rate):
    return amount * rate


def main():
    state = new_game()
    print("银行 - 命令: open/transfer/interest/cancel/operate/fee/convert/quit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            print("空命令，请重新输入")
            continue
        parts = raw.split()
        cmd, args = parts[0], parts[1:]
        try:
            if cmd == "quit":
                break
            elif cmd == "open" and len(args) == 2:
                ok = open_account(state, args[0], int(args[1]))
                print("ok" if ok else "失败：账户已存在或金额非法")
            elif cmd == "transfer" and len(args) == 3:
                ok = transfer(state, args[0], args[1], int(args[2]))
                print("ok" if ok else "失败：余额不足、账户冻结或金额非法")
            elif cmd == "interest" and len(args) == 2:
                print(interest(state, args[0], int(args[1])))
            elif cmd == "cancel" and len(args) == 3:
                ok = cancel_transfer(state, args[0], args[1], int(args[2]))
                print("ok" if ok else "失败：无匹配交易或已取消")
            elif cmd == "operate" and len(args) == 1:
                print("ok" if can_operate(state, args[0]) else "失败：账户冻结或不存在")
            elif cmd == "fee" and len(args) == 3:
                ok = charge_fee(state, args[0], int(args[1]), args[2] == "success")
                print("ok" if ok else "失败：交易未成功或余额不足")
            elif cmd == "convert" and len(args) == 2:
                print(convert(state, int(args[0]), float(args[1])))
            else:
                print("非法命令")
        except ValueError:
            print("非法参数")


if __name__ == "__main__":
    main()
