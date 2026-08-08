"""Every labor/land configuration under test, built from the policy builders
in policies.py. Each entry: (name, hire_policy, land_policy, allocation).

Groups:
  A - hiring cadence in isolation (land fixed at NW-only, L_never)      -> 27
  B - land timing in isolation (no hands, H_never)                     -> 10 (L_never dup with A skipped)
  C - curated hire+land interaction / reinvestment-schedule archetypes -> 20
  E - extremes / edge cases                                            -> 8
  (allocation-mode supplement is added later in sweep.py on top of the
  screening winners, not baked in here)
"""

import policies as P

HIRE = {
    "never": P.hire_never(),
    "flat1": P.hire_flat(1),
    "flat2": P.hire_flat(2),
    "flat3": P.hire_flat(3),
    "flat4": P.hire_flat(4),
    "flat5": P.hire_flat(5),
    "flat6": P.hire_flat(6),
    "flat8": P.hire_flat(8),
    "money1k_1": P.hire_money_gate(1000, 1),
    "money2k_2": P.hire_money_gate(2000, 2),
    "money5k_3": P.hire_money_gate(5000, 3),
    "money10k_5": P.hire_money_gate(10000, 5),
    "day0_2": P.hire_day_gate(0, 2),
    "day3_1": P.hire_day_gate(3, 1),
    "day5_2": P.hire_day_gate(5, 2),
    "day10_3": P.hire_day_gate(10, 3),
    "scaleland1": P.hire_scale_with_land(1),
    "scaleland2": P.hire_scale_with_land(2),
    "util60_1": P.hire_utilization_gate(0.6, 1),
    "util80_1": P.hire_utilization_gate(0.8, 1),
    "util80_2": P.hire_utilization_gate(0.8, 2),
    "util90_2": P.hire_utilization_gate(0.9, 2),
    "fibcap1": P.hire_fib_cost_cap(1),    # up to 2 hands/day (cost 1,1)
    "fibcap3": P.hire_fib_cost_cap(3),    # up to 4 hands/day (cost 1,1,2,3)
    "fibcap5": P.hire_fib_cost_cap(5),    # up to 5 hands/day
    "fibcap13": P.hire_fib_cost_cap(13),  # up to 7 hands/day
    "fibcap21": P.hire_fib_cost_cap(21),  # up to 8 hands/day
    "ramp_0_10_0_6": P.hire_ramp(0, 10, 0, 6),
    "ramp_5_20_1_8": P.hire_ramp(5, 20, 1, 8),
}

LAND = {
    "never": P.land_never(),
    "immediate": P.land_buy_immediately(),
    "money1500": P.land_money_threshold(1500),
    "money3000": P.land_money_threshold(3000),
    "money6000": P.land_money_threshold(6000),
    "day3": P.land_day_threshold(3),
    "day7": P.land_day_threshold(7),
    "day14": P.land_day_threshold(14),
    "util60": P.land_utilization_gate(0.6),
    "util80": P.land_utilization_gate(0.8),
    "util90": P.land_utilization_gate(0.9),
}

CONFIGS = []


def _add(name, hire_key, land_key, allocation="stripe"):
    CONFIGS.append({"name": name, "hire": hire_key, "land": land_key, "allocation": allocation,
                     "hire_fn": HIRE[hire_key], "land_fn": LAND[land_key]})


# --- Group A: hiring cadence in isolation, land fixed at NW only ---
for hk in HIRE:
    _add(f"A_hire_{hk}_noland", hk, "never")

# --- Group B: land timing in isolation, no hired hands ---
for lk in LAND:
    if lk == "never":
        continue  # duplicate of A_hire_never_noland
    _add(f"B_land_{lk}_solo", "never", lk)

# --- Group C: curated hire+land interaction / reinvestment archetypes ---
_add("C_aggressive_rush", "flat6", "immediate")
_add("C_conservative_gated", "money5k_3", "money6000")
_add("C_scaleland1_util80", "scaleland1", "util80")
_add("C_scaleland2_util60", "scaleland2", "util60")
_add("C_hire_first_then_land", "day0_2", "day7")
_add("C_land_first_then_hire", "day10_3", "immediate")
_add("C_utilization_driven_both", "util80_1", "util80")
_add("C_fibcap3_money3000", "fibcap3", "money3000")
_add("C_fibcap5_money6000", "fibcap5", "money6000")
_add("C_flat1_immediate", "flat1", "immediate")
_add("C_flat2_util90", "flat2", "util90")
_add("C_money_gate_synced_low", "money2k_2", "money1500")
_add("C_money_gate_synced_high", "money10k_5", "money6000")
_add("C_ramp_early_land5", "ramp_0_10_0_6", "day3")
_add("C_ramp_late_land10", "ramp_5_20_1_8", "day14")
_add("C_scaleland1_immediate", "scaleland1", "immediate")
_add("C_scaleland2_immediate", "scaleland2", "immediate")
_add("C_flat3_money3000", "flat3", "money3000")
_add("C_flat4_util80", "flat4", "util80")
_add("C_fibcap13_util80", "fibcap13", "util80")

# --- Group C (reserve-floor variants; wrap two archetypes with a cash floor) ---
_add_reserve = []
CONFIGS.append({
    "name": "C_reserve_floor_conservative",
    "hire": "flat3_reserve1000", "land": "money3000_reserve1000", "allocation": "stripe",
    "hire_fn": P.hire_reserve_floor(HIRE["flat3"], 1000),
    "land_fn": P.land_reserve_floor(LAND["money3000"], 1000),
})
CONFIGS.append({
    "name": "C_reserve_floor_aggressive",
    "hire": "flat6_reserve200", "land": "immediate_reserve200", "allocation": "stripe",
    "hire_fn": P.hire_reserve_floor(HIRE["flat6"], 200),
    "land_fn": P.land_reserve_floor(LAND["immediate"], 200),
})

# --- Group E: extremes / edge cases ---
_add("E_flat8_noland_crowding", "flat8", "never")
_add("E_fibcap21_immediate", "fibcap21", "immediate")
_add("E_money1k1_noland", "money1k_1", "never")
_add("E_util80_1_noland", "util80_1", "never")
_add("E_flat4_land_day14", "flat4", "day14")
_add("E_flat2_land_day3", "flat2", "day3")
_add("E_never_land_util90_solo", "never", "util90")
_add("E_flat1_land_never", "flat1", "never")


def get(name):
    for c in CONFIGS:
        if c["name"] == name:
            return c
    raise KeyError(name)


if __name__ == "__main__":
    print(f"{len(CONFIGS)} configs defined")
    for c in CONFIGS:
        print(c["name"], c["hire"], c["land"], c["allocation"])
