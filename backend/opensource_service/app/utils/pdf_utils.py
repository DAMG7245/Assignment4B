import logging
from pathlib import Path
from typing import Dict, Any, Optional
import boto3
import uuid
from datetime import datetime
import fitz  # PyMuPDF for PDF processing
import tempfile
import os

# Create logs directory if it doesn't exist
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

class PdfConverter:
    def __init__(self, bucket_name: str = None):
        """Initialize PdfConverter with S3 bucket configuration and AWS credentials from environment variables"""
        # Get AWS credentials from environment variables
        aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')
        
        # Use bucket from environment variable if not provided
        self.bucket_name = bucket_name or os.environ.get('AWS_S3_BUCKET', "damg7245-datanexus-pro")
        
        # Initialize S3 client with credentials
        self.s3_client = boto3.client(
            's3',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        
        logger.info(f"Initialized PdfConverter with bucket: {self.bucket_name}, region: {aws_region}")

    def get_s3_url(self, s3_key: str) -> str:
        """Generate an S3 URL for a given key"""
        return f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"

    def download_from_s3(self, s3_url: str) -> Optional[Path]:
        """Download a file from S3 URL to temporary location
        
        Args:
            s3_url: Full S3 URL (https://bucket-name.s3.region.amazonaws.com/key)
            
        Returns:
            Path object to temporary file or None if download failed
        """
        try:
            # Parse the S3 URL to extract bucket and key
            parts = s3_url.replace("https://", "").split("/", 1)
            bucket_domain = parts[0]
            object_key = parts[1]
            
            # Extract bucket name from domain
            bucket_name = bucket_domain.split(".")[0]
            
            # Create a temporary file
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            tmp_path = Path(tmp_file.name)
            tmp_file.close()
            
            logger.info(f"Downloading from bucket: {bucket_name}, key: {object_key}")
            
            # Download the file
            self.s3_client.download_file(bucket_name, object_key, str(tmp_path))
            logger.info(f"Successfully downloaded S3 file to {tmp_path}")
            
            return tmp_path
            
        except Exception as e:
            logger.error(f"Failed to download from S3 URL {s3_url}: {str(e)}")
            return None

    def upload_to_s3(self, local_path: Path, s3_key: str) -> bool:
        """Upload a file to S3 with error handling"""
        try:
            if not local_path.exists():
                logger.error(f"File not found: {local_path}")
                return False

            self.s3_client.upload_file(str(local_path), self.bucket_name, s3_key)
            logger.info(f"Successfully uploaded {local_path} to s3://{self.bucket_name}/{s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {local_path} to S3: {str(e)}")
            return False

    def extract_and_upload_images(
        self,
        pdf_document: fitz.Document,
        images_dir: Path,
        base_filename: str,
        base_s3_path: str
    ) -> list:
        """Extract embedded images from PDF and upload to S3"""
        image_info = []
        images_dir.mkdir(parents=True, exist_ok=True)

        try:
            for page_num, page in enumerate(pdf_document):
                # Get a list of all images on the page
                image_list = page.get_images()

                for img_idx, img in enumerate(image_list):
                    try:
                        # Get the xref of the image
                        xref = img[0]

                        # Extract image info
                        base_image = pdf_document.extract_image(xref)
                        if base_image:
                            image_bytes = base_image["image"]
                            image_ext = base_image["ext"]

                            # Save image
                            image_filename = f"{base_filename}_image_{page_num + 1}_{img_idx + 1}.{image_ext}"
                            image_path = images_dir / image_filename

                            with open(image_path, 'wb') as img_file:
                                img_file.write(image_bytes)

                            # Upload to S3
                            image_s3_key = f"{base_s3_path}/images/{image_filename}"
                            if self.upload_to_s3(image_path, image_s3_key):
                                # Get the bounding box of the image (if available)
                                bbox = img[1:5]  # x0, y0, x1, y1
                                image_info.append({
                                    'page': page_num,
                                    'bbox': bbox,
                                    'type': 'image',
                                    's3_url': self.get_s3_url(image_s3_key)
                                })
                                logger.info(f"Successfully extracted and uploaded image {img_idx + 1} from page {page_num + 1}")

                    except Exception as e:
                        logger.error(f"Failed to process image {img_idx} on page {page_num}: {str(e)}")
                        continue

            return sorted(image_info, key=lambda x: (x['page'], x['bbox'][1]))

        except Exception as e:
            logger.error(f"Error in extract_and_upload_images: {str(e)}")
            return []

    def extract_text_with_layout(
        self,
        pdf_document: fitz.Document,
        image_info: list
    ) -> str:
        """Extract text while preserving layout and image positions"""
        try:
            markdown_content = []

            for page_num, page in enumerate(pdf_document):
                page_dict = page.get_text("dict")
                blocks = sorted(page_dict["blocks"], key=lambda b: (b["bbox"][1], b["bbox"][0]))

                # Track current y-position for image placement
                current_y = 0

                for block in blocks:
                    # Get block's vertical position
                    block_y = block["bbox"][1]

                    # Insert any images that should appear before this block
                    page_images = [img for img in image_info if img['page'] == page_num and 
                                current_y <= img['bbox'][1] < block_y]

                    for img in sorted(page_images, key=lambda x: x['bbox'][1]):
                        markdown_content.append(f"\n![image]({img['s3_url']})\n")
                        image_info.remove(img)

                    if block["type"] == 0:  # Text
                        # Process text
                        text_content = []
                        for line in block["lines"]:
                            try:
                                text = " ".join(span["text"] for span in line["spans"])
                                font_size = line["spans"][0]["size"]

                                if font_size > 14:
                                    text_content.append(f"## {text}\n")
                                else:
                                    text_content.append(f"{text}\n")
                            except Exception as e:
                                logger.error(f"Error processing line: {str(e)}")
                                continue

                        markdown_content.append("".join(text_content))

                    current_y = block["bbox"][3]  # Update current y-position

                # Add any remaining images for this page
                remaining_images = [img for img in image_info if img['page'] == page_num]
                for img in sorted(remaining_images, key=lambda x: x['bbox'][1]):
                    markdown_content.append(f"\n![image]({img['s3_url']})\n")
                    image_info.remove(img)

                # Add page break between pages
                markdown_content.append("\n---\n")

            return "".join(markdown_content)

        except Exception as e:
            logger.error(f"Error in extract_text_with_layout: {str(e)}")
            return ""
 
    def process_pdf(self, pdf_path: Path) -> Dict[str, Any]:
        """Process a single PDF file"""
        try:
            # Create base directories
            output_dir = Path("output")
            markdown_dir = output_dir / "markdown"
            images_dir = output_dir / "images"

            for dir_path in [markdown_dir, images_dir]:
                dir_path.mkdir(parents=True, exist_ok=True)

            # Create unique folder name for S3
            unique_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Use enterprise folder prefix
            process_folder = f"Enterprise_Extract_{timestamp}_{unique_id}"
            
            # Set the S3 path
            base_s3_path = "enterprise-parsed"
            s3_path = f"{base_s3_path}/{process_folder}"

            logger.info(f"Processing PDF: {pdf_path}")
            logger.info(f"Output folder: {process_folder}")

            try:
                pdf_document = fitz.open(pdf_path)
            except Exception as e:
                logger.error(f"Failed to open PDF: {str(e)}")
                return {'status': 'error', 'message': f"Failed to open PDF: {str(e)}"}

            try:
                base_filename = pdf_path.stem

                # First extract and upload images
                image_info = self.extract_and_upload_images(
                    pdf_document, images_dir, base_filename, s3_path
                )

                # Then extract text with layout and image positions
                markdown_content = self.extract_text_with_layout(pdf_document, image_info)

                # Save and upload markdown
                markdown_path = markdown_dir / f"{base_filename}.md"

                # Then extract text with layout and image positions
                try:
                    markdown_path.write_text(markdown_content)
                    logger.info(f"Saved markdown to {markdown_path}")
                except Exception as e:
                    logger.error(f"Failed to save markdown: {str(e)}")
                    return {'status': 'error', 'message': f"Failed to save markdown: {str(e)}"}

                markdown_s3_key = f"{s3_path}/markdown/content.md"
                if not self.upload_to_s3(markdown_path, markdown_s3_key):
                    return {'status': 'error', 'message': "Failed to upload markdown to S3"}

                # Return simplified response
                return {
                    'status': 'success',
                    'markdown_url': self.get_s3_url(markdown_s3_key)
                }

            finally:
                try:
                    pdf_document.close()
                except:
                    pass

        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {'status': 'error', 'message': str(e)}
            
    def process_pdf_from_s3(self, s3_url: str) -> Dict[str, Any]:
        """Process a PDF file directly from S3 URL
        
        Args:
            s3_url: S3 URL of the PDF file
            
        Returns:
            Dict with processing results
        """
        temp_pdf_path = None
        try:
            # Download PDF from S3
            temp_pdf_path = self.download_from_s3(s3_url)
            if not temp_pdf_path:
                return {'status': 'error', 'message': f"Failed to download PDF from {s3_url}"}
                
            # Process the PDF
            result = self.process_pdf(temp_pdf_path)
            return result
            
        except Exception as e:
            logger.error(f"Error processing PDF from S3: {str(e)}")
            return {'status': 'error', 'message': str(e)}
            
        finally:
            # Clean up temporary file
            if temp_pdf_path:
                try:
                    temp_pdf_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"Error cleaning up temporary file: {str(e)}")
                    
# Example handler function for API requests
def handle_pdf_conversion_request(request_data):
    """Handle PDF conversion request
    
    Args:
        request_data: Dictionary containing 's3_url' key
        
    Returns:
        Dict with processing results
    """
    try:
        # Extract S3 URL from request
        if 's3_url' not in request_data:
            return {'status': 'error', 'message': "Missing 's3_url' parameter"}
            
        s3_url = request_data['s3_url']
        
        # Initialize converter
        converter = PdfConverter()
        
        # Process PDF from S3
        result = converter.process_pdf_from_s3(s3_url)
        
        return result
        
    except Exception as e:
        logger.error(f"Error handling conversion request: {str(e)}")
        return {'status': 'error', 'message': str(e)}