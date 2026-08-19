# Adaptive Strategy Follower and Watcher Implementation

## Summary

Refactor `strategy_follower.py` into a reversible layered agent:

1. Deadline-safe action planning.
2. Adaptive asset and labor targets.
3. Township-aware production.
4. Opponent-aware production and expansion.
5. A hybrid watcher: deterministic rules first, followed by a compact linear SVM trained from randomized counterfactual simulations.

Preserve the current strategy as an exact legacy path. Do not modify `main.py` until the combined design passes confirmation testing.

## Strategy and Watcher Design

### Reversible feature layers

Add independently configurable top-level flags compatible with `test_gen.py`:

- `ENABLE_DEADLINE_PLANNER`
- `ENABLE_ADAPTIVE_TARGETS`
- `ENABLE_TOWN_WATCHER`
- `ENABLE_OPPONENT_WATCHER`
- `WATCHER_BACKEND = "rules" | "linear_svm"`

All flags off must execute the current strategy unchanged. Each cumulative A/B variant enables exactly one additional layer.

### 1. Deadline-safe action planner

Replace fixed per-hand chunks, when enabled, with a global task board rebuilt every turn:

1. Animals at immediate feed risk.
2. Newly planted or previously missed crops requiring water.
3. Remaining feed and water obligations.
4. Products approaching held-yield or decay limits.
5. Harvest, fertilizer collection, and animal placement.
6. `CARE`.
7. Construction, planting, digging, and optional work.

Assign each task to the nearest qualified unit without duplicate targeting. Include inventory needs and shed travel in the cost. Stable livestock and crop zones remain contiguous to reduce movement.

Before buying or placing another asset, estimate its daily actions and travel overhead. Reject expansion if existing obligations plus a safety margin exceed available unit-turn capacity.

### 2. Adaptive strategy targets

Introduce a runtime target structure containing product tile counts, animal counts, daily hands, quadrants, cash reserve, and replant cutoffs.

The controller must:

- Treat the current 11-cow, 6-sheep, 19-melon, 8-hand, 2-quadrant plan as maximum baseline targets rather than mandatory purchases.
- Hire from estimated daily workload and Fibonacci cost.
- Reserve money for feed and existing obligations before seeds, animals, or land.
- Stop purchases whose expected payback exceeds remaining turns.
- Change crop allocations only when tiles become empty; never dig healthy crops merely because a score changed.
- Retain existing animals but stop buying more when capacity or profitability falls.
- Keep hand roles stable for the remainder of each day.

Generalize execution for wheat, carrot, tomato, strawberry, melon, goose, cow, and sheep. Empty tiles are assigned to the most under-target profitable product; existing tiles retain their lifecycle rules.

### 3–4. Watcher contract

Add a pure function above `agent`:

```python
watcher_signals(obs, backend) -> {
    "product_attractiveness": {product: -1.0..1.0},
    "town_demand_pressure": {product: 0.0..1.0},
    "opponent_supply_pressure": {product: 0.0..1.0},
    "market_glut_risk": {product: 0.0..1.0},
    "competitive_expansion_pressure": -1.0..1.0,
    "recommended_limits": {
        "product_exposure": {product: int},
        "hands": int,
        "quadrants": int,
        "cash_reserve": float,
    },
    "backend": "off" | "rules" | "linear_svm",
}
```

The follower remains authoritative: watcher recommendations are clamped by deadline capacity, cash, payback, land, and endgame constraints.

Deterministic watcher calculations:

- Township demand: count duplicate shop instances and convert each into its exact daily product consumption.
- Opponent supply: forecast visible crop harvests and animal output over the next six days using crop ages, animal counts, and public farm state.
- Glut risk: combine price/base-price ratio, inventory displacement from 10,000 relative to product throughput `T`, and forecast opponent supply.
- Expansion pressure: compare profitable unmet demand and opponent scale against current serviced capacity.
- With opponent signals disabled, opponent pressure must be neutral.
- With town signals disabled, township pressure must be neutral.
- Invalid or non-finite model output falls back to the rules backend.

## Watcher Model and Training Pipeline

### Features

Use aggregated features rather than the raw 10×10 grids:

- Turn, day, hour, remaining-season fraction, and opening/midgame/endgame phase.
- Own and opponent money, hands, quadrants, weeds, structures, animals, crop counts, crop-age/harvest-horizon bins, ready yields, and feed/water risk.
- Own shed, carried inventory, and seeds.
- Duplicate count for every shop class.
- Each product's price divided by base price.
- Market inventory displacement divided by product throughput.
- Capacity backlog, estimated travel, and current asset-service ratio.

Apply `StandardScaler` to unbounded numeric features. Normalize counts by their natural caps. Encode shop, crop, animal, and structure classes as fixed one-hot/count columns. Store the feature order and scaler parameters with a schema version.

### Counterfactual labels

Extend the simulation harness with checkpoint interventions at day starts and shop-unlock days. Paired episodes must use the same seed and player order and follow identical behavior until the checkpoint.

Randomly test one bounded deviation per pair:

- Add, remove, or redirect two future crop slots.
- Add or defer one animal.
- Add or remove one hand.
- Advance or defer the next land purchase.
- Exit or retain a premium product.

Label the deviation positive only when it improves final money without violating safety gates; negative when it reduces money or causes a safety failure; changes within $250 are neutral.

Generate data against `starter`, `strategies_v2.ring`, and `strategies_v2.leader_clone`. Split by seed—not by turn—to prevent states from the same episode leaking across train and test sets. Require at least 150 paired examples per modeled output and at least 40 positive and 40 negative labels, stopping at 2,000 pairs if a class remains unavailable.

### Compact SVM

Use development-only scikit-learn:

- Fit independent `LinearSVC` models for each product's increase/avoid decision and for competitive expansion.
- Keep exact town, opponent-supply, and market-risk signals deterministic.
- Convert decision margins to `[-1, 1]` using training-set margin scales.
- Export feature order, scaler means/scales, coefficients, intercepts, and margin scales as pure-Python constants. Kaggle inference must not import scikit-learn.
- Require held-out balanced accuracy of at least 0.60 and at least 0.10 above the majority baseline before runtime A/B testing.
- If the model fails either offline or gameplay acceptance, retain the rules watcher.

## A/B Testing and Reversibility

Extend the harness without changing existing `run_matches` or `compare_paired` callers. Add detailed paired output containing both players' money, win/loss, raw paired differences, and:

- Feed-risk tile-turns and escaped animals.
- Missed-watering deaths.
- Shed overflow and ending saleable inventory.
- Invalid/no-op purchase indicators and market-order cap violations.
- Work, movement, and idle action shares.
- Land, labor, and asset trajectories.

Test cumulative variants:

1. Legacy baseline.
2. Baseline plus deadline planner.
3. Previous plus adaptive targets.
4. Previous plus rule-based township signals.
5. Previous plus rule-based opponent signals.
6. Previous plus linear-SVM attractiveness and expansion scores.

For every stage:

- Syntax and 100-turn smoke checks.
- Four 120-turn smoke episodes before full-season evaluation.
- Paired screening against `starter`, 20 episodes, alternating player order.
- Confirmation against `starter`, `ring`, and `leader_clone`, at least 30 episodes per opponent.
- If confirmation is inconclusive, expand once to 60 episodes per opponent.

Promotion requires:

- Overall paired-money 95% confidence interval above zero.
- No opponent with a confirmed regression exceeding 1% of baseline money.
- No new animal escapes or order-cap violations.
- Feed/water risk, overflow, and unsold ending value no more than 5% worse than the preceding variant.

If still inconclusive at 60 episodes, revert to the simpler predecessor. After selecting a final combination, run leave-one-layer-out ablations so harmful interactions are visible.

Store every round configuration and summarized result under `ab_rounds`; keep generated `ab_tests` disposable. Preserve the legacy code path until the complete watcher-backed version is confirmed.

## Assumptions

- Final money is the primary optimization target; win rate is reported secondarily.
- `starter` is the required regression baseline, while strong local agents validate opponent awareness.
- Scikit-learn is permitted only for offline training.
- The first usable watcher is the deterministic rules backend; the SVM replaces only the parts supported by counterfactual evidence.
- `main.py` synchronization and Kaggle submission remain out of scope until this editable strategy passes all gates.
