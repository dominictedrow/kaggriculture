# Local data

Generated datasets and imported replay artifacts belong in this directory and
are intentionally excluded from Git. Keep only this README under version
control.

Current local counterfactual artifacts use these paths:

- `data/counterfactual_dataset.jsonl`
- `data/counterfactual_dataset.jsonl.summary.json`
- `data/counterfactual_smoke.jsonl`
- `data/counterfactual_smoke.jsonl.summary.json`

The large Kaggle replay cache remains under `kaggle_replays/` because the
acquisition and analysis scripts already use that layout. It is also ignored.
