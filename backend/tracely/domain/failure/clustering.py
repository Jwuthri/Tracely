"""Embedding clustering: pick UMAP-then-HDBSCAN vs direct cosine HDBSCAN by `n`.

For small/moderate sets we cluster directly on cosine distance — robust to duplicates and few
points. For large, diverse sets we UMAP-denoise first (HDBSCAN degrades in raw high-dim space).
UMAP is deliberately NOT used on small n: it is a manifold learner that, given few or
near-identical vectors, scatters them and HDBSCAN then finds phantom clusters.
"""

from __future__ import annotations

from tracely.config import settings


class ClusterEngine:
    """Pure-ish encapsulation of the cluster regime selection. The heavy libs (numpy, hdbscan,
    umap, sklearn) are lazy-imported so workers/API start without them.

    `min_cluster_size` and `umap_min_n` default to the project settings but can be overridden in
    tests.
    """

    def __init__(
        self,
        min_cluster_size: int | None = None,
        umap_min_n: int | None = None,
    ) -> None:
        self.min_cluster_size = (
            min_cluster_size if min_cluster_size is not None else settings.fi_min_cluster_size
        )
        self.umap_min_n = umap_min_n if umap_min_n is not None else settings.fi_umap_min_n

    def labels_for(self, matrix) -> list[int]:
        """Return one cluster label per row. Label `-1` is HDBSCAN noise (caller should drop)."""
        import numpy as np

        X = np.asarray(matrix, dtype="float64")
        n = len(X)
        if n < 4:
            return [0] * n  # too few to cluster meaningfully -> one group

        import hdbscan

        if n < self.umap_min_n:
            from sklearn.metrics.pairwise import cosine_distances

            d = cosine_distances(X).astype("float64")
            labels = hdbscan.HDBSCAN(
                min_cluster_size=self.min_cluster_size,
                min_samples=1,
                metric="precomputed",
            ).fit_predict(d)
            return [int(x) for x in labels]

        import umap

        reducer = umap.UMAP(
            n_neighbors=min(15, n - 1),
            n_components=min(5, n - 1),
            metric="cosine",
            random_state=42,
        )
        reduced = reducer.fit_transform(X.astype("float32"))
        labels = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size, min_samples=1
        ).fit_predict(reduced)
        return [int(x) for x in labels]
