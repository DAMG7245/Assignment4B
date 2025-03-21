from fastapi import APIRouter, Depends, File, UploadFile, status, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
from controllers.rag_api_controller import FileController

# Create router
router = APIRouter()

# Response models
class UploadResponse(BaseModel):
    filename: str
    file_url: str
    file_size: int
    content_type: str
    upload_date: str

# File upload endpoint
@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    folder: Optional[str] = "raw_reports"
):
    controller = FileController()
    return await controller.upload_file(file, folder)

# Get file list endpoint
@router.get("/files", status_code=status.HTTP_200_OK)
async def list_files(
    folder: Optional[str] = "raw_reports"
):
    controller = FileController()
    return await controller.list_files(folder)

@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return JSONResponse(content={"status": "ok"})