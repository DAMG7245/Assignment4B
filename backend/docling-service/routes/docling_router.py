from fastapi import FastAPI, HTTPException, APIRouter
from pydantic import BaseModel, HttpUrl
import logging
import os
from dotenv import load_dotenv

from controllers.docling_controller import DoclingConverter

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

class S3PDFProcessRequest(BaseModel):
    s3_url: HttpUrl
    
@router.post("/docling_process_s3_pdf/", status_code=200)
async def process_s3_pdf(request: S3PDFProcessRequest):
    """
    Process a PDF from an S3 URL
    
    This endpoint expects an S3 URL pointing to a PDF file.
    It will download the PDF, process it, and upload the results back to S3.
    """
    logger.info(f"Processing PDF from S3 URL: {request.s3_url}")
    
    try:
        # Process the PDF and get the markdown URL
        converter = DoclingConverter()
        markdown_url = converter.process_s3_pdf(str(request.s3_url))
        
        # Check if markdown URL was returned
        if markdown_url is None:
            logger.error("Failed to process PDF: No markdown URL returned")
            raise HTTPException(
                status_code=500,
                detail="Failed to process the PDF: No markdown URL was generated"
            )
        
        # Return a structured response with the markdown URL
        logger.info(f"PDF processing completed for URL: {request.s3_url}")
        return {
            "status": "success",
            "markdown_url": markdown_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception during PDF processing: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process the PDF: {str(e)}")