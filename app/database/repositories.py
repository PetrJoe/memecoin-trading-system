from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    BotEvent,
    DailyStats,
    EventLevel,
    ExitReason,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionStatus,
    Signal,
    SignalType,
    Token,
    TokenStatus,
    Trade,
    TradeStatus,
    MarketSnapshotModel,
)


class TokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_address(self, address: str) -> Optional[Token]:
        result = await self.session.execute(select(Token).where(Token.address == address))
        return result.scalar_one_or_none()

    async def get_by_id(self, token_id: int) -> Optional[Token]:
        result = await self.session.execute(select(Token).where(Token.id == token_id))
        return result.scalar_one_or_none()

    async def get_by_status(self, status: TokenStatus) -> list[Token]:
        result = await self.session.execute(select(Token).where(Token.status == status))
        return list(result.scalars().all())

    async def create(
        self,
        address: str,
        symbol: str,
        name: str = "",
        decimals: int = 9,
        status: TokenStatus = TokenStatus.DISCOVERED,
    ) -> Token:
        token = Token(
            address=address,
            symbol=symbol,
            name=name,
            decimals=decimals,
            status=status,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def update_status(self, token_id: int, status: TokenStatus) -> Optional[Token]:
        token = await self.get_by_id(token_id)
        if token:
            token.status = status
            await self.session.flush()
        return token

    async def update_risk_score(self, token_id: int, score: int) -> Optional[Token]:
        token = await self.get_by_id(token_id)
        if token:
            token.risk_score = score
            await self.session.flush()
        return token

    async def upsert(self, address: str, symbol: str, name: str = "", decimals: int = 9) -> Token:
        existing = await self.get_by_address(address)
        if existing:
            return existing
        return await self.create(address=address, symbol=symbol, name=name, decimals=decimals)


class MarketSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token_id: int,
        price: float,
        liquidity: Optional[float] = None,
        volume_5m: Optional[float] = None,
        volume_1h: Optional[float] = None,
        volume_6h: Optional[float] = None,
        volume_24h: Optional[float] = None,
        buys: Optional[int] = None,
        sells: Optional[int] = None,
        market_cap: Optional[float] = None,
    ) -> MarketSnapshotModel:
        snapshot = MarketSnapshotModel(
            token_id=token_id,
            price=price,
            liquidity=liquidity,
            volume_5m=volume_5m,
            volume_1h=volume_1h,
            volume_6h=volume_6h,
            volume_24h=volume_24h,
            buys=buys,
            sells=sells,
            market_cap=market_cap,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def get_latest(self, token_id: int) -> Optional[MarketSnapshotModel]:
        result = await self.session.execute(
            select(MarketSnapshotModel)
            .where(MarketSnapshotModel.token_id == token_id)
            .order_by(MarketSnapshotModel.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_recent(self, token_id: int, limit: int = 10) -> list[MarketSnapshotModel]:
        result = await self.session.execute(
            select(MarketSnapshotModel)
            .where(MarketSnapshotModel.token_id == token_id)
            .order_by(MarketSnapshotModel.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class SignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token_id: int,
        signal: SignalType,
        score: int = 0,
        reasons: Optional[dict] = None,
    ) -> Signal:
        sig = Signal(
            token_id=token_id,
            signal=signal,
            score=score,
            reasons=reasons,
        )
        self.session.add(sig)
        await self.session.flush()
        return sig

    async def get_latest(self, token_id: int) -> Optional[Signal]:
        result = await self.session.execute(
            select(Signal)
            .where(Signal.token_id == token_id)
            .order_by(Signal.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token_id: int,
        side: OrderSide,
        amount: float,
        status: OrderStatus = OrderStatus.PENDING,
        tx_signature: Optional[str] = None,
    ) -> Order:
        order = Order(
            token_id=token_id,
            side=side,
            amount=amount,
            status=status,
            tx_signature=tx_signature,
        )
        self.session.add(order)
        await self.session.flush()
        return order

    async def get_by_id(self, order_id: int) -> Optional[Order]:
        result = await self.session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_by_tx_signature(self, tx_signature: str) -> Optional[Order]:
        result = await self.session.execute(
            select(Order).where(Order.tx_signature == tx_signature)
        )
        return result.scalar_one_or_none()

    async def update_status(self, order_id: int, status: OrderStatus) -> Optional[Order]:
        order = await self.get_by_id(order_id)
        if order:
            order.status = status
            await self.session.flush()
        return order


class TradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        order_id: int,
        token_id: int,
        side: OrderSide,
        quantity: float,
        price: float,
        fees: float = 0.0,
        slippage: float = 0.0,
        pnl: Optional[float] = None,
        tx_signature: Optional[str] = None,
        status: TradeStatus = TradeStatus.PENDING,
    ) -> Trade:
        trade = Trade(
            order_id=order_id,
            token_id=token_id,
            side=side,
            quantity=quantity,
            price=price,
            fees=fees,
            slippage=slippage,
            pnl=pnl,
            tx_signature=tx_signature,
            status=status,
        )
        self.session.add(trade)
        await self.session.flush()
        return trade

    async def get_by_tx_signature(self, tx_signature: str) -> Optional[Trade]:
        result = await self.session.execute(
            select(Trade).where(Trade.tx_signature == tx_signature)
        )
        return result.scalar_one_or_none()

    async def get_today_trades(self) -> list[Trade]:
        today = date.today()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        result = await self.session.execute(
            select(Trade).where(Trade.created_at >= start).order_by(Trade.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_win_loss_count(self) -> tuple[int, int]:
        today = date.today()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        wins = await self.session.execute(
            select(func.count()).select_from(Trade).where(
                and_(Trade.created_at >= start, Trade.pnl > 0)
            )
        )
        losses = await self.session.execute(
            select(func.count()).select_from(Trade).where(
                and_(Trade.created_at >= start, Trade.pnl < 0)
            )
        )
        return wins.scalar_one(), losses.scalar_one()


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token_id: int,
        entry_price: float,
        quantity: float,
        capital: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop: Optional[float] = None,
    ) -> Position:
        position = Position(
            token_id=token_id,
            entry_price=entry_price,
            quantity=quantity,
            capital=capital,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=trailing_stop,
            status=PositionStatus.OPEN,
        )
        self.session.add(position)
        await self.session.flush()
        return position

    async def get_by_id(self, position_id: int) -> Optional[Position]:
        result = await self.session.execute(select(Position).where(Position.id == position_id))
        return result.scalar_one_or_none()

    async def get_open_positions(self) -> list[Position]:
        result = await self.session.execute(
            select(Position)
            .where(Position.status == PositionStatus.OPEN)
            .order_by(Position.opened_at.desc())
        )
        return list(result.scalars().all())

    async def get_open_by_token(self, token_id: int) -> Optional[Position]:
        result = await self.session.execute(
            select(Position).where(
                and_(Position.token_id == token_id, Position.status == PositionStatus.OPEN)
            )
        )
        return result.scalar_one_or_none()

    async def close_position(
        self,
        position_id: int,
        exit_reason: ExitReason,
        realized_pnl: float,
    ) -> Optional[Position]:
        position = await self.get_by_id(position_id)
        if position:
            position.status = PositionStatus.CLOSED
            position.exit_reason = exit_reason
            position.realized_pnl = realized_pnl
            position.closed_at = datetime.now(timezone.utc)
            await self.session.flush()
        return position

    async def count_open(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Position).where(
                Position.status == PositionStatus.OPEN
            )
        )
        return result.scalar_one()

    async def get_total_exposure(self) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Position.capital), 0.0)).where(
                Position.status == PositionStatus.OPEN
            )
        )
        return result.scalar_one()


class BotEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        level: EventLevel,
        event_type: str,
        message: str,
        extra_data: Optional[dict] = None,
    ) -> BotEvent:
        event = BotEvent(
            level=level,
            event_type=event_type,
            message=message,
            extra_data=extra_data,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_recent(self, limit: int = 50) -> list[BotEvent]:
        result = await self.session.execute(
            select(BotEvent).order_by(BotEvent.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


class DailyStatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_today(self) -> DailyStats:
        today = date.today()
        result = await self.session.execute(
            select(DailyStats).where(DailyStats.date == today)
        )
        stats = result.scalar_one_or_none()
        if not stats:
            stats = DailyStats(date=today)
            self.session.add(stats)
            await self.session.flush()
        return stats

    async def update(self, stats: DailyStats) -> None:
        await self.session.flush()
