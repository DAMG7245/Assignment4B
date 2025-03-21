import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.utils.pdf_utils import PdfConverter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI router
router = APIRouter()

class PdfProcessingResponse(BaseModel):
    status: str
    markdown_url: str = None

class S3UrlRequest(BaseModel):
    s3_url: str

@router.post("/pdf-process/opensource", response_model=PdfProcessingResponse)
async def process_pdf_from_s3(request: S3UrlRequest) -> PdfProcessingResponse:
    """
    Endpoint to process PDF directly from an S3 URL
    
    Args:
        request: S3UrlRequest containing the s3_url of the PDF
        
    Returns:
        PdfProcessingResponse: Processing results with status and markdown_url
    """
    try:
        # Initialize PDF converter with the enterprise target bucket
        pdf_converter = PdfConverter(bucket_name="damg7245-nvidia-reports")
        
        # Process the PDF from S3
        result = pdf_converter.process_pdf_from_s3(request.s3_url)
        
        if result['status'] != 'success':
            return PdfProcessingResponse(
                status="error"
            )
        
        # Return simplified response format
        return PdfProcessingResponse(
            status="success",
            markdown_url=result['markdown_url']
        )
            
    except Exception as e:
        error_msg = f"Error processing PDF from S3: {str(e)}"
        logger.error(error_msg)
        return PdfProcessingResponse(
            status="error"
        )

# Export router
__all__ = ['router']