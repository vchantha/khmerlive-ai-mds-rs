import boto3
from botocore.client import Config
from app.config import settings

def client():
    return boto3.client("s3",endpoint_url=f"http://{settings.minio_endpoint}",aws_access_key_id=settings.minio_access_key,aws_secret_access_key=settings.minio_secret_key,region_name="us-east-1",config=Config(signature_version="s3v4"))
