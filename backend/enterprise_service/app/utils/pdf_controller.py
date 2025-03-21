import logging
import os
import tempfile
import json
import uuid
import zipfile
import traceback
from datetime import datetime
from pathlib import Path
import boto3
import requests
import pandas as pd
import sys
import subprocess
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from urllib.parse import urlparse

# Load environment variables from .env file
load_dotenv()

# Adobe PDF Services imports
from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.exception.exceptions import ServiceApiException, ServiceUsageException, SdkException
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.extract_pdf_job import ExtractPDFJob
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_element_type import ExtractElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_pdf_params import ExtractPDFParams
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_renditions_element_type import ExtractRenditionsElementType
from adobe.pdfservices.operation.pdfjobs.result.extract_pdf_result import ExtractPDFResult

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models for input and output
class PDFProcessRequest(BaseModel):
    s3_url: str

class PDFProcessResponse(BaseModel):
    status: str
    markdown_url: str

class PDFProcessError(Exception):
    """Custom exception for PDF processing errors"""
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

#################################################
# Functions for PDF handling
#################################################

def convert_json_to_markdown(data):
    """
    Universal converter for Adobe PDF Extract API JSON to Markdown.
    Handles any PDF document structure with robust error handling.
    """
    markdown_content = []
    
    def clean_text(text):
        """Clean and normalize text content"""
        if not text:
            return ""
        # Remove multiple spaces and normalize whitespace
        text = ' '.join(text.strip().split())
        # Remove common PDF artifacts
        text = text.replace('_x000D_', '')
        return text

    def detect_heading_level(text):
        """Detect if text is a heading and determine its level"""
        if not text:
            return False, 0
            
        text = text.strip()
        
        # H1 indicators
        if any(indicator in text for indicator in ['White Paper', 'Guide', 'Documentation']):
            return True, 1
            
        # H2 indicators (main sections)
        if text.isupper() or any(text.lower().startswith(word) for word in 
            ['overview', 'introduction', 'conclusion', 'chapter', 'section']):
            return True, 2
            
        # H3 indicators (subsections)
        if text.endswith(':') or ('data' in text.lower() and len(text.split()) <= 4):
            return True, 3
            
        return False, 0

    def format_list_item(text):
        """Format list items with proper markdown"""
        text = clean_text(text)
        if not text:
            return ""
            
        if text.startswith('•') or text.startswith('-'):
            return f"* {text[1:].strip()}\n"
        elif text[0].isdigit() and '.' in text[:3]:
            parts = text.split('.', 1)
            if len(parts) > 1:
                return f"{parts[0]}. {parts[1].strip()}\n"
        return text + "\n\n"

    # Process elements
    if 'elements' in data:
        for element in data['elements']:
            # Get text content
            text = element.get('Text', '')
            if not text:
                continue

            text = clean_text(text)
            
            # Skip lone numbers (likely page numbers)
            if text.isdigit():
                continue

            # Handle lists
            if text.startswith('•') or text.startswith('-') or (text[0].isdigit() and '.' in text[:3]):
                markdown_content.append(format_list_item(text))
                continue

            # Detect headings
            is_heading, level = detect_heading_level(text)
            if is_heading:
                markdown_content.append(f"{'#' * level} {text}\n\n")
                continue

            # Handle regular paragraphs
            if len(text.split()) > 1:  # Only add if more than one word
                markdown_content.append(f"{text}\n\n")

    # Join and clean up the final markdown
    result = ''.join(markdown_content)
    
    # Clean up excessive newlines
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')
    
    # Clean up list formatting
    result = result.replace('* \n', '* ')
    
    return result.strip()


def convert_table_to_markdown(df):
    """Convert pandas DataFrame to markdown table with special handling for financial statements"""
    # Handle empty or malformed DataFrames
    if df.empty:
        return "*Empty table*"
    
    # Clean and normalize the DataFrame
    df = df.fillna('')
    
    # Clean column headers
    headers = [str(h).replace('_x000D_', '').strip() for h in df.columns.tolist()]
    
    # Simple markdown table format
    markdown_lines = []
    markdown_lines.append("| " + " | ".join(headers) + " |")
    markdown_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    
    for _, row in df.iterrows():
        cells = [str(cell).replace('_x000D_', '').strip() for cell in row]
        markdown_lines.append("| " + " | ".join(cells) + " |")
    
    return "\n".join(markdown_lines)


def process_zip(zip_path: str) -> str:
    """Handler function to process the extracted ZIP file and upload to S3"""
    # Get AWS credentials from environment variables
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION', 'us-east-1')
    bucket_name = os.getenv('S3_BUCKET_NAME', 'damg7245-nvidia-reports')
    
    # Create S3 client with explicit credentials
    s3_client = boto3.client(
        's3',
        region_name=aws_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key
    )
    
    # Create unique folder name
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    process_folder = f"Enterprise_Extract_{timestamp}_{unique_id}"
    
    # Define S3 paths
    base_s3_path = f"enterprise-parsed/{process_folder}"
    images_s3_path = f"{base_s3_path}/images"
    markdown_s3_path = f"{base_s3_path}/markdown"

    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        
        try:
            # Extract ZIP contents
            logger.info(f"Extracting ZIP file: {zip_path}")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_path)

            final_content = []

            # Process structured JSON
            json_files = list(temp_dir_path.glob('*.json'))
            if json_files:
                json_file = json_files[0]
                logger.info(f"Found JSON file: {json_file.name}")
                
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        logger.info("JSON structure keys: " + str(list(data.keys())))
                    
                    markdown_text = convert_json_to_markdown(data)
                    if markdown_text.strip():
                        final_content.append(markdown_text)
                        logger.info("Successfully converted JSON to markdown")
                    else:
                        logger.warning("No content extracted from JSON")
                except Exception as e:
                    logger.error(f"Error processing JSON file: {str(e)}")
                    logger.error(traceback.format_exc())

            # Process figures
            figures_dir = temp_dir_path / "figures"
            if figures_dir.exists():
                logger.info("Processing figures...")
                final_content.append("\n## Figures\n")
                for img_file in figures_dir.glob("*"):
                    if img_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                        s3_image_key = f"{images_s3_path}/{img_file.name}"
                        # Upload without ACL since bucket uses Object Ownership
                        s3_client.upload_file(
                            str(img_file),
                            bucket_name,
                            s3_image_key
                        )
                        # Generate the full S3 URL for the image
                        s3_image_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_image_key}"
                        logger.info(f"Uploaded image: {s3_image_key}")
                        final_content.append(f"\n![{img_file.stem}]({s3_image_url})\n")

            # Process tables
            tables_dir = temp_dir_path / "tables"
            if tables_dir.exists():
                logger.info("Processing tables...")
                final_content.append("\n## Tables\n")
                
                # Try to install openpyxl if not available
                try:
                    import importlib
                    importlib.import_module('openpyxl')
                    logger.info("openpyxl is already installed")
                except ImportError:
                    logger.info("Attempting to install openpyxl package...")
                    try:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
                        logger.info("Successfully installed openpyxl")
                    except Exception as e:
                        logger.warning(f"Could not install openpyxl: {str(e)}")
                
                # Process Excel files
                for xlsx_file in tables_dir.glob("*.xlsx"):
                    try:
                        logger.info(f"Processing table {xlsx_file.name}")
                        # Try to read with pandas
                        df = pd.read_excel(xlsx_file, engine='openpyxl')
                        # Log basic structure for debugging
                        logger.info(f"Table dimensions: {df.shape[0]} rows x {df.shape[1]} columns")
                        
                        # Look for titles in the data to use as headers
                        title = xlsx_file.stem
                        # Check first few rows for potential title
                        for i in range(min(3, len(df))):
                            # If first cell of row has multiple words and looks like a title
                            first_cell = str(df.iloc[i, 0]) if not df.empty and len(df.columns) > 0 else ""
                            if first_cell and len(first_cell.split()) > 3 and first_cell.isupper():
                                title = first_cell
                                # Remove this row from dataframe to avoid duplication
                                df = df.drop(i).reset_index(drop=True)
                                break
                                
                        final_content.append(f"\n### {title}\n")
                        table_content = convert_table_to_markdown(df)
                        final_content.append(table_content + "\n\n")
                        
                    except ImportError:
                        # Fallback for missing openpyxl
                        logger.warning(f"Cannot read Excel file {xlsx_file.name}: openpyxl not available")
                        final_content.append(f"\n### {xlsx_file.stem} (Table data unavailable)\n")
                        final_content.append("*Note: Could not read this table due to missing Excel library.*\n\n")
                    except Exception as e:
                        logger.error(f"Error processing table {xlsx_file.name}: {str(e)}")
                        final_content.append(f"\n### {xlsx_file.stem} (Error processing table)\n")
                        final_content.append(f"*Error: {str(e)}*\n\n")

            # Upload markdown content to S3
            markdown_content = ''.join(final_content)
            markdown_content = markdown_content.replace('\r\n', '\n')
            markdown_content = markdown_content.replace('_x000D_', '')
            
            s3_client.put_object(
                Bucket=bucket_name,
                Key=f"{markdown_s3_path}/content.md",
                Body=markdown_content.encode('utf-8')
            )
            logger.info(f"Uploaded markdown to S3: {markdown_s3_path}/content.md")

            # Cleanup
            logger.info("Cleaning up...")
            Path(zip_path).unlink()
            logger.info("Cleanup completed successfully")

            return f"https://{bucket_name}.s3.amazonaws.com/{base_s3_path}/"

        except Exception as e:
            logger.error(f"Error processing ZIP file: {str(e)}")
            raise PDFProcessError(f"Error processing ZIP file: {str(e)}", traceback.format_exc())

#################################################
# Functions for PDF extraction
#################################################

def extract_pdf_content(pdf_path: str, output_dir: str = "output") -> str:
    """Extract content from PDF using Adobe PDF Services API"""
    try:
        # Read PDF file
        with open(pdf_path, 'rb') as file:
            input_stream = file.read()

        # Get credentials
        credentials = ServicePrincipalCredentials(
            client_id=os.getenv('PDF_SERVICES_CLIENT_ID'),
            client_secret=os.getenv('PDF_SERVICES_CLIENT_SECRET')
        )

        # Initialize PDF services
        pdf_services = PDFServices(credentials=credentials)

        # Upload PDF
        input_asset = pdf_services.upload(
            input_stream=input_stream,
            mime_type=PDFServicesMediaType.PDF
        )

        # Set extraction parameters
        extract_params = ExtractPDFParams(
            elements_to_extract=[
                ExtractElementType.TEXT,
                ExtractElementType.TABLES
            ],
            elements_to_extract_renditions=[
                ExtractRenditionsElementType.TABLES,
                ExtractRenditionsElementType.FIGURES
            ]
        )

        # Create and submit job
        extract_job = ExtractPDFJob(
            input_asset=input_asset,
            extract_pdf_params=extract_params
        )

        # Get results
        location = pdf_services.submit(extract_job)
        response = pdf_services.get_job_result(location, ExtractPDFResult)
        
        # Save ZIP file
        result_asset = response.get_result().get_resource()
        stream_asset = pdf_services.get_content(result_asset)
        
        # Ensure output directory exists
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        output_zip = output_path / f"extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with open(output_zip, "wb") as f:
            f.write(stream_asset.get_input_stream())
        
        logger.info(f"Saved ZIP file to: {output_zip}")
        
        return str(output_zip)

    except (ServiceApiException, ServiceUsageException, SdkException) as e:
        logger.error(f"Error extracting PDF content: {str(e)}")
        raise PDFProcessError(f"Error extracting PDF content: {str(e)}", traceback.format_exc())
    except Exception as e:
        logger.error(f"Unexpected error in extract_pdf_content: {str(e)}")
        raise PDFProcessError(f"Unexpected error in extract_pdf_content: {str(e)}", traceback.format_exc())

#################################################
# Helper functions
#################################################

def download_from_s3(s3_url: str, local_path: Path):
    """
    Download file from S3 URL to local path using AWS authentication
    
    Args:
        s3_url: S3 URL in format https://<bucket-name>.s3.<region>.amazonaws.com/<key> 
               or https://<bucket-name>.s3.amazonaws.com/<key>
        local_path: Local path to save the file
    """
    try:
        # Parse the S3 URL to extract bucket name and key
        parsed_url = urlparse(s3_url)
        
        # Handle different S3 URL formats
        if 's3.amazonaws.com' in parsed_url.netloc:
            # Format: https://<bucket-name>.s3.amazonaws.com/<key>
            bucket_name = parsed_url.netloc.split('.s3.amazonaws.com')[0]
            key = parsed_url.path.lstrip('/')
        elif 's3.us-east-1.amazonaws.com' in parsed_url.netloc:
            # Format: https://<bucket-name>.s3.us-east-1.amazonaws.com/<key>
            bucket_name = parsed_url.netloc.split('.s3.us-east-1.amazonaws.com')[0]
            key = parsed_url.path.lstrip('/')
        else:
            # Format: https://s3.<region>.amazonaws.com/<bucket-name>/<key>
            parts = parsed_url.path.lstrip('/').split('/', 1)
            if len(parts) < 2:
                raise ValueError(f"Invalid S3 URL format: {s3_url}")
            bucket_name = parts[0]
            key = parts[1]
        
        logger.info(f"Downloading from bucket: {bucket_name}, key: {key}")
        
        # Initialize S3 client with credentials
        # AWS credentials should be configured in environment variables, 
        # AWS config file, or instance profile
        s3_client = boto3.client('s3')
        
        # Download the file
        s3_client.download_file(
            Bucket=bucket_name,
            Key=key,
            Filename=str(local_path)
        )
        
        logger.info(f"Downloaded file to {local_path}")
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"AWS S3 error ({error_code}): {error_message}")
        raise PDFProcessError(f"AWS S3 error: {error_message}", traceback.format_exc())
    except Exception as e:
        logger.error(f"Error downloading file from S3: {str(e)}")
        raise PDFProcessError(f"Error downloading file from S3: {str(e)}", traceback.format_exc())

#################################################
# Main processing function
#################################################

def process_pdf(s3_url: str) -> PDFProcessResponse:
    """
    Process PDF from S3 URL using Adobe PDF Services API
    
    1. Download PDF from S3 URL
    2. Extract content using Adobe PDF Extract API
    3. Process extracted content and upload to S3
    4. Return URL of the markdown file
    """
    try:
        # Create temp directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            
            # Step 1: Download PDF from S3 URL
            pdf_filename = os.path.basename(s3_url)
            local_pdf_path = temp_dir_path / pdf_filename
            
            logger.info(f"Downloading PDF from {s3_url}")
            download_from_s3(s3_url, local_pdf_path)
            
            # Step 2: Extract content directly without OCR
            logger.info(f"Extracting content from PDF")
            extract_zip_path = extract_pdf_content(str(local_pdf_path), str(temp_dir_path))
            
            # Step 3: Process extracted content and upload to S3
            s3_base_url = process_zip(extract_zip_path)
            
            # Construct markdown URL
            markdown_url = f"{s3_base_url}markdown/content.md"
            
            return PDFProcessResponse(
                status="success",
                markdown_url=markdown_url
            )
            
    except PDFProcessError as e:
        logger.error(f"PDF Processing Error: {e.message}")
        if e.details:
            logger.error(f"Details: {e.details}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in process_pdf: {str(e)}")
        logger.error(traceback.format_exc())
        raise PDFProcessError(f"Unexpected error in process_pdf: {str(e)}", traceback.format_exc())