import os
import time
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MinioInit")

endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
bucket_name = os.getenv("MINIO_BUCKET_NAME", "vision-frames")

try:
    from minio import Minio
except ImportError:
    logger.error("minio package not installed")
    sys.exit(1)

client = Minio(
    endpoint=endpoint,
    access_key=access_key,
    secret_key=secret_key,
    secure=False
)

max_retries = 30
for i in range(max_retries):
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            logger.info(f"Successfully created bucket: {bucket_name}")
        else:
            logger.info(f"Bucket '{bucket_name}' already exists")

        # Set anonymous download policy (public read)
        policy = f'''{{
            "Version": "2012-10-17",
            "Statement": [
                {{
                    "Effect": "Allow",
                    "Principal": {{"AWS": ["*"]}},
                    "Action": ["s3:GetObject"],
                    "Resource": ["arn:aws:s3:::{bucket_name}/*"]
                }}
            ]
        }}'''
        client.set_bucket_policy(bucket_name, policy)
        logger.info(f"Successfully set download policy for '{bucket_name}'")
        sys.exit(0)
    except Exception as e:
        logger.info(f"Waiting for MinIO endpoint ({endpoint})... attempt {i+1}/{max_retries}. Error: {e}")
        time.sleep(2)

logger.error("Failed to connect to MinIO after maximum retries")
sys.exit(1)
