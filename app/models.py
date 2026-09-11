import datetime as dt
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Meter(Base):
    __tablename__ = 'meters'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    feeder: Mapped[str] = mapped_column(String(40))
    transformer: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default='shop')
    nominal_v: Mapped[float] = mapped_column(Float, default=230.0)
    baseline_kwh_h: Mapped[float] = mapped_column(Float, default=0.35)
    token: Mapped[str] = mapped_column(String(48))
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Reading(Base):
    __tablename__ = 'readings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meter_id: Mapped[str] = mapped_column(ForeignKey('meters.id'), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    voltage: Mapped[float] = mapped_column(Float)
    current: Mapped[float] = mapped_column(Float)
    kw: Mapped[float] = mapped_column(Float)
    kwh_export: Mapped[float] = mapped_column(Float, default=0.0)
    reverse_events: Mapped[int] = mapped_column(Integer, default=0)
    phases: Mapped[str] = mapped_column(Text, default='[]')

class Alert(Base):
    __tablename__ = 'alerts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(12))
    meter_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scope: Mapped[str] = mapped_column(String(40), default='meter')
    title: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[str] = mapped_column(Text, default='{}')
    status: Mapped[str] = mapped_column(String(12), default='open')
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class Scenario(Base):
    __tablename__ = 'scenarios'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40))
    meter_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    feeder: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    ttl_s: Mapped[int] = mapped_column(Integer, default=240)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
