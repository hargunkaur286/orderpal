"""Play with embeddings to build intuition. Edit the sentences and re-run:

    python -m scripts.playground
"""
import numpy as np

from app.rag.embeddings import embed_documents

SENTENCES = [
    "How long does a card refund take?",
    "Refunds to a credit card arrive in 5-7 business days.",
    "My money hasn't come back to my bank yet",        # no word overlap with the line above!
    "Can I cancel my order?",
    "Orders can be cancelled free within 60 seconds.",
    "The butter chicken was delicious.",
]

vecs = embed_documents(SENTENCES)
print(f"Each sentence -> {vecs.shape[1]} numbers. First 5 of sentence 0: {np.round(vecs[0][:5], 3)}")
print(f"Length of each vector (normalized): {np.linalg.norm(vecs[0]):.3f}\n")

sims = vecs @ vecs.T          # normalized vectors: dot product == cosine similarity
for i, s in enumerate(SENTENCES):
    best = sorted(((sims[i][j], SENTENCES[j]) for j in range(len(SENTENCES)) if j != i), reverse=True)
    print(f"{s!r}\n   closest: {best[0][1]!r} ({best[0][0]:.2f})   farthest: {best[-1][1]!r} ({best[-1][0]:.2f})")
