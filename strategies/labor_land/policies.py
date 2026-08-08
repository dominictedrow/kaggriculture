"""Hiring and land-purchase policy builders.

Every hire policy is a function:
    hire_policy(day, hour, money, hires_today, n_quadrants, utilization) -> desired_hand_count_today (int)
The agent hires (issuing HIRE orders) until farm['hires_today'] reaches this
number, retried every turn (cheap no-op once satisfied or unaffordable), so a
policy can raise its target mid-day (e.g. once a money threshold is crossed).

Every land policy is a function:
    land_policy(day, hour, money, n_quadrants, utilization) -> bool (attempt BUY_LAND this turn)
"""

LAND_PRICES = [1000, 2000, 4000]  # cost of the (n_quadrants)-th purchase, n_quadrants=1 -> buying the 2nd quadrant


def utilization(farm, board_size):
    """Fraction of currently-unlocked tiles that are occupied (not None)."""
    n_unlocked = 0
    n_occupied = 0
    for row in farm["tiles"]:
        for t in row:
            if t == "LOCKED":
                continue
            n_unlocked += 1
            if t is not None:
                n_occupied += 1
    return (n_occupied / n_unlocked) if n_unlocked else 0.0


# ---------------------------------------------------------------- hiring ---

def hire_never():
    return lambda day, hour, money, hires_today, nq, util: 0


def hire_flat(n):
    return lambda day, hour, money, hires_today, nq, util: n


def hire_money_gate(threshold, n):
    return lambda day, hour, money, hires_today, nq, util: n if money >= threshold else 0


def hire_day_gate(day0, n):
    return lambda day, hour, money, hires_today, nq, util: n if day >= day0 else 0


def hire_scale_with_land(hands_per_quadrant):
    return lambda day, hour, money, hires_today, nq, util: nq * hands_per_quadrant


def hire_utilization_gate(util_threshold, n):
    return lambda day, hour, money, hires_today, nq, util: n if util >= util_threshold else 0


def hire_fib_cost_cap(max_marginal_cost):
    """Keep hiring today as long as the NEXT hire's fib cost is <= cap.
    fib(0)=1,fib(1)=1,fib(2)=2,fib(3)=3,fib(4)=5,fib(5)=8,fib(6)=13,fib(7)=21."""
    def _fib(n):
        a, b = 1, 1
        for _ in range(n):
            a, b = b, a + b
        return a

    def policy(day, hour, money, hires_today, nq, util):
        n = 0
        while _fib(n) <= max_marginal_cost:
            n += 1
        return n
    return policy


def hire_ramp(start_day, end_day, start_n, end_n):
    def policy(day, hour, money, hires_today, nq, util):
        if day <= start_day:
            return start_n
        if day >= end_day:
            return end_n
        frac = (day - start_day) / (end_day - start_day)
        return round(start_n + frac * (end_n - start_n))
    return policy


def hire_reserve_floor(base_policy, floor):
    """Wrap another hire policy: only hire if money stays >= floor after cost."""
    def policy(day, hour, money, hires_today, nq, util):
        desired = base_policy(day, hour, money, hires_today, nq, util)
        # Rough afford check: don't bother hiring if it would dip under floor
        # (exact per-hire fib cost is handled by the engine's own affordability
        # no-op; this just prevents chasing a target we can't sustain).
        if money - floor < 1:
            return min(desired, hires_today)
        return desired
    return policy


# ------------------------------------------------------------------ land ---

def land_never():
    return lambda day, hour, money, nq, util: False


def land_buy_immediately():
    return lambda day, hour, money, nq, util: True


def land_money_threshold(threshold):
    return lambda day, hour, money, nq, util: money >= threshold


def land_day_threshold(day0):
    return lambda day, hour, money, nq, util: day >= day0


def land_utilization_gate(util_threshold):
    return lambda day, hour, money, nq, util: util >= util_threshold


def land_reserve_floor(base_policy, floor):
    def policy(day, hour, money, nq, util):
        if not base_policy(day, hour, money, nq, util):
            return False
        return money - floor >= 0
    return policy


def next_land_cost(n_quadrants):
    if n_quadrants - 1 >= len(LAND_PRICES):
        return None
    return LAND_PRICES[n_quadrants - 1]
