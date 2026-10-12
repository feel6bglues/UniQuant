"""
UniQuant Brain Factors Base Class
==================================
Abstract Base Class for all standard quantitative and forensic factors.
"""

from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class BaseFactor(ABC):
    """
    Abstract Base Class for UniQuant Factors.
    Subclasses implement compute(df) and can self-register into FactorRegistry.
    """
    name: str = ""
    category: str = "custom"
    default_weight: float = 1.0
    description: str = ""

    def __init__(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        default_weight: Optional[float] = None,
        description: Optional[str] = None,
    ):
        if name:
            self.name = name
        if category:
            self.category = category
        if default_weight is not None:
            self.default_weight = default_weight
        if description:
            self.description = description

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute factor values on the input DataFrame.
        Returns a pd.Series aligned with df.index.
        """
        pass

    def __call__(self, df: pd.DataFrame) -> pd.Series:
        return self.compute(df)

    def register(self) -> None:
        """Register factor into FactorRegistry."""
        from .registry import FactorRegistry
        FactorRegistry.register(
            name=self.name,
            compute_func=self.compute,
            category=self.category,
            default_weight=self.default_weight,
            description=self.description,
        )
