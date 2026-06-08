"""Pure regression-testing domain: assertion evaluation + fixture bundle."""

from tracely.domain.regression.contract import evaluate_assertions, evaluate_case
from tracely.domain.regression.fixtures import FixtureBundle, FixtureCall

__all__ = ["evaluate_assertions", "evaluate_case", "FixtureBundle", "FixtureCall"]
