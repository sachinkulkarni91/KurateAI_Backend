import os
import pickle
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Detect serverless environment
IS_SERVERLESS = bool(os.environ.get("VERCEL"))

# Paths
FAISS_INDEX_PATH = "incidents_index.bin"
MAPPING_PATH = "incidents_mapping.pkl"

# Globals
faiss_index = None
id_mapping = []
model = None
embedding_cache = {}


def _get_model():
    """Lazy-load the embedding model (skip on serverless)."""
    global model
    if model is not None:
        return model

    if IS_SERVERLESS:
        logger.warning("Skipping fastembed model load on serverless (Vercel)")
        return None

    try:
        from fastembed import TextEmbedding
        model = TextEmbedding()
        return model
    except Exception as e:
        logger.warning(f"Could not load fastembed model: {e}")
        return None


def _get_faiss():
    """Lazy-import faiss."""
    try:
        import faiss
        return faiss
    except ImportError:
        logger.warning("faiss-cpu not available")
        return None


# Embedding function with cache
def generate_embedding(text: str):
    if text in embedding_cache:
        return embedding_cache[text]

    m = _get_model()
    if m is None:
        # Return a zero vector as fallback
        return np.zeros(384, dtype="float32")

    if len(embedding_cache) > 1000:
        embedding_cache.clear()

    embedding = list(m.embed([text]))[0]
    embedding = np.array(embedding, dtype="float32")

    embedding_cache[text] = embedding
    return embedding


def generate_embeddings_batch(texts: list[str]) -> np.ndarray:
    embeddings = []
    for text in texts:
        emb = generate_embedding(text)
        embeddings.append(emb)
    return np.vstack(embeddings)


# Build FAISS index
def build_incidents_faiss_index():
    global faiss_index, id_mapping

    faiss = _get_faiss()
    if faiss is None:
        logger.warning("FAISS not available — skipping index build")
        return

    from services.incident_triage.utils.query import get_closed_incidents
    incidents = get_closed_incidents()

    texts = []
    id_mapping = []

    for inc in incidents:
        text = f"{inc['short_description']}. {inc['description']}"
        texts.append(text)
        id_mapping.append(inc["number"])

    if not texts:
        logger.warning("No resolved/closed incidents found for FAISS index")
        return

    embeddings = generate_embeddings_batch(texts)
    dim = embeddings.shape[1]

    faiss.normalize_L2(embeddings)
    faiss_index = faiss.IndexFlatIP(dim)
    faiss_index.add(embeddings)

    faiss.write_index(faiss_index, FAISS_INDEX_PATH)
    with open(MAPPING_PATH, "wb") as f:
        pickle.dump(id_mapping, f)

    print(f"FAISS index built and saved with {len(id_mapping)} incidents")


# Load FAISS index
def load_incident_faiss_index():
    global faiss_index, id_mapping

    faiss = _get_faiss()
    if faiss is None:
        logger.warning("FAISS not available — skipping index load")
        return

    if not os.path.exists(FAISS_INDEX_PATH) or not os.path.exists(MAPPING_PATH):
        print("FAISS index not found. Building new index...")
        build_incidents_faiss_index()
        return

    faiss_index = faiss.read_index(FAISS_INDEX_PATH)
    with open(MAPPING_PATH, "rb") as f:
        id_mapping = pickle.load(f)

    print(f"Pre-loaded FAISS index found with {len(id_mapping)} incidents")


# Search similar incidents
def search_similar_incidents(query_text: str, top_k: int = 5):
    global faiss_index, id_mapping

    faiss = _get_faiss()
    if faiss is None or faiss_index is None:
        logger.warning("FAISS not available for search")
        return []

    query_embedding = generate_embedding(query_text).reshape(1, -1)
    faiss.normalize_L2(query_embedding)
    scores, indices = faiss_index.search(query_embedding, top_k)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        results.append({
            "incident_id": id_mapping[idx],
            "similarity": float(scores[0][i])
        })

    return results


def add_incident_to_faiss(incident: dict):
    global faiss_index, id_mapping

    faiss = _get_faiss()
    if faiss is None or faiss_index is None:
        logger.warning("FAISS not available — cannot add incident")
        return

    text = f"{incident['short_description']}. {incident['description']}"
    embedding = generate_embedding(text).reshape(1, -1)
    faiss.normalize_L2(embedding)
    faiss_index.add(embedding)
    id_mapping.append(incident["number"])

    faiss.write_index(faiss_index, FAISS_INDEX_PATH)
    with open(MAPPING_PATH, "wb") as f:
        pickle.dump(id_mapping, f)

    print(f"Added incident {incident['number']} to FAISS index")