"""Scanner REST endpoints for uploads, crawling, drafts, and exports."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from agent_service.api.rest.deps import _require_scanner_service
from agent_service.schemas.scanner import (
    ScannerBatchExportRequest,
    ScannerCancelRequest,
    ScannerDraftUpdate,
    ScannerListOut,
    ScannerOut,
    ScannerSaveRequest,
    ScannerSourceUpdate,
    ScannerUrlCreate,
    ScannerVariant,
)

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.post("/files", response_model=ScannerOut)
async def create_file_scan(
    user_id: str = Form(...),
    ocr_enabled: bool = Form(True),
    source_kind: str = Form("file"),
    file: UploadFile = File(...),
) -> ScannerOut:
    """Create a scanner task from one uploaded file or bundled example."""

    content = await file.read()
    try:
        return await run_in_threadpool(
            _require_scanner_service().create_file,
            user_id=user_id,
            filename=file.filename or "upload",
            content=content,
            ocr_enabled=ocr_enabled,
            source_kind=source_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/urls", response_model=ScannerOut)
async def create_url_scan(payload: ScannerUrlCreate) -> ScannerOut:
    """Create a scanner task from one public webpage URL."""

    try:
        return await run_in_threadpool(
            _require_scanner_service().create_url,
            user_id=payload.user_id,
            url=str(payload.url),
            ocr_enabled=payload.ocr_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=ScannerListOut)
async def list_scans(user_id: str = Query(..., min_length=1)) -> ScannerListOut:
    """List scanner history for the user's active knowledge library."""

    try:
        service = _require_scanner_service()
        scans = await run_in_threadpool(service.list_scans, user_id=user_id)
        return ScannerListOut(scans=scans, max_concurrency=service.max_concurrency)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{scan_id}", response_model=ScannerOut)
async def get_scan(scan_id: str, user_id: str = Query(..., min_length=1)) -> ScannerOut:
    """Return one scanner record and its editable drafts."""

    try:
        return await run_in_threadpool(_require_scanner_service().get_scan, user_id=user_id, scan_id=scan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{scan_id}/draft", response_model=ScannerOut)
async def update_scan_draft(scan_id: str, payload: ScannerDraftUpdate) -> ScannerOut:
    """Persist one OCR or no-OCR Markdown draft."""

    try:
        return await run_in_threadpool(
            _require_scanner_service().update_draft,
            user_id=payload.user_id,
            scan_id=scan_id,
            variant=payload.variant,
            content=payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{scan_id}/source", response_model=ScannerOut)
async def update_scan_source(scan_id: str, payload: ScannerSourceUpdate) -> ScannerOut:
    """Persist editable UTF-8 text in the managed original copy."""

    try:
        return await run_in_threadpool(
            _require_scanner_service().update_source_text,
            user_id=payload.user_id,
            scan_id=scan_id,
            content=payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{scan_id}/cancel", response_model=ScannerOut)
async def cancel_scan(scan_id: str, payload: ScannerCancelRequest) -> ScannerOut:
    """Immediately terminate one isolated scanner worker process."""

    try:
        return await run_in_threadpool(
            _require_scanner_service().cancel,
            user_id=payload.user_id,
            scan_id=scan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{scan_id}/save")
async def save_scan_to_knowledge(scan_id: str, payload: ScannerSaveRequest) -> dict:
    """Save a scanner projection into the active knowledge root."""

    try:
        return await run_in_threadpool(
            _require_scanner_service().save_to_knowledge,
            user_id=payload.user_id,
            scan_id=scan_id,
            variant=payload.variant,
            conflict_strategy=payload.conflict_strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{scan_id}/export")
async def export_scan(
    scan_id: str,
    user_id: str = Query(..., min_length=1),
    variant: ScannerVariant = Query(...),
) -> Response:
    """Return a Markdown or ZIP payload for the desktop save dialog."""

    try:
        filename, media_type, content = await run_in_threadpool(
            _require_scanner_service().export_payload,
            user_id=user_id,
            scan_id=scan_id,
            variant=variant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    encoded = quote(filename)
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


@router.post("/export-batch")
async def export_scan_batch(payload: ScannerBatchExportRequest) -> Response:
    """Return one ZIP containing all requested completed scanner projections."""

    try:
        filename, media_type, content = await run_in_threadpool(
            _require_scanner_service().export_batch_payload,
            user_id=payload.user_id,
            items=[(item.scan_id, item.variant) for item in payload.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    encoded = quote(filename)
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


@router.delete("/{scan_id}")
async def delete_scan(scan_id: str, user_id: str = Query(..., min_length=1)) -> dict[str, bool]:
    """Delete one terminal scanner history record and all managed artifacts."""

    try:
        deleted = await run_in_threadpool(_require_scanner_service().delete_scan, user_id=user_id, scan_id=scan_id)
        return {"ok": True, "deleted": deleted}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
