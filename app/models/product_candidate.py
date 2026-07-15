from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base


class ProductCandidate(Base):
    __tablename__ = "product_candidates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    asin: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(500),
    )

    category: Mapped[str] = mapped_column(
        String(100),
        default="未分類",
    )

    original_price: Mapped[int] = mapped_column(
        Integer,
    )

    current_price: Mapped[int] = mapped_column(
        Integer,
    )

    discount_rate: Mapped[int] = mapped_column(
        Integer,
    )

    rating: Mapped[float] = mapped_column(
        Float,
        default=0,
    )

    review_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    is_prime: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    product_url: Mapped[str] = mapped_column(
        String(1000),
        default="",
    )

    affiliate_url: Mapped[str] = mapped_column(
        String(1000),
        default="",
    )

    score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        index=True,
    )

    score_label: Mapped[str] = mapped_column(
        String(30),
        default="未採点",
    )

    score_reason: Mapped[str] = mapped_column(
        String(1000),
        default="",
    )

    draft_text: Mapped[str] = mapped_column(
        Text,
        default="",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )

    filter_reason: Mapped[str] = mapped_column(
        String(500),
        default="",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )