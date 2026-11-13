"""Chunks every document in the DB, embeds the chunks, stores the vectors, builds the index.

Run after seeding:  python -m scripts.ingest      (idempotent: safe to re-run)
"""
import time

import psycopg
from pgvector.psycopg import register_vector

from app.config import get_settings
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import embed_documents


def main() -> None:
    with psycopg.connect(get_settings().database_url) as conn:
        register_vector(conn)        # teaches psycopg to send numpy arrays as pgvector values
        docs = conn.execute("SELECT id, source, content FROM documents ORDER BY id").fetchall()

        rows = []                    # (document_id, chunk_index, content)
        for doc_id, source, content in docs:
            chunks = chunk_markdown(content)
            rows += [(doc_id, c.index, c.content) for c in chunks]
            print(f"{source}: {len(chunks)} chunks")

        t0 = time.perf_counter()
        vectors = embed_documents([content for _, _, content in rows])   # one batched call
        print(f"Embedded {len(rows)} chunks in {time.perf_counter() - t0:.2f}s -> shape {vectors.shape}")

        conn.execute("DELETE FROM chunks")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, content, embedding) VALUES (%s,%s,%s,%s)",
                [(d, i, c, v) for (d, i, c), v in zip(rows, vectors)],
            )
        # HNSW = approximate nearest-neighbour graph index. vector_cosine_ops must match the
        # operator used in queries (<=> is cosine), or Postgres silently won't use the index.
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
                     "ON chunks USING hnsw (embedding vector_cosine_ops)")
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
