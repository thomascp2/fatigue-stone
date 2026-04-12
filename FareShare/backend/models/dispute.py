from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone
import enum


class Base(DeclarativeBase):
    pass


class DisputeStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    FLAGGED = "flagged"          # over-assessment confirmed
    NOT_FLAGGED = "not_flagged"  # assessment looks fair
    LETTER_DRAFTED = "letter_drafted"
    LETTER_SENT = "letter_sent"
    PENDING_DECISION = "pending_decision"
    RESOLVED_WIN = "resolved_win"
    RESOLVED_LOSS = "resolved_loss"


class Dispute(Base):
    __tablename__ = "disputes"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Client info
    client_name = Column(String(255))
    client_phone = Column(String(20))
    client_email = Column(String(255))

    # Parcel data (extracted by Claude)
    parcel_id = Column(String(100))
    county = Column(String(100))
    property_class = Column(String(100))  # residential, agricultural, etc.
    acreage = Column(Float)
    assessed_value = Column(Float)
    appraised_value = Column(Float)
    tax_year = Column(Integer)
    property_address = Column(String(500))

    # Comp analysis
    median_comp_value = Column(Float)
    comp_count = Column(Integer)
    overassessment_pct = Column(Float)   # % above median comp
    is_flagged = Column(Integer, default=0)  # 1 if >15% over comp

    # Dispute outcome
    status = Column(String(50), default=DisputeStatus.UPLOADED)
    amount_saved = Column(Float)
    fee_collected = Column(Float)

    # File paths
    source_file_path = Column(String(500))
    report_path = Column(String(500))
    letter_path = Column(String(500))

    # Raw extraction JSON from Claude
    extraction_raw = Column(Text)
    intake_channel = Column(String(50), default="web")  # web | sms


class Comp(Base):
    """Comparable sales used in a dispute analysis."""
    __tablename__ = "comps"

    id = Column(Integer, primary_key=True, index=True)
    dispute_id = Column(Integer, index=True)
    parcel_id = Column(String(100))
    address = Column(String(500))
    sale_price = Column(Float)
    sale_date = Column(String(20))
    acreage = Column(Float)
    price_per_acre = Column(Float)
    distance_miles = Column(Float)
    data_source = Column(String(100))  # alabama_gis | attom
