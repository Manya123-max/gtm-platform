import asyncio
import math
import sys
import os

# Add parent directory to path to allow importing app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.embedding_service import EmbeddingService
from app.core.config import settings

async def main():
    print("Initializing EmbeddingService...")
    print(f"Configured EMBEDDING_MODEL: {settings.EMBEDDING_MODEL}")
    
    embedder = EmbeddingService()
    
    # Test sentences
    s1 = "Our sales automation software helps teams close deals faster."
    s2 = "We build tools to automate the go-to-market funnel and accelerate sales."
    s3 = "The weather in Seattle is rainy and cold today."
    
    print("\nGenerating embeddings...")
    e1 = await embedder.embed(s1)
    e2 = await embedder.embed(s2)
    e3 = await embedder.embed(s3)
    
    # 1. Verify dimensions
    print("\n--- 1. Dimension Check ---")
    print(f"s1 embedding dimensions: {len(e1)}")
    print(f"s2 embedding dimensions: {len(e2)}")
    print(f"s3 embedding dimensions: {len(e3)}")
    assert len(e1) == 384, f"Expected 384 dimensions, got {len(e1)}"
    assert len(e2) == 384, f"Expected 384 dimensions, got {len(e2)}"
    assert len(e3) == 384, f"Expected 384 dimensions, got {len(e3)}"
    print("Dimension Check: PASSED (exactly 384 dimensions)")
    
    # 2. Verify non-zero values
    print("\n--- 2. Non-Zero Values Check ---")
    sum_abs_e1 = sum(abs(x) for x in e1)
    print(f"Sum of absolute values in e1: {sum_abs_e1:.6f}")
    assert sum_abs_e1 > 1.0, f"Vector values are too close to zero: {sum_abs_e1}"
    print("Non-Zero Values Check: PASSED (contains meaningful non-zero values)")
    
    # 3. Verify normalization (L2 norm should be ~1.0)
    print("\n--- 3. Normalization Check ---")
    norm_e1 = math.sqrt(sum(x * x for x in e1))
    norm_e2 = math.sqrt(sum(x * x for x in e2))
    norm_e3 = math.sqrt(sum(x * x for x in e3))
    print(f"s1 L2 norm: {norm_e1:.6f}")
    print(f"s2 L2 norm: {norm_e2:.6f}")
    print(f"s3 L2 norm: {norm_e3:.6f}")
    assert abs(norm_e1 - 1.0) < 1e-4, f"Expected L2 norm ~1.0, got {norm_e1}"
    assert abs(norm_e2 - 1.0) < 1e-4, f"Expected L2 norm ~1.0, got {norm_e2}"
    assert abs(norm_e3 - 1.0) < 1e-4, f"Expected L2 norm ~1.0, got {norm_e3}"
    print("Normalization Check: PASSED (fully L2-normalized)")
    
    # 4. Cosine similarity checks
    print("\n--- 4. Cosine Similarity Check ---")
    sim_related = embedder.cosine_similarity(e1, e2)
    sim_unrelated = embedder.cosine_similarity(e1, e3)
    
    print(f"Cosine similarity (related sentences):   {sim_related:.6f}")
    print(f"Cosine similarity (unrelated sentences): {sim_unrelated:.6f}")
    
    # Semantic verification
    assert sim_related > 0.5, f"Expected related similarity > 0.5, got {sim_related}"
    assert sim_unrelated < 0.3, f"Expected unrelated similarity < 0.3, got {sim_unrelated}"
    assert sim_related > sim_unrelated + 0.3, f"Expected margin > 0.3, got margin {sim_related - sim_unrelated}"
    print("Cosine Similarity Check: PASSED (strong semantic distinction!)")
    
    print("\nALL SEMANTIC EMBEDDING VALIDATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
