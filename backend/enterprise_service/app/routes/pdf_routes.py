from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from app.utils.pdf_controller import process_pdf, PDFProcessError, PDFProcessRequest, PDFProcessResponse

router = APIRouter()

@router.post("/extract-pdf/enterprise", response_model=PDFProcessResponse)
async def process_pdf_endpoint(request: PDFProcessRequest = Body(...)):
    try:
        result = process_pdf(request.s3_url)
        return result
    except PDFProcessError as e:
        raise HTTPException(status_code=500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF processing failed: {str(e)}")