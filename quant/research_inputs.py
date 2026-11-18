from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class BacktestIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_config = ConfigDict(extra='forbid')
    source: Literal['experiment'] = 'experiment'
    experiment_id: str = Field(min_length=1)
    run_id: Optional[str] = None
    strategy: Literal['long_flat', 'long_short', 'return_band', 'structure_confirmation'] = 'long_flat'
    short_threshold: Optional[float] = Field(default=None, ge=-1, le=1)
    threshold: Optional[float] = Field(default=None, ge=-1, le=1)
    initial_cash: Optional[float] = Field(default=None, gt=0, le=1e12)
    fee_bps: Optional[float] = Field(default=None, ge=0, le=1000)
    slippage_bps: Optional[float] = Field(default=None, ge=0, le=1000)
    position_pct: Optional[float] = Field(default=None, gt=0, le=1)
    stop_loss_pct: Optional[float] = Field(default=None, ge=0, le=.9)
    take_profit_pct: Optional[float] = Field(default=None, ge=0, le=10)
    max_hold_bars: Optional[int] = Field(default=None, ge=0, le=1000)


class MarketRange(BaseModel):
    symbol: str
    period: str
    start: str
    end: str
    audit: bool = True


class TriggerIn(BaseModel):
    kind: str
    rule_id: Optional[str] = None


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dataset_id: Optional[str] = None
    market_range: Optional[MarketRange] = None
    source_experiment_id: Optional[str] = None
    factor_ids: List[str] = Field(default_factory=list, max_length=30)
    factor_set_id: Optional[str] = None
    target_id: str
    target_version: Optional[int] = Field(default=None, ge=1)
    target_params: Dict[str, Any] = Field(default_factory=dict)
    model: str
    sample_mode: str = 'bar'
    trigger: Optional[TriggerIn] = None
    event_types: Optional[List[str]] = Field(default=None, max_length=4)
    model_params: Dict[str, Any] = Field(default_factory=dict)
    lookback: int = Field(default=30, ge=3, le=120)
    epochs: int = Field(default=10, ge=1, le=100)
    submission_key: Optional[str] = Field(default=None, max_length=128)
    auto_backtest: bool = True
    diagnostic_runs: int = Field(default=1, ge=1, le=3)
    cost_bps: float = Field(default=5, ge=0, le=100)
    entry_threshold: float = Field(default=0, ge=0, le=.5)
    probability_threshold: float = Field(default=.55, ge=0, le=1)
