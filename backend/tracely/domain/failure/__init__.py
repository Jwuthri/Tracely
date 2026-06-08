"""Pure failure-domain logic: signature, embedding text, cluster engine, histogram."""

from tracely.domain.failure.clustering import ClusterEngine
from tracely.domain.failure.histogram import histogram
from tracely.domain.failure.signature import FailureSignature, mask
from tracely.domain.failure.text import embedding_text, summarize_failure

__all__ = [
    "ClusterEngine",
    "FailureSignature",
    "embedding_text",
    "histogram",
    "mask",
    "summarize_failure",
]
