"""
Seed/import script for adding real company brand assets and case studies to the GTM platform.
This script generates the 384-dimensional hash-based embedding using the existing EmbeddingService
and inserts the record into the database.

Usage:
    docker compose exec -T backend env PYTHONPATH=/app python /app/scripts/seed_brand_assets.py \\
        --title "CSL Case Study" \\
        --content "Cloud Science Labs scaled their sales development team by 40% using our go-to-market automation solutions." \\
        --format "case_study" \\
        --segment "SaaS"
"""
import asyncio
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal
from app.models.models import BrandAsset
from app.services.embedding_service import EmbeddingService
from sqlalchemy import select, and_


async def main():
    parser = argparse.ArgumentParser(description="Seed a brand asset with generated embeddings.")
    parser.add_argument("--title", required=True, help="Title or type of the company asset")
    parser.add_argument("--content", required=True, help="Original factual text content")
    parser.add_argument("--format", default=None, help="Optional format type (e.g. case_study, blog)")
    parser.add_argument("--segment", default=None, help="Optional target ICP segment")

    args = parser.parse_args()

    title = args.title.strip()
    content = args.content.strip()
    content_format = args.format.strip() if args.format else None
    icp_segment = args.segment.strip() if args.segment else None

    if not title or not content:
        print("Error: --title and --content must be non-empty strings.")
        sys.exit(1)

    print("Checking for existing duplicate asset content in database...")
    async with AsyncSessionLocal() as db:
        existing_query = select(BrandAsset.id).where(BrandAsset.content == content).limit(1)
        existing_res = await db.execute(existing_query)
        existing_id = existing_res.scalar_one_or_none()

        if existing_id:
            print(f"Skipping insertion: Asset already exists with ID: {existing_id}")
            return

        print("Generating 384-dimensional embedding using EmbeddingService...")
        embedder = EmbeddingService()
        embedding = await embedder.embed(content)

        if not embedding or len(embedding) != 384:
            print(f"Error: Embedding generation failed or did not return 384 dimensions. Got length: {len(embedding) if embedding else 0}")
            sys.exit(1)

        print("Verification: Embedding generated successfully (not NULL, length: 384).")

        print("Inserting new BrandAsset record...")
        new_asset = BrandAsset(
            title=title,
            content=content,
            content_format=content_format,
            icp_segment=icp_segment,
            embedding=embedding
        )
        db.add(new_asset)
        await db.commit()
        await db.refresh(new_asset)

        print(f"Success! Inserted BrandAsset ID: {new_asset.id}")


if __name__ == "__main__":
    asyncio.run(main())
