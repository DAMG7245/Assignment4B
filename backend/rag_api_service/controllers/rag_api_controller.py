import boto3
import os
from dotenv import load_dotenv
from typing import Optional
import uuid
from datetime import datetime
from fastapi import UploadFile, HTTPException, status
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# AWS S3 configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

class FileController:
    def __init__(self):
        # Validate environment variables
        if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_BUCKET_NAME]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="S3 configuration is missing. Please set the required environment variables."
            )
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
    
    async def upload_file(self, file: UploadFile, folder: Optional[str]):
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Invalid file"
            )
        
        try:
            # Generate a unique filename
            # file_extension = os.path.splitext(file.filename)[1]
            # unique_filename = f"{uuid.uuid4()}{file_extension}"
            sanitized_filename = os.path.basename(file.filename)
            # Set the S3 path
            s3_path = f"{folder}/{sanitized_filename}" if folder else sanitized_filename
            
            # Read file content
            contents = await file.read()
            file_size = len(contents)
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=AWS_BUCKET_NAME,
                Key=s3_path,
                Body=contents,
                ContentType=file.content_type
            )
            
            # Generate URL to the file
            file_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_path}"
            
            # Return success response
            return {
                "filename": sanitized_filename,
                "file_url": file_url,
                "file_size": file_size,
                "content_type": file.content_type,
                "upload_date": datetime.now().isoformat()
            }
            
        except Exception as e:
            # Log the error
            print(f"Error uploading file: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail=f"Failed to upload file: {str(e)}"
            )
    
 
    async def list_files(self, folder: Optional[str]):
        try:
            prefix = f"{folder}/" if folder else ""
            
            response = self.s3_client.list_objects_v2(
                Bucket=AWS_BUCKET_NAME,
                Prefix=prefix
            )
            
            files = []
            if 'Contents' in response:
                for item in response['Contents']:
                    file_key = item['Key']
                    file_name = os.path.basename(file_key)
                    file_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_key}"
                    
                    files.append({
                        "filename": file_name,
                        "file_url": file_url,
                        "size": item['Size'],
                        "last_modified": item['LastModified'].isoformat()
                    })
                    
            return {"files": files}
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail=f"Failed to list files: {str(e)}"
            )