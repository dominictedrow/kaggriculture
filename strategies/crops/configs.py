"""Config generation for the crop-strategy sweep. Two phases:

Phase 1: crop_mix x max_tiles grid, everything else at sane defaults
         (land=never, fertilize=never, harvest_at=first, sell=dump, hire=0).
Phase 2: for the top Phase-1 survivors, vary one dimension at a time
         (harvest timing, fertilizing, land expansion x hiring, sell batching).
"""

CROP_MIXES = {
    "wheat-mono":    [("WHEAT", 1)],
    "carrot-mono":   [("CARROT", 1)],
    "melon-mono":    [("MELON", 1)],
    "wheat-carrot-11": [("WHEAT", 1), ("CARROT", 1)],
    "wheat-carrot-21": [("WHEAT", 2), ("CARROT", 1)],
    "wheat-melon-11":  [("WHEAT", 1), ("MELON", 1)],
    "carrot-melon-11": [("CARROT", 1), ("MELON", 1)],
    "wheat-carrot-melon-111": [("WHEAT", 1), ("CARROT", 1), ("MELON", 1)],
}

DENSITIES = [4, 8, 12, 16, 20, 25]

DEFAULTS = dict(harvest_at="first", fertilize="never", land="never", sell="dump", hire=0)


def name_of(mix_name, **overrides):
    parts = [mix_name]
    d = dict(DEFAULTS, **overrides)
    parts.append(f"mt{d['max_tiles']}")
    if d["harvest_at"] != "first":
        parts.append("harvestmax")
    if d["fertilize"] != "never":
        parts.append("fert" + d["fertilize"])
    if d["land"] != "never":
        landtag = d["land"] if isinstance(d["land"], str) else "d" + "-".join(map(str, d["land"]))
        parts.append("land" + landtag)
    if d["sell"] != "dump":
        parts.append("sell" + str(d["sell"]))
    if d["hire"]:
        parts.append(f"hire{d['hire']}")
    return "_".join(parts)


def phase1_configs():
    configs = {}
    for mix_name, mix in CROP_MIXES.items():
        for mt in DENSITIES:
            cfg = dict(DEFAULTS, crop_mix=mix, max_tiles=mt)
            configs[name_of(mix_name, max_tiles=mt)] = cfg
    return configs


def phase2_configs(top_survivors):
    """top_survivors: list of (mix_name, mix, max_tiles) tuples."""
    configs = {}
    for mix_name, mix, mt in top_survivors:
        base = dict(DEFAULTS, crop_mix=mix, max_tiles=mt)

        # Harvest timing
        cfg = dict(base, harvest_at="max")
        configs[name_of(mix_name, max_tiles=mt, harvest_at="max")] = cfg

        # Fertilizing (skip pure melon-mono -- melon caps out unfertilized already).
        # Must pair with harvest_at="max": for wheat/carrot the fertilize bonus
        # window starts exactly at first_yield_day, so harvest_at="first" would
        # harvest the plant before any FERTILIZE action ever lands, and bought
        # fertilizer would just pile up unused.
        if mix_name != "melon-mono":
            cfg = dict(base, fertilize="bonus", harvest_at="max")
            configs[name_of(mix_name, max_tiles=mt, fertilize="bonus", harvest_at="max")] = cfg

        # Land expansion x hiring
        for land_val in ["asap", [10], [8, 15, 20]]:
            for hire in [0, 1]:
                # Give expanded land room to be used.
                mt_expanded = max(mt, 50)
                cfg = dict(base, max_tiles=mt_expanded, land=land_val, hire=hire)
                configs[name_of(mix_name, max_tiles=mt_expanded, land=land_val, hire=hire)] = cfg

        # Sell batching
        cfg = dict(base, sell=("batch", 20))
        configs[name_of(mix_name, max_tiles=mt, sell=("batch", 20))] = cfg

    return configs
