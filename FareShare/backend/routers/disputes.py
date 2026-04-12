"""
Dispute API routes.

POST /disputes/upload  — upload assessment notice (PDF or image), kick off analysis
GET  /disputes/{id}    — get dispute status and report link
GET  /disputes/        — list all disputes (admin)
POST /disputes/{id}/status — update status (admin)
"""

import json
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Dispute, DisputeStatus
from services import extract_assessment, analyze_assessment, generate_report

router = APIRouter(prefix="/disputes", tags=["disputes"])

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _save_upload(upload: UploadFile, dispute_id: int) -> str:
    settings.ensure_dirs()
    suffix = Path(upload.filename).suffix.lower()
    filename = f"dispute_{dispute_id}{suffix}"
    dest = os.path.join(settings.upload_dir, filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@router.post("/upload")
async def upload_assessment(
    file: UploadFile = File(...),
    client_name: str = Form(default=""),
    client_phone: str = Form(default=""),
    client_email: str = Form(default=""),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Accepted: PDF, JPG, PNG.")

    # Create dispute record immediately so we have an ID for file naming
    dispute = Dispute(
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        status=DisputeStatus.ANALYZING,
        intake_channel="web",
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)

    # Save file
    file_path = _save_upload(file, dispute.id)
    dispute.source_file_path = file_path
    db.commit()

    try:
        # Step 1: Extract parcel data via Claude Vision
        extraction = extract_assessment(file_path)
        dispute.extraction_raw = json.dumps(extraction)

        # Map extraction fields to dispute record
        dispute.parcel_id = extraction.get("parcel_id")
        dispute.county = extraction.get("county")
        dispute.property_class = extraction.get("property_class")
        dispute.acreage = extraction.get("acreage")
        dispute.appraised_value = extraction.get("appraised_value")
        dispute.assessed_value = extraction.get("assessed_value")
        dispute.tax_year = extraction.get("tax_year")
        dispute.property_address = extraction.get("property_address")
        db.commit()

        # Step 2: Comp analysis
        if not dispute.assessed_value:
            raise ValueError("Could not extract assessed value from document.")

        analysis = analyze_assessment(
            assessed_value=dispute.assessed_value,
            appraised_value=dispute.appraised_value,
            county=dispute.county or "",
            parcel_id=dispute.parcel_id or "",
            acreage=dispute.acreage,
            property_class=dispute.property_class,
        )

        dispute.median_comp_value = analysis.get("median_comp_appraised")
        dispute.comp_count = analysis.get("comp_count", 0)
        dispute.overassessment_pct = analysis.get("overassessment_pct")
        dispute.is_flagged = 1 if analysis.get("is_flagged") else 0
        dispute.status = DisputeStatus.FLAGGED if analysis.get("is_flagged") else DisputeStatus.NOT_FLAGGED
        db.commit()

        # Step 3: Generate dispute report
        report = generate_report(dispute.id, extraction, analysis)
        dispute.report_path = report["pdf_path"]
        db.commit()

    except Exception as exc:
        dispute.status = DisputeStatus.UPLOADED  # reset — analysis failed
        db.commit()
        raise HTTPException(500, f"Analysis failed: {exc}")

    return {
        "dispute_id": dispute.id,
        "status": dispute.status,
        "is_flagged": bool(dispute.is_flagged),
        "overassessment_pct": dispute.overassessment_pct,
        "report_id": f"FS-{dispute.id:05d}",
        "report_pdf": dispute.report_path,
        "summary": analysis.get("summary", ""),
        "parcel_id": dispute.parcel_id,
        "county": dispute.county,
        "assessed_value": dispute.assessed_value,
        "comp_count": dispute.comp_count,
    }


@router.get("/{dispute_id}")
def get_dispute(dispute_id: int, db: Session = Depends(get_db)):
    dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(404, "Dispute not found.")
    return {
        "id": dispute.id,
        "status": dispute.status,
        "client_name": dispute.client_name,
        "parcel_id": dispute.parcel_id,
        "county": dispute.county,
        "assessed_value": dispute.assessed_value,
        "appraised_value": dispute.appraised_value,
        "median_comp_value": dispute.median_comp_value,
        "overassessment_pct": dispute.overassessment_pct,
        "is_flagged": bool(dispute.is_flagged),
        "report_path": dispute.report_path,
        "created_at": dispute.created_at.isoformat() if dispute.created_at else None,
    }


@router.get("/")
def list_disputes(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    disputes = db.query(Dispute).order_by(Dispute.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": d.id,
            "status": d.status,
            "client_name": d.client_name,
            "county": d.county,
            "assessed_value": d.assessed_value,
            "is_flagged": bool(d.is_flagged),
            "overassessment_pct": d.overassessment_pct,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in disputes
    ]


@router.patch("/{dispute_id}/status")
def update_status(
    dispute_id: int,
    status: DisputeStatus,
    amount_saved: float = None,
    db: Session = Depends(get_db),
):
    dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(404, "Dispute not found.")
    dispute.status = status
    if amount_saved is not None:
        dispute.amount_saved = amount_saved
        dispute.fee_collected = amount_saved * 0.22  # 22% success fee midpoint
    db.commit()
    return {"id": dispute_id, "status": status, "amount_saved": amount_saved}
