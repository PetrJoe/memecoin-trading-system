from __future__ import annotations

import enum
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


class TokenStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    WATCHING = "WATCHING"
    ANALYZING = "ANALYZING"
    APPROVED = "APPROVED"
    TRADED = "TRADED"
    REJECTED = "REJECTED"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TradeStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, enum.Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_LIMIT = "TIME_LIMIT"
    EMERGENCY = "EMERGENCY"
    MANUAL = "MANUAL"
    RISK_EVENT = "RISK_EVENT"


class SignalType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"
    REJECT = "REJECT"


class EventLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus), nullable=False, default=TokenStatus.DISCOVERED
    )
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    pairs: Mapped[list["Pair"]] = relationship("Pair", back_populates="token", lazy="selectin")
    snapshots: Mapped[list["MarketSnapshotModel"]] = relationship(
        "MarketSnapshotModel", back_populates="token", lazy="noload"
    )
    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="token", lazy="noload")
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="token", lazy="noload")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="token", lazy="noload")
    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="token", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Token {self.symbol} ({self.address[:8]}...)>"


class Pair(Base):
    __tablename__ = "pairs"
    __table_args__ = (
        UniqueConstraint("address", name="uq_pair_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(64), nullable=False)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    dex: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    token: Mapped["Token"] = relationship("Token", back_populates="pairs")

    __table_args__ = (
        UniqueConstraint("address", name="uq_pair_address"),
        Index("ix_pairs_token_id", "token_id"),
    )


class MarketSnapshotModel(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_5m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_6h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buys: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sells: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    token: Mapped["Token"] = relationship("Token", back_populates="snapshots")

    __table_args__ = (
        Index("ix_market_snapshots_token_id", "token_id"),
        Index("ix_market_snapshots_timestamp", "timestamp"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    signal: Mapped[SignalType] = mapped_column(Enum(SignalType), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasons: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    token: Mapped["Token"] = relationship("Token", back_populates="signals")

    __table_args__ = (Index("ix_signals_token_id", "token_id"),)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), nullable=False, default=OrderStatus.PENDING
    )
    tx_signature: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    token: Mapped["Token"] = relationship("Token", back_populates="orders")
    trade: Mapped[Optional["Trade"]] = relationship("Trade", back_populates="order", uselist=False)

    __table_args__ = (
        Index("ix_orders_token_id", "token_id"),
        Index("ix_orders_status", "status"),
    )


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("tx_signature", name="uq_trade_tx_signature"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), nullable=False)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tx_signature: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus), nullable=False, default=TradeStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship("Order", back_populates="trade")
    token: Mapped["Token"] = relationship("Token", back_populates="trades")

    __table_args__ = (
        Index("ix_trades_token_id", "token_id"),
        Index("ix_trades_order_id", "order_id"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(Integer, ForeignKey("tokens.id"), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    capital: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus), nullable=False, default=PositionStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[Optional[ExitReason]] = mapped_column(Enum(ExitReason), nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    token: Mapped["Token"] = relationship("Token", back_populates="positions")

    __table_args__ = (
        Index("ix_positions_token_id", "token_id"),
        Index("ix_positions_status", "status"),
    )


class BotEvent(Base):
    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[EventLevel] = mapped_column(Enum(EventLevel), nullable=False, default=EventLevel.INFO)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_bot_events_created_at", "created_at"),)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    date: Mapped[date] = mapped_column(primary_key=True)
    starting_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ending_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
