import logging
import tempfile
import urllib.parse
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

import boto3
from botocore.exceptions import ClientError

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode, PictureItem, TableItem

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "parsing.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DoclingConverter:
    def __init__(self):
        # Load environment variables from .env file
        load_dotenv()
        
        # Configure PDF pipeline options
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.images_scale = 2.0
        self.pipeline_options.generate_table_images = True
        self.pipeline_options.generate_picture_images = True
        
        # Initialize document converter
        self.doc_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
            }
        )
        
        # Get AWS credentials from environment variables
        aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')
        self.s3_bucket = os.environ.get('AWS_S3_BUCKET')
   
        
        if not self.s3_bucket:
            raise ValueError("AWS_S3_BUCKET environment variable is not set")
        
        # Initialize S3 client with credentials from environment variables
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=aws_region
        )

    def get_s3_key_from_url(self, s3_url: str) -> str:
        """
        Extract the S3 key (path) from an S3 URL
        
        Args:
            s3_url: S3 URL 
            
        Returns:
            S3 key (path)
        """
        parsed_url = urllib.parse.urlparse(s3_url)
        
        # Get everything after the domain as the key
        s3_key = parsed_url.path.lstrip('/')
        return s3_key

    def download_from_s3(self, s3_url: str) -> tuple:
        """
        Download a file from an S3 URL to a temporary file
        
        Args:
            s3_url: S3 URL of the file to download
            
        Returns:
            Tuple of (temp_path, s3_key)
        """
        logger.info(f"Downloading file from S3: {s3_url}")
        
        try:
            # Get the S3 key from the URL
            s3_key = self.get_s3_key_from_url(s3_url)
            
            # Create a temporary file to store the downloaded content
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Download the file from S3
            self.s3_client.download_file(self.s3_bucket, s3_key, str(temp_path))
            logger.info(f"Successfully downloaded S3 file to {temp_path}")
            
            return temp_path, s3_key
            
        except ClientError as e:
            logger.error(f"Error downloading from S3: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error downloading from S3: {e}")
            raise

    def upload_to_s3(self, local_path: Path, s3_key: str) -> str:
        """
        Upload a file to S3
        
        Args:
            local_path: Path to the local file
            s3_key: S3 key for the uploaded file
            
        Returns:
            S3 URL of the uploaded file
        """
        try:
            self.s3_client.upload_file(str(local_path), self.s3_bucket, s3_key)
            s3_url = f"https://{self.s3_bucket}.s3.amazonaws.com/{s3_key}"
            logger.info(f"Successfully uploaded {local_path} to {s3_url}")
            return s3_url
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            raise

    def upload_results_to_s3(self, output_dir: Path, base_key: str) -> Dict[str, Any]:
        """
        Upload processing results to S3
        
        Args:
            output_dir: Directory containing output files
            base_key: Base S3 key for uploads
            
        Returns:
            Dictionary with S3 URLs
        """
        s3_urls = {
            'markdown_urls': [],
            'image_urls': []
        }
        
        # Upload markdown files
        markdown_dir = output_dir / "markdown"
        if markdown_dir.exists():
            for md_file in markdown_dir.glob("*.md"):
                s3_key = f"{base_key}/markdown/{md_file.name}"
                s3_url = self.upload_to_s3(md_file, s3_key)
                s3_urls['markdown_urls'].append(s3_url)
        
        # Upload image files
        images_dir = output_dir / "images"
        if images_dir.exists():
            for img_file in images_dir.glob("*.png"):
                s3_key = f"{base_key}/images/{img_file.name}"
                s3_url = self.upload_to_s3(img_file, s3_key)
                s3_urls['image_urls'].append(s3_url)
        
        return s3_urls

    def process_s3_pdf(self, s3_url: str) -> Optional[str]:
        """
        Process a PDF file from an S3 URL, convert to markdown with images,
        and upload results back to S3
        
        Args:
            s3_url: S3 URL of the PDF file
        
        Returns:
            URL of the uploaded markdown file, or None if processing failed
        """
        temp_pdf_path = None
        temp_output_dir = None
        
        try:
            # Download the PDF from S3
            temp_pdf_path, s3_key = self.download_from_s3(s3_url)
            
            # Create temporary output directory
            temp_output_dir = Path(tempfile.mkdtemp())
            
            # Process the downloaded PDF
            result = self.process_pdf(temp_pdf_path, temp_output_dir)
            
            if result['status'] in ['success', 'partial_success']:
                # Determine base path for S3 uploads
                pdf_filename = Path(s3_key).stem
                processed_base_key = f"docling-parsed/{pdf_filename}"
                
                # Upload markdown and images to S3
                s3_urls = self.upload_results_to_s3(temp_output_dir, processed_base_key)
                
                # Return the first markdown URL if available
                if s3_urls['markdown_urls']:
                    return s3_urls['markdown_urls'][0]
                else:
                    logger.warning("No markdown files were uploaded")
                    return None
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error processing S3 PDF: {str(e)}")
            return None
        
        finally:
            # Clean up temporary files and directories
            self.cleanup_temp_files(temp_pdf_path, temp_output_dir)

    def cleanup_temp_files(self, pdf_path: Path = None, output_dir: Path = None):
        """
        Clean up temporary files and directories
        
        Args:
            pdf_path: Path to temporary PDF file
            output_dir: Path to temporary output directory
        """
        if pdf_path and pdf_path.exists():
            pdf_path.unlink()
            logger.info(f"Deleted temporary file: {pdf_path}")
        
        if output_dir and output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
            logger.info(f"Deleted temporary directory: {output_dir}")

    def process_pdf(self, pdf_path: Path, output_dir: Path) -> Dict[str, Any]:
        """
        Process a single PDF file and convert to markdown with images
        
        Args:
            pdf_path: Path to input PDF file
            output_dir: Directory for output files
        
        Returns:
            Dictionary containing processing results
        """
        try:
            # Create output directories
            markdown_dir = output_dir / "markdown"
            images_dir = output_dir / "images"
            markdown_dir.mkdir(parents=True, exist_ok=True)
            images_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Going to convert document batch...")
            # Convert PDF
            conv_results = self.doc_converter.convert_all([pdf_path], raises_on_error=False)
            
            for conv_res in conv_results:
                if conv_res.status == ConversionStatus.SUCCESS:
                    # Generate base filename
                    base_filename = conv_res.input.file.stem
                    
                    # Save markdown with embedded images
                    markdown_content = conv_res.document.export_to_markdown(
                        image_mode=ImageRefMode.EMBEDDED
                    )
                    markdown_path = markdown_dir / f"{base_filename}.md"
                    markdown_path.write_text(markdown_content)
                    
                    # Export tables and images
                    table_count = 0
                    image_count = 0
                    
                    for element, _ in conv_res.document.iterate_items():
                        if isinstance(element, TableItem):
                            table_count += 1
                            image_path = images_dir / f"{base_filename}-table-{table_count}.png"
                            element.image.pil_image.save(image_path, "PNG")
                        
                        if isinstance(element, PictureItem):
                            image_count += 1
                            image_path = images_dir / f"{base_filename}-image-{image_count}.png"
                            element.image.pil_image.save(image_path, "PNG")
                    
                    return {
                        'status': 'success',
                        'tables': table_count,
                        'images': image_count
                    }
                
                elif conv_res.status == ConversionStatus.PARTIAL_SUCCESS:
                    error_msg = "Document was partially converted with errors"
                    logger.warning(f"{error_msg}: {conv_res.errors}")
                    return {'status': 'partial_success', 'message': error_msg}
                
                else:
                    error_msg = "Conversion failed"
                    logger.error(error_msg)
                    return {'status': 'error', 'message': error_msg}
                    
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {'status': 'error', 'message': str(e)}