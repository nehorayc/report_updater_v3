from duckduckgo_search import DDGS
import os
from typing import List, Dict

from logger_config import setup_logger
import time

logger = setup_logger("ResearchAgent")

def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Performs a web search using DuckDuckGo.
    """
    logger.info(f"Performing web search for: '{query}' (max_results={max_results})")
    results = []
    start_time = time.time()
    try:
        with DDGS() as ddgs:
            # text search
            ddgs_gen = ddgs.text(query, max_results=max_results)
            for r in ddgs_gen:
                results.append({
                    "title": r.get('title', ''),
                    "url": r.get('href', ''),
                    "snippet": r.get('body', ''),
                    "source": "web"
                })
        latency = time.time() - start_time
        logger.info(f"Web search complete. Found {len(results)} results in {latency:.2f}s.")
    except Exception as e:
        logger.error(f"Web search error for query '{query}': {e}", exc_info=True)
    return results

def search_internal(query: str, reference_docs: List[str]) -> List[Dict[str, str]]:
    """
    Simulated internal search.
    """
    logger.info(f"Performing internal search for: '{query}' in {len(reference_docs)} docs.")
    results = []
    # Simplified version
    for doc_path in reference_docs:
        if os.path.exists(doc_path):
            try:
                with open(doc_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if query.lower() in content.lower():
                        results.append({
                            "title": os.path.basename(doc_path),
                            "snippet": f"Found match in {os.path.basename(doc_path)} for '{query}'",
                            "source": "internal"
                        })
            except Exception as e:
                logger.error(f"Error reading doc {doc_path}: {e}")
    
    logger.info(f"Internal search complete. Found {len(results)} matches.")
    return results

def perform_comprehensive_research(blueprint: Dict) -> List[Dict]:
    """
    Combines web and internal research based on keywords.
    """
    topic = blueprint.get("topic", "")
    keywords = blueprint.get("keywords", [])
    ref_paths = blueprint.get("ref_paths", []) # Added support for uploaded docs
    
    logger.info(f"Orchestrating comprehensive research for topic: '{topic}'")
    all_findings = []
    
    # 1. Internal Search (if reference docs exist)
    if ref_paths:
        for kw in keywords[:3]:
            all_findings.extend(search_internal(kw, ref_paths))
    
    # 2. Web Search
    # Heuristic: If topic is generic (e.g. "Introduction"), skip it as a query
    generic_topics = ["introduction", "conclusion", "summary", "abstract", "foreword", "appendix"]
    queries = []
    
    if topic.lower().strip() not in generic_topics and len(topic.split()) > 1:
        queries.append(topic)
    
    # Add keywords (up to 4 for more depth)
    for kw in keywords:
        if kw not in queries:
            queries.append(kw)
    
    # Limit to top 4 queries total to avoid rate limiting
    final_queries = queries[:4]
    if not final_queries and topic: # Fallback if everything was filtered out
        final_queries = [topic]

    for q in final_queries:
        res = search_web(q)
        if res:
            all_findings.extend(res)
        else:
            # Try a slightly broader version if 0 results
            if len(q.split()) > 2:
                broad_q = " ".join(q.split()[:2])
                logger.info(f"Retrying with broader query: {broad_q}")
                all_findings.extend(search_web(broad_q, max_results=3))
        
    logger.info(f"Comprehensive research complete. Total findings: {len(all_findings)}")
    unique_findings = []
    seen_urls = set()
    for f in all_findings:
        if f.get('url') and f['url'] not in seen_urls:
            unique_findings.append(f)
            seen_urls.add(f['url'])
        elif not f.get('url'): # Internal docs or similar
            unique_findings.append(f)
            
    return unique_findings[:15] # Return top 15 results

if __name__ == "__main__":
    test_blueprint = {"topic": "AI in healthcare trends 2024", "keywords": ["Mayo Clinic AI", "FDA approved AI 2024"]}
    findings = perform_comprehensive_research(test_blueprint)
    for f in findings:
        print(f"[{f['source']}] {f['title']}: {f['url']}")
