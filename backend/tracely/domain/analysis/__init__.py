"""Cross-metric meta-analysis: deterministic statistics over evaluator scores.

`statistics.py` is the Python (non-LLM) half of the "Analyze" feature — Spearman correlations
between metric pairs and z-score outlier detection. These are computed up front and merged into
the LLM synthesis so the numbers are stable regardless of what the model writes.
"""
