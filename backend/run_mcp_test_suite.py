"""Lance la suite de 13 tests MCP (10 prompts + 3 cas limites) et imprime
les sorties brutes que Claude recevrait. Pour rapport `MCP_TEST_REPORT.md`."""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.sse import sse_client

# (numéro, titre, tool, args)
TESTS = [
    ("1", "Aperçu corpus", "get_corpus_stats", {}),
    ("2", "Recherche 'altm'", "search_entities", {"query": "altm"}),
    ("3", "Profil Macron", "get_entity_profile", {"slug": "emmanuel-macron"}),
    (
        "4",
        "Images Altman profil G. (uniques)",
        "get_entity_images",
        {"slug": "sam-altman", "pose": "left", "unique_only": True, "limit": 5},
    ),
    (
        "5",
        "Compare Altman ↔ Musk",
        "compare_entities",
        {"slug_a": "sam-altman", "slug_b": "elon-musk"},
    ),
    (
        "6",
        "Timeline Trump (mois)",
        "get_media_timeline",
        {"slug": "donald-trump", "granularity": "month"},
    ),
    ("7", "Profil Bengio", "get_entity_profile", {"slug": "yoshua-bengio"}),
    (
        "8",
        "Images Altman tout (audit)",
        "get_entity_images",
        {"slug": "sam-altman", "unique_only": False, "limit": 50},
    ),
    ("9a", "Profil Trump", "get_entity_profile", {"slug": "donald-trump"}),
    ("9b", "Profil Musk", "get_entity_profile", {"slug": "elon-musk"}),
    ("9c", "Profil Macron (rappel)", "get_entity_profile", {"slug": "emmanuel-macron"}),
    (
        "10",
        "Analyse pattern Altman",
        "analyze_visibility_pattern",
        {"slug": "sam-altman"},
    ),
    ("A", "Entité inexistante", "get_entity_profile", {"slug": "yoshua-inexistant"}),
    (
        "B",
        "Compare inconnus",
        "compare_entities",
        {"slug_a": "marcel-duchamp", "slug_b": "andre-breton"},
    ),
    ("C", "Recherche multi-mots", "search_entities", {"query": "elon musk"}),
]


async def main():
    async with sse_client("http://mcp:8001/sse") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for num, title, tool, args in TESTS:
                print(f"\n{'=' * 70}")
                print(f"[{num}] {title}")
                print(f"     → {tool}({json.dumps(args, ensure_ascii=False)})")
                print("=" * 70)
                try:
                    result = await s.call_tool(tool, args)
                    if not result.content:
                        print("(réponse vide)")
                        continue
                    text = result.content[0].text
                    # Compact JSON pour la lecture rapide ; tronque les listes longues
                    try:
                        parsed = json.loads(text)
                        # Tronque les listes images / buckets pour ne pas inonder
                        if isinstance(parsed, dict):
                            for k in ("images", "buckets", "article_titles", "results", "top_entities"):
                                if isinstance(parsed.get(k), list) and len(parsed[k]) > 5:
                                    n = len(parsed[k])
                                    parsed[k] = parsed[k][:5] + [f"… {n - 5} autres tronqués"]
                        print(json.dumps(parsed, ensure_ascii=False, indent=2)[:2500])
                    except json.JSONDecodeError:
                        print(text[:2000])
                except Exception as e:
                    print(f"!! EXCEPTION : {e}")


if __name__ == "__main__":
    asyncio.run(main())
