"""银行核心逻辑：开户、转账、利息、冻结和汇率。

约束：
- 仅使用标准库；JSON 存档；不依赖网络。
- 业务日期固定为 FIXED_DATE，所有演示与结算均以此日期为基准。
- 转账、取消、结算均幂等：相同幂等键重复提交不会重复生效。
- 金额统一为整数最小货币单位，利息向下取整到最小单位。
"""

import json

FIXED_DATE = "2026-09-29"
MAX_ACCOUNTS = 10000
MAX_AMOUNT = 10 ** 12
DAILY_RATE = 0.01  # 日利率：百分之一（固定演示用）


def new_game():
    return {
        "accounts": {},
        "txn_id": 0,
        "date": FIXED_DATE,
        "txns": {},
    }


# ---------- 存档 ----------

def save_state(state):
    return json.dumps(state, ensure_ascii=False)


def load_state(text):
    if text is None or not str(text).strip():
        raise ValueError("empty save data")
    state = json.loads(text)
    if not isinstance(state, dict) or not isinstance(state.get("accounts"), dict):
        raise ValueError("invalid save data")
    state.setdefault("date", FIXED_DATE)
    state["date"] = FIXED_DATE  # 固定日期，读档不推进时间
    state["txn_id"] = _to_int(state.get("txn_id", 0))
    if state["txn_id"] < 0:
        raise ValueError("invalid txn_id")
    state["txns"] = state.get("txns") if isinstance(state.get("txns"), dict) else {}
    for acc_id, acc in state["accounts"].items():
        if not isinstance(acc, dict):
            raise ValueError("invalid account data")
        acc["balance"] = _to_int(acc.get("balance", 0))
        acc["frozen"] = bool(acc.get("frozen", False))
        if acc["balance"] < 0:
            raise ValueError("negative balance in save data")
        acc.setdefault("interest_periods", {})
    return state


# ---------- 校验辅助 ----------

def _to_int(value):
    if isinstance(value, bool):
        raise ValueError("bool is not a valid number")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ValueError("non-integer amount")
        return int(value)
    raise ValueError("invalid number: %r" % (value,))


def _check_amount(value, name="amount"):
    amount = _to_int(value)
    if amount <= 0:
        raise ValueError("%s must be positive" % name)
    if amount > MAX_AMOUNT:
        raise ValueError("%s exceeds limit" % name)
    return amount


def _check_nonneg_amount(value, name="amount"):
    amount = _to_int(value)
    if amount < 0:
        raise ValueError("%s must be non-negative" % name)
    if amount > MAX_AMOUNT:
        raise ValueError("%s exceeds limit" % name)
    return amount


def _account(state, acc_id):
    if not isinstance(acc_id, str) or not acc_id:
        raise ValueError("invalid account id")
    acc = state["accounts"].get(acc_id)
    if acc is None:
        raise KeyError("account not found: %s" % acc_id)
    return acc


def can_operate(state, acc_id):
    """账户存在且未冻结才可操作。"""
    acc = state["accounts"].get(acc_id)
    return bool(acc) and not acc["frozen"]


def _next_txn_id(state):
    state["txn_id"] += 1
    return state["txn_id"]


# ---------- 开户 ----------

def open_account(state, acc_id, balance):
    """同一账户重复开户返回 False；初始余额必须非负；受容量上限约束。"""
    if not isinstance(acc_id, str) or not acc_id.strip():
        raise ValueError("invalid account id")
    balance = _check_nonneg_amount(balance, "balance")
    if acc_id in state["accounts"]:
        return False
    if len(state["accounts"]) >= MAX_ACCOUNTS:
        raise OverflowError("account capacity reached")
    state["accounts"][acc_id] = {
        "balance": balance,
        "frozen": False,
        "interest_periods": {},
    }
    _next_txn_id(state)
    return True


def set_frozen(state, acc_id, frozen):
    _account(state, acc_id)["frozen"] = bool(frozen)
    return True


# ---------- 转账（幂等） ----------

def transfer(state, src, dst, amount, key=None):
    """冻结/不存在/余额不足均失败且不改动任何余额；key 相同的重试返回首次结果。"""
    amount = _check_amount(amount)
    if src == dst:
        raise ValueError("source and destination must differ")
    src_acc = state["accounts"].get(src)
    dst_acc = state["accounts"].get(dst)
    if src_acc is None or dst_acc is None:
        return False
    if key is not None and key in state["txns"]:
        return state["txns"][key]["ok"]
    if src_acc["frozen"] or dst_acc["frozen"]:
        ok = False
    elif src_acc["balance"] < amount:
        ok = False
    else:
        src_acc["balance"] -= amount
        dst_acc["balance"] += amount
        ok = True
    if key is not None:
        state["txns"][key] = {"ok": ok, "type": "transfer",
                              "src": src, "dst": dst, "amount": amount,
                              "date": state.get("date", FIXED_DATE)}
    if ok:
        _next_txn_id(state)
    return ok


def cancel_transfer(state, src, dst, amount, key=None):
    """撤销转账：仅在对方账户确有对应在途金额时返还，幂等且不会造成透支。"""
    amount = _check_amount(amount)
    if src == dst:
        raise ValueError("source and destination must differ")
    src_acc = state["accounts"].get(src)
    dst_acc = state["accounts"].get(dst)
    if src_acc is None or dst_acc is None:
        return False
    if key is not None and key in state["txns"]:
        return state["txns"][key]["ok"]
    if src_acc["frozen"] or dst_acc["frozen"]:
        ok = False
    elif dst_acc["balance"] < amount:
        ok = False
    else:
        dst_acc["balance"] -= amount
        src_acc["balance"] += amount
        ok = True
    if key is not None:
        state["txns"][key] = {"ok": ok, "type": "cancel",
                              "src": src, "dst": dst, "amount": amount,
                              "date": state.get("date", FIXED_DATE)}
    if ok:
        _next_txn_id(state)
    return ok


# ---------- 利息（结算幂等，含首尾两天） ----------

def interest(state, acc_id, days, rate=DAILY_RATE, period=FIXED_DATE):
    """按实际天数计息（跨日按 days 天，不再少算一天）。

    同一 period 重复结算返回 0 且不重复入账；返回本次入账利息（整数最小单位）。
    """
    days = _check_amount(days, "days")
    if rate < 0:
        raise ValueError("rate must be non-negative")
    acc = _account(state, acc_id)
    if acc["frozen"]:
        return 0
    periods = acc.setdefault("interest_periods", {})
    if str(period) in periods:
        return 0
    interest_amount = int(acc["balance"] * rate * days)
    if interest_amount:
        acc["balance"] += interest_amount
    periods[str(period)] = {"days": days, "rate": rate,
                            "interest": interest_amount,
                            "date": state.get("date", FIXED_DATE)}
    _next_txn_id(state)
    return interest_amount


# ---------- 手续费 ----------

def charge_fee(state, acc_id, fee, success):
    """只有成功交易才扣手续费；账户冻结或余额不足时扣费失败。"""
    fee = _check_nonneg_amount(fee, "fee")
    acc = _account(state, acc_id)
    if not success:
        return False
    if acc["frozen"] or acc["balance"] < fee:
        return False
    acc["balance"] -= fee
    _next_txn_id(state)
    return True


# ---------- 汇率（只换算一次） ----------

def convert(state, amount, rate):
    amount = _check_nonneg_amount(amount)
    if rate < 0:
        raise ValueError("rate must be non-negative")
    return int(amount * rate)


# ---------- CMD 菜单（固定日期） ----------

def main():
    print("日期: %s" % FIXED_DATE)
    print("银行 - 命令: open/transfer/interest/cancel/operate/fee/convert/quit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            print("error: empty command")
            continue
        if raw == "quit":
            break
        parts = raw.split()
        cmd = parts[0]
        args = parts[1:]
        try:
            if cmd == "open" and len(args) == 2:
                print("ok" if open_account(_STATE, args[0], int(args[1])) else "error: account exists")
            elif cmd == "transfer" and len(args) in (3, 4):
                key = args[3] if len(args) == 4 else None
                print("ok" if transfer(_STATE, args[0], args[1], int(args[2]), key) else "error: transfer failed")
            elif cmd == "interest" and len(args) in (2, 3, 4):
                days = int(args[1])
                rate = float(args[2]) if len(args) >= 3 else DAILY_RATE
                period = args[3] if len(args) == 4 else FIXED_DATE
                print("ok interest=%s" % interest(_STATE, args[0], days, rate, period))
            elif cmd == "cancel" and len(args) in (3, 4):
                key = args[3] if len(args) == 4 else None
                print("ok" if cancel_transfer(_STATE, args[0], args[1], int(args[2]), key) else "error: cancel failed")
            elif cmd == "operate" and len(args) == 1:
                print("ok" if can_operate(_STATE, args[0]) else "error: not operable")
            elif cmd == "freeze" and len(args) == 2:
                set_frozen(_STATE, args[0], args[1] in ("1", "true", "yes"))
                print("ok")
            elif cmd == "fee" and len(args) == 3:
                print("ok" if charge_fee(_STATE, args[0], int(args[1]), args[2] in ("1", "true", "success")) else "error: fee not charged")
            elif cmd == "convert" and len(args) == 2:
                print("ok %s" % convert(_STATE, int(args[0]), float(args[1])))
            elif cmd == "balance" and len(args) == 1:
                print("ok %s" % _account(_STATE, args[0])["balance"])
            elif cmd == "save" and len(args) <= 1:
                if args:
                    with open(args[0], "w", encoding="utf-8") as fh:
                        fh.write(save_state(_STATE))
                    print("ok")
                else:
                    print("ok " + save_state(_STATE))
            elif cmd == "load" and len(args) == 1:
                with open(args[0], "r", encoding="utf-8") as fh:
                    data = fh.read()
                _STATE.clear()
                _STATE.update(load_state(data))
                print("ok")
            else:
                print("error: unknown or malformed command")
        except (ValueError, KeyError, OverflowError) as exc:
            print("error: %s" % exc)


_STATE = new_game()


if __name__ == "__main__":
    main()
