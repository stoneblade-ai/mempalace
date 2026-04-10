import os
import tempfile
import shutil
import chromadb
from cortex.convo_miner import mine_convos


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    cortex_path = os.path.join(tmpdir, "cortex")
    mine_convos(tmpdir, cortex_path, wing="test_convos")

    client = chromadb.PersistentClient(path=cortex_path)
    col = client.get_collection("cortex_drawers")
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)
