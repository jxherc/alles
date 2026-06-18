"""
IterResearch-style deep research engine (ported from odysseus → Tongyi DeepResearch).

iterative Think→Search→Extract→Synthesize loop where the LLM drives every
decision: what to search, what's relevant, what's missing, and when to stop.
rewired to alles services.llm + services.research.search.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from .research_utils import strip_thinking, is_low_quality
from .goal_based_extractor import EXTRACTOR_PROMPT

logger = logging.getLogger("aide.research")


def current_date_context() -> str:
    """grounds query-gen/planning in the real date so the model doesn't emit
    'best X 2025' when it's actually 2026 (training-cutoff drift)."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"When a search query needs a year or refers to 'latest'/'current'/"
        f"'this year', use {now.strftime('%Y')} or relative wording — never a "
        f"year inferred from training data.\n\n"
    )


# ── prompts ─────────────────────────────────────────────────────────────────
RESEARCH_PLAN_PROMPT = """\
You are a research strategist. Before searching, analyze this question and create a research plan.

**Question:** {question}

Break this question down:
1. What are the key sub-topics that need to be covered for a comprehensive answer?
2. What specific data points, facts, or perspectives should we look for?
3. What would a complete, high-quality answer include?

Return a JSON object with:
- "sub_questions": Array of 3-6 specific sub-questions to investigate
- "key_topics": Array of key topics/angles to cover
- "success_criteria": One sentence describing what a complete answer looks like

Example:
{{
  "sub_questions": ["What is the cost of living in X?", "How is the healthcare system?"],
  "key_topics": ["economy", "healthcare", "safety", "culture"],
  "success_criteria": "A balanced comparison covering cost, quality of life, and practical considerations."
}}
"""

QUERY_GEN_PROMPT = """\
You are a research assistant planning web searches.

**Original question:** {question}

**Research plan:**
{research_plan}

**What we know so far:**
{report}

**Round:** {round_num}

Generate {num_queries} focused search queries that will help answer the question.
{round_instruction}

Return ONLY a JSON array of query strings, nothing else.
Example: ["query one", "query two", "query three"]
"""

SYNTHESIZE_PROMPT = """\
You are updating an evolving research report.

**Original question:** {question}

**Current report:**
{report}

**New findings from this round:**
{new_findings}

Integrate the new findings into the existing report. Produce an updated, well-organized \
report that answers the original question as completely as possible given all evidence so far. \
Remove redundancy, resolve contradictions, and maintain logical flow. \
Keep source URLs as inline citations where relevant.

Write only the updated report — no preamble or meta-commentary.
"""

STOP_PROMPT = """\
You are deciding whether a research report is comprehensive enough.

**Original question:** {question}

**Current report:**
{report}

**Rounds completed:** {round_num}

Based on the report so far, do we have enough information to answer the question \
comprehensively?  Consider:
- Are the key aspects of the question addressed?
- Are there obvious gaps or unanswered sub-questions?
- Is the evidence sufficient and from multiple sources?

Reply with ONLY "YES" or "NO" followed by a brief one-sentence reason.
Example: "YES — The report covers all major aspects with evidence from multiple sources."
Example: "NO — We still lack information about the economic impact."
"""

FINAL_REPORT_PROMPT = """\
Write a **long, detailed, comprehensive** research report answering this question:

**Question:** {question}

**All collected evidence and analysis:**
{report}

Requirements:
- Write at MINIMUM 1500 words — this should be a thorough, magazine-quality article
- Use clear ## headings and ### subheadings to organize into logical sections
- Each section should have multiple detailed paragraphs, not just bullet points
- Synthesize and analyze the information — explain WHY things matter, draw comparisons, provide context
- Include specific data points, numbers, and statistics from the evidence
- Include source URLs as inline citations [like this](url)
- Note where sources agree and where they disagree
- Add a brief executive summary at the top
- End with a clear conclusion that directly answers the question
- Write in an engaging, informative style — not dry or robotic
"""

CATEGORY_PROMPTS = {
    "product": """IMPORTANT FORMAT OVERRIDE — this is a PRODUCT research report:
- Structure as a RANKED LIST of products/options (best first)
- For EACH product include: name as ### heading, approximate price, 2-3 sentence summary, **Pros:** bullet list, **Cons:** bullet list, **Where to buy:** URLs as links
- Start with a quick-compare markdown table of top picks (columns: Name, Price, Best For, Rating)
- End with a ## Verdict section picking Best Overall and Best Value
- Still include source citations inline""",
    "comparison": """IMPORTANT FORMAT OVERRIDE — this is a COMPARISON report:
- Create a ## Comparison Table as a markdown table comparing ALL options across key criteria (rows = criteria, columns = options)
- Use checkmarks, ratings, or short values in cells
- Write a ## section per option with its strengths, weaknesses, and ideal use case
- End with ## Best For verdicts (e.g., "**Best for small teams:** Option A because...")
- Include a ## Shared Considerations section for things that apply to all options""",
    "howto": """IMPORTANT FORMAT OVERRIDE — this is a HOW-TO guide:
- Start with ## Quick Guide — a super concise numbered list (one line per step, no details, just the action). Example: 1. Install X  2. Run Y  3. Configure Z
- Then ## Prerequisites listing what's needed before starting
- Then the detailed steps: ## Step 1: ..., ## Step 2: ...
- Each step should have a clear heading and detailed instructions
- Use blockquotes (> ) for tips and warnings: > **Tip:** ... or > **Warning:** ...
- End with ## Common Mistakes section
- Add estimated time and difficulty level near the top""",
    "factcheck": """IMPORTANT FORMAT OVERRIDE — this is a FACT-CHECK report:
- Start with ## The Claim restating what's being checked
- Create ## Evidence For and ## Evidence Against sections
- Each piece of evidence should be a ### with source name, what it found, and how strong the evidence is
- Include a ## Verdict section with one of: **Supported**, **Mixed Evidence**, or **Unsupported**
- End with ## Nuance & Caveats for important context and limitations
- Be balanced and cite sources for every claim""",
}


class DeepResearcher:
    """iterative research engine following the IterResearch pattern."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_rounds: int = 8,
        max_time: int = 300,
        max_urls_per_round: int = 3,
        max_content_chars: int = 15000,
        max_report_tokens: int = 8192,
        extraction_timeout: int = 90,
        extraction_concurrency: int = 3,
        min_rounds: int = 2,
        max_empty_rounds: int = 2,
        synthesis_window: int = 10,
        progress_callback: Optional[Callable] = None,
        search_provider: Optional[str] = None,
        category: Optional[str] = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.search_provider_override = search_provider
        self.category = category
        self.max_rounds = max_rounds
        self.max_time = max_time
        self.max_urls_per_round = max_urls_per_round
        self.max_content_chars = max_content_chars
        self.max_report_tokens = max_report_tokens
        self.extraction_timeout = min(3600, max(15, int(extraction_timeout or 90)))
        self.extraction_concurrency = min(12, max(1, int(extraction_concurrency or 3)))
        self.min_rounds = min_rounds
        self.max_empty_rounds = max_empty_rounds
        self.synthesis_window = synthesis_window
        self._progress = progress_callback
        self._cancelled = False
        self._start_time: float = 0
        self._last_search_error = None
        self.queries_used: Set[str] = set()
        self.urls_fetched: Set[str] = set()
        self.round_count: int = 0
        self.providers_used: List[str] = []
        self.findings: List[Dict] = []
        self.evolving_report: str = ""
        self.research_plan: str = ""

    def cancel(self):
        self._cancelled = True

    # ── public ──────────────────────────────────────────────────────────────
    async def research(
        self,
        question: str,
        prior_report: str = "",
        prior_findings: Optional[List[Dict]] = None,
        prior_urls: Optional[Set[str]] = None,
    ) -> str:
        self._start_time = time.time()
        findings: List[Dict] = list(prior_findings) if prior_findings else []
        report = prior_report or ""

        self._emit(phase="planning")
        self.research_plan = await self._create_plan(question)
        logger.info(f"Research plan: {self.research_plan[:200]}")
        if not self.category and not prior_report:
            self.category = await self._classify_category(question)
            if self.category:
                logger.info(f"Auto-detected category: {self.category}")

        if prior_urls:
            self.urls_fetched.update(prior_urls)
        self.findings = findings
        consecutive_empty_rounds = 0

        for round_num in range(1, self.max_rounds + 1):
            self.round_count = round_num
            if self._cancelled:
                logger.info(f"Research cancelled after {round_num - 1} rounds")
                break
            if self._time_exceeded():
                logger.info(f"Time limit reached after {round_num - 1} rounds")
                break

            logger.info(f"=== Research Round {round_num} ===")
            self._emit(phase="searching", round=round_num, total_sources=len(self.urls_fetched))

            queries = await self._generate_queries(question, report, round_num)
            if not queries:
                logger.warning(f"Round {round_num}: no queries generated, stopping")
                break

            self._emit(
                phase="searching",
                round=round_num,
                queries=len(queries),
                query_preview=queries[0] if queries else "",
                total_sources=len(self.urls_fetched),
            )

            round_findings = await self._search_and_extract(queries, question)
            if round_findings:
                findings.extend(round_findings)
                self.findings = findings
                consecutive_empty_rounds = 0
                logger.info(f"Round {round_num}: extracted {len(round_findings)} findings")
                self._emit(
                    phase="reading",
                    round=round_num,
                    new_sources=len(round_findings),
                    total_sources=len(self.urls_fetched),
                    total_findings=len(findings),
                )
            else:
                consecutive_empty_rounds += 1
                logger.info(
                    f"Round {round_num}: no new findings ({consecutive_empty_rounds} consecutive empty)"
                )
                if consecutive_empty_rounds >= self.max_empty_rounds:
                    err_detail = self._last_search_error or "unknown error"
                    self._emit(phase="error", message=f"Search engine unavailable: {err_detail}")
                    if not findings:
                        return (
                            f"**Search unavailable** — Web search failed after "
                            f"{round_num} rounds. Error: {err_detail}\n\n"
                            "Please check your search provider settings and ensure the service is running."
                        )
                    break

            if findings:
                self._emit(
                    phase="analyzing",
                    round=round_num,
                    total_sources=len(self.urls_fetched),
                    total_findings=len(findings),
                )
                report = await self._synthesize(question, findings, report)

            if round_num >= self.min_rounds:
                if await self._should_stop(question, report, round_num):
                    logger.info(f"LLM decided to stop after round {round_num}")
                    break

        self._emit(
            phase="writing", total_sources=len(self.urls_fetched), total_findings=len(findings)
        )
        if not report:
            if findings:
                logger.warning(
                    "Synthesis produced no report; returning %d findings as fallback", len(findings)
                )
                return self._fallback_report(question, findings)
            return "No information could be gathered for this question."

        self.evolving_report = report
        final = await self._final_report(question, report)
        elapsed = time.time() - self._start_time
        logger.info(
            f"Research complete: {self.round_count} rounds, {len(findings)} findings, "
            f"{len(self.urls_fetched)} URLs, {elapsed:.1f}s"
        )
        return final

    # ── llm ─────────────────────────────────────────────────────────────────
    async def _llm(
        self,
        messages: List[Dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: int = 60,
    ) -> str:
        """accumulate a non-streaming completion off alles' stream_chat, strip thinking.
        timeout is advisory — stream_chat carries its own httpx read timeout."""
        from services.llm import stream_chat

        out = []
        async for ch in stream_chat(
            messages,
            self.base_url,
            self.api_key,
            self.model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if "delta" in ch:
                out.append(ch["delta"])
            elif "error" in ch:
                raise RuntimeError(ch["error"])
            elif ch.get("done"):
                break
        return strip_thinking("".join(out).strip()) or ""

    # ── plan ────────────────────────────────────────────────────────────────
    async def _create_plan(self, question: str) -> str:
        prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=1024, timeout=30
            )
            parsed = self._parse_json_object(response)
            if parsed:
                parts = []
                if parsed.get("sub_questions"):
                    parts.append("Sub-questions: " + "; ".join(parsed["sub_questions"]))
                if parsed.get("key_topics"):
                    parts.append("Key topics: " + ", ".join(parsed["key_topics"]))
                if parsed.get("success_criteria"):
                    parts.append("Success: " + parsed["success_criteria"])
                return "\n".join(parts) if parts else response
            return response
        except Exception as e:
            logger.warning(f"Research planning failed: {e}")
            self._emit(
                phase="warning", message="Planning step failed, proceeding with direct search"
            )
            return ""

    async def _classify_category(self, question: str) -> Optional[str]:
        valid = ", ".join(CATEGORY_PROMPTS.keys())
        prompt = (
            f"Classify this research question into exactly ONE category.\n"
            f"Categories: {valid}\n"
            f"If none fit well, respond with: general\n\n"
            f"Question: {question}\n\n"
            f"Respond with ONLY the category name, nothing else."
        )
        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}], temperature=0, max_tokens=20, timeout=15
            )
            cat = (result or "").strip().lower()
            first = cat.split()[0].strip(".,\"'*:") if cat.split() else ""
            if first in CATEGORY_PROMPTS:
                return first
            for c in CATEGORY_PROMPTS:
                if c in cat:
                    return c
            return None
        except Exception as e:
            logger.warning(f"Category classification failed: {e}")
            return None

    # ── think ───────────────────────────────────────────────────────────────
    async def _generate_queries(self, question: str, report: str, round_num: int) -> List[str]:
        if round_num == 1:
            num_queries = 4
            round_instruction = (
                "This is the first round — generate broad, diverse queries "
                "that explore the key facets of the question."
            )
        else:
            num_queries = 3
            round_instruction = (
                "We already have partial findings.  Generate targeted follow-up "
                "queries to fill gaps, verify claims, or explore specific aspects "
                "that the report doesn't yet cover well."
            )

        prompt = current_date_context() + QUERY_GEN_PROMPT.format(
            question=question,
            research_plan=self.research_plan or "(No plan — search broadly.)",
            report=report or "(No findings yet.)",
            round_num=round_num,
            num_queries=num_queries,
            round_instruction=round_instruction,
        )
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}], temperature=0.5, max_tokens=4096
            )
            queries = self._parse_json_array(response)
            new_queries = [q for q in queries if q not in self.queries_used]
            self.queries_used.update(new_queries)
            logger.info(f"Round {round_num} queries: {new_queries}")
            return new_queries
        except Exception as e:
            logger.error(f"Query generation failed: {e}")
            self._emit(phase="warning", message=f"Query generation failed: {e}")
            return []

    # ── search + extract ────────────────────────────────────────────────────
    async def _search_and_extract(self, queries: List[str], question: str) -> List[Dict]:
        all_findings: List[Dict] = []

        search_results = await asyncio.gather(
            *[self._search(q) for q in queries], return_exceptions=True
        )
        urls_to_fetch = []
        for result in search_results:
            if isinstance(result, Exception):
                logger.warning(f"Search error: {result}")
                continue
            if not result:
                continue
            for r in result:
                url = r.get("url", "")
                if url and url not in self.urls_fetched:
                    urls_to_fetch.append(r)
                    self.urls_fetched.add(url)
                if len(urls_to_fetch) >= self.max_urls_per_round * len(queries):
                    break

        if self._cancelled or self._time_exceeded():
            return all_findings

        semaphore = asyncio.Semaphore(self.extraction_concurrency)

        async def _bounded_extract(result: Dict) -> Optional[Dict]:
            async with semaphore:
                return await self._fetch_and_extract(
                    result["url"], question, result.get("title", "")
                )

        results_gathered = await asyncio.gather(
            *[_bounded_extract(r) for r in urls_to_fetch], return_exceptions=True
        )
        for result in results_gathered:
            if isinstance(result, Exception):
                logger.warning(f"Extraction error: {result}")
                continue
            if result:
                all_findings.append(result)
        return all_findings

    async def _search(self, query: str) -> List[Dict]:
        try:
            from .search import search_chain

            results, prov, err = await search_chain(query, self.search_provider_override, 10)
            if results:
                if prov and prov not in self.providers_used:
                    self.providers_used.append(prov)
                logger.info(f"Research search: {prov} returned {len(results)} results")
                return results
            if err:
                self._last_search_error = err
            return []
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            self._last_search_error = str(e)
            return []

    async def _fetch_and_extract(self, url: str, question: str, title: str) -> Optional[Dict]:
        display = title or url
        self._emit(phase="reading", url=url, title=display, total_sources=len(self.urls_fetched))
        try:
            from .search import fetch_webpage_content

            page = await asyncio.to_thread(fetch_webpage_content, url, 10)
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

        if not page.get("success") or not page.get("content"):
            return None

        content = page["content"]
        if len(content) > self.max_content_chars:
            truncated = content[: self.max_content_chars]
            last_para = truncated.rfind("\n\n")
            content = (
                truncated[:last_para] if last_para > self.max_content_chars * 0.8 else truncated
            )

        prompt = EXTRACTOR_PROMPT.format(webpage_content=content, goal=question)
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
                timeout=self.extraction_timeout,
            )
            parsed = self._parse_json_object(response)
            if parsed:
                parsed["url"] = url
                parsed["title"] = title or page.get("title", "")
                parsed["og_image"] = page.get("og_image", "")
                if is_low_quality(parsed.get("summary", "")):
                    logger.info(f"Skipping low-quality extraction from {url}")
                    return None
                return parsed
            return {
                "url": url,
                "title": title or page.get("title", ""),
                "og_image": page.get("og_image", ""),
                "rational": "LLM extraction (raw)",
                "evidence": response[:3000],
                "summary": response[:500],
            }
        except Exception as e:
            logger.warning(f"LLM extraction failed for {url}: {e}")
            return None

    # ── synthesize ──────────────────────────────────────────────────────────
    async def _synthesize(self, question: str, findings: List[Dict], current_report: str) -> str:
        window = findings[-self.synthesis_window :]
        if len(findings) > self.synthesis_window:
            logger.info(f"Synthesis using last {self.synthesis_window} of {len(findings)} findings")
        findings_text = self._format_findings(window)
        prompt = SYNTHESIZE_PROMPT.format(
            question=question,
            report=current_report or "(First round — no report yet.)",
            new_findings=findings_text,
        )
        try:
            return await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=180,
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            self._emit(phase="warning", message="Synthesis failed, keeping previous report")
            return current_report

    # ── decide ──────────────────────────────────────────────────────────────
    async def _should_stop(self, question: str, report: str, round_num: int) -> bool:
        prompt = STOP_PROMPT.format(question=question, report=report, round_num=round_num)
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=128
            )
            clean = strip_thinking(response).strip()
            answer = re.sub(r'^[\s*_`"\'>#\-]+', "", clean).upper()
            should_stop = answer.startswith("YES")
            logger.info(f"Stop decision (round {round_num}): {clean[:120]}")
            return should_stop
        except Exception as e:
            logger.warning(f"Stop decision failed: {e}")
            return False

    # ── final report ────────────────────────────────────────────────────────
    async def _final_report(self, question: str, report: str) -> str:
        prompt = FINAL_REPORT_PROMPT.format(question=question, report=report)
        cat_extra = CATEGORY_PROMPTS.get(self.category or "", "")
        if cat_extra:
            prompt += "\n\n" + cat_extra
        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=180,
            )
            if len(result.split()) < 400:
                logger.info(f"Final report too short ({len(result.split())} words), expanding")
                self._emit(phase="writing", message="Expanding report...")
                expanded = await self._llm(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": result},
                        {
                            "role": "user",
                            "content": "This report is too brief. Please expand it significantly:\n"
                            "- Add detailed paragraphs for each section (not just bullet points)\n"
                            "- Include specific data, numbers, and comparisons from the evidence\n"
                            "- Explain context and significance — don't just list facts\n"
                            "- Use ## headings and ### subheadings\n"
                            "- Target at least 1000 words\n"
                            "Write the full expanded report now.",
                        },
                    ],
                    temperature=0.4,
                    max_tokens=self.max_report_tokens,
                    timeout=180,
                )
                if len(expanded.split()) > len(result.split()):
                    return expanded
            return result
        except Exception as e:
            logger.error(f"Final report generation failed: {e}")
            return report

    # ── helpers ─────────────────────────────────────────────────────────────
    def _emit(self, **kwargs):
        if self._progress:
            try:
                self._progress(kwargs)
            except Exception:
                pass

    def _time_exceeded(self) -> bool:
        return (time.time() - self._start_time) > self.max_time

    @staticmethod
    def _strip_code_block(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _parse_json_array(self, text: str) -> List[str]:
        text = self._strip_code_block(text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        # truncated array — repair from the LAST '[' so an echoed example isn't harvested
        last_start = text.rfind("[")
        if last_start != -1 and "]" not in text[last_start:]:
            complete_items = re.findall(r'"([^"]*)"', text[last_start:])
            if complete_items:
                return complete_items
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass
        # multiple arrays (echoed example + real one) — keep the LAST parseable
        last_parsed = None
        for m in re.finditer(r"\[[\s\S]*?\]", text):
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    last_parsed = parsed
            except json.JSONDecodeError:
                continue
        if last_parsed is not None:
            return [str(item) for item in last_parsed]
        arr_start = text.find("[")
        if arr_start != -1:
            complete_items = re.findall(r'"([^"]*)"', text[arr_start:])
            if complete_items:
                return complete_items
        logger.warning(f"Could not parse JSON array from: {text[:200]}")
        return []

    def _parse_json_object(self, text: str) -> Optional[Dict]:
        text = self._strip_code_block(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _format_findings(self, findings: List[Dict]) -> str:
        parts = []
        for i, f in enumerate(findings, 1):
            url = f.get("url", "unknown")
            title = f.get("title", "")
            summary = f.get("summary", "")
            evidence = f.get("evidence", "")
            content = summary if summary else (evidence[:1000] if evidence else "(no content)")
            parts.append(f"**Finding {i}** — [{title}]({url})\n{content}")
        return "\n\n".join(parts)

    def _fallback_report(self, question: str, findings: List[Dict]) -> str:
        return (
            f"# {question}\n\n"
            "_Automatic synthesis did not complete, so this report lists the "
            f"{len(findings)} finding(s) gathered during research._\n\n"
            f"{self._format_findings(findings)}"
        )

    def get_stats(self) -> Dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
            "Model": self.model,
        }
        if self.providers_used:
            stats["Search"] = ", ".join(self.providers_used)
        if self.category:
            stats["Category"] = self.category.capitalize()
        return stats
