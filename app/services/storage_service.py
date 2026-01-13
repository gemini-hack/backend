
import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile
import io
from app.core.config import settings
from app.utils.logger import logger

class StorageService:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION
        )
        self.bucket = settings.S3_BUCKET_NAME
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.s3_client.create_bucket(Bucket=self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
            except Exception as e:
                logger.error(f"Failed to create bucket {self.bucket}: {e}")

    def upload_file(self, file: UploadFile, key: str) -> str:
        """
        Upload a file to object storage.
        Returns the key.
        """
        try:
            self.s3_client.upload_fileobj(
                file.file,
                self.bucket,
                key,
                ExtraArgs={'ContentType': file.content_type}
            )
            logger.info(f"Uploaded file {key} to {self.bucket}")
            return key
        except ClientError as e:
            logger.error(f"Failed to upload file {key}: {e}")
            raise

    def get_file(self, key: str) -> io.BytesIO:
        """
        Download a file from object storage.
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            return io.BytesIO(response['Body'].read())
        except ClientError as e:
            logger.error(f"Failed to download file {key}: {e}")
            raise
