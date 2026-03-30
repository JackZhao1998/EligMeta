"""Browser-driven Drugs.com agent for condition medication discovery."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - runtime dependency
    sync_playwright = None

_WHITESPACE_PATTERN = re.compile(r"\s+")
_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_SYSTEMIC_SUFFIX_PATTERN = re.compile(r"\s+systemic$", re.IGNORECASE)


class DrugsComAgentError(RuntimeError):
    """Raised when the Drugs.com agent cannot complete a retrieval."""


def _normalize_space(value: Optional[str]) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _normalize_match_text(value: Optional[str]) -> str:
    return _NON_ALNUM_PATTERN.sub(" ", str(value or "").strip().lower()).strip()


def _slugify(value: Optional[str]) -> str:
    return _NON_ALNUM_PATTERN.sub("_", str(value or "").strip().lower()).strip("_")


def _unique_strings(values: List[Optional[str]]) -> List[str]:
    cleaned_values: List[str] = []
    seen = set()
    for value in values:
        cleaned = _normalize_space(value)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned_values.append(cleaned)
    return cleaned_values


def _split_names(value: Optional[str]) -> List[str]:
    raw = _normalize_space(value)
    if not raw:
        return []
    return _unique_strings(re.split(r"[;,]", raw))


def _split_aliases(value: Optional[str]) -> List[str]:
    raw = _normalize_space(value)
    if not raw:
        return []
    if ";" in raw:
        return _unique_strings(raw.split(";"))
    return _unique_strings(raw.split(","))


def _clean_generic_name(value: Optional[str]) -> str:
    generic_name = _normalize_space(value)
    generic_name = _SYSTEMIC_SUFFIX_PATTERN.sub("", generic_name).strip()
    return generic_name


class DrugsComConditionAgent:
    """A lightweight observe-think-act browser agent for Drugs.com searches."""

    SEARCH_PAGE_URL = "https://www.drugs.com/search.php"

    def __init__(
        self,
        headless: bool = True,
        max_steps: int = 6,
        timeout_ms: int = 60000,
    ) -> None:
        self.headless = headless
        self.max_steps = max_steps
        self.timeout_ms = timeout_ms
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        )

    def fetch_condition_library(self, query: str) -> Dict[str, Any]:
        if sync_playwright is None:
            raise DrugsComAgentError(
                "Playwright is not installed. Install it with 'pip install playwright'."
            )

        normalized_query = _normalize_space(query)
        if not normalized_query:
            raise DrugsComAgentError("A non-empty condition query is required.")

        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            context = browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1365, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(
                self.SEARCH_PAGE_URL,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )

            state: Dict[str, Any] = {
                "query": normalized_query,
                "search_submitted": False,
                "selected_result_url": "",
                "search_results_url": "",
                "condition_aliases": [],
                "trace": [],
            }

            try:
                for step_number in range(1, self.max_steps + 1):
                    observation = self._observe(page)
                    action = self._decide_next_action(state, observation)
                    state["trace"].append(
                        {
                            "step": step_number,
                            "url": observation["url"],
                            "title": observation["title"],
                            "observation": observation["summary"],
                            "action": action,
                        }
                    )

                    if action["type"] == "search":
                        self._execute_search(page, normalized_query)
                        state["search_submitted"] = True
                        state["search_results_url"] = page.url
                        continue

                    if action["type"] == "open_condition_result":
                        target_url = action["target_url"]
                        page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=self.timeout_ms,
                        )
                        state["selected_result_url"] = target_url
                        continue

                    if action["type"] == "view_all_results":
                        state["condition_aliases"] = self._extract_condition_aliases(page)
                        target_url = action["target_url"]
                        page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=self.timeout_ms,
                        )
                        continue

                    if action["type"] == "parse_medications":
                        library_payload = self._parse_condition_page(
                            page,
                            normalized_query,
                            state.get("condition_aliases", []),
                        )
                        library_payload["source"].update(
                            {
                                "search_url": state.get("search_results_url")
                                or f"{self.SEARCH_PAGE_URL}?searchterm={quote_plus(normalized_query)}",
                                "agent_trace": list(state["trace"]),
                            }
                        )
                        return library_payload

                    if action["type"] == "stop":
                        raise DrugsComAgentError(action["reason"])

                raise DrugsComAgentError(
                    f"Could not resolve a Drugs.com medication list for '{normalized_query}' "
                    f"within {self.max_steps} steps."
                )
            finally:
                context.close()
                browser.close()

    def _launch_browser(self, playwright: Any) -> Any:
        launch_options = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        for channel in ("msedge", "chrome"):
            try:
                return playwright.chromium.launch(channel=channel, **launch_options)
            except Exception:
                continue
        try:
            return playwright.chromium.launch(**launch_options)
        except Exception as exc:
            raise DrugsComAgentError(
                "Unable to launch a Chromium browser for Drugs.com automation."
            ) from exc

    def _observe(self, page: Any) -> Dict[str, Any]:
        title = page.title()
        url = page.url
        has_search_box = page.locator('input[name="searchterm"]').count() > 0
        search_value = ""
        if has_search_box:
            try:
                search_value = _normalize_space(
                    page.locator('input[name="searchterm"]').first.input_value()
                )
            except Exception:
                search_value = ""

        candidate_links: List[Dict[str, str]] = []
        try:
            candidate_links = page.locator("main a").evaluate_all(
                """
                (els) => els
                  .map((el) => ({
                    text: (el.innerText || "").replace(/\\s+/g, " ").trim(),
                    href: el.href || ""
                  }))
                  .filter((item) => item.text && item.href)
                """
            )
        except Exception:
            candidate_links = []

        row_count = page.locator("tr.ddc-table-row-medication").count()
        view_all_links = [
            link
            for link in candidate_links
            if "view all results on one page" in link["text"].lower()
        ]
        heading = ""
        if page.locator("h1").count():
            heading = _normalize_space(page.locator("h1").first.inner_text())

        body_excerpt = ""
        try:
            body_excerpt = _normalize_space(page.locator("body").inner_text())[:500]
        except Exception:
            body_excerpt = ""

        summary_parts = [
            f"title={title or 'Unknown'}",
            f"url={url}",
            f"search_box={'yes' if has_search_box else 'no'}",
        ]
        if heading:
            summary_parts.append(f"heading={heading}")
        if search_value:
            summary_parts.append(f"query={search_value}")
        if row_count:
            summary_parts.append(f"rows={row_count}")
        if view_all_links:
            summary_parts.append("view_all=yes")

        return {
            "title": title,
            "url": url,
            "heading": heading,
            "has_search_box": has_search_box,
            "search_value": search_value,
            "candidate_links": candidate_links,
            "row_count": row_count,
            "view_all_url": view_all_links[0]["href"] if view_all_links else "",
            "is_search_results": "/search.php" in url and "searchterm=" in url,
            "is_condition_page": "/condition/" in url,
            "is_page_all": "page_all=1" in url,
            "summary": "; ".join(summary_parts),
            "body_excerpt": body_excerpt,
        }

    def _decide_next_action(
        self,
        state: Dict[str, Any],
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not state["search_submitted"] and observation["has_search_box"]:
            return {
                "type": "search",
                "query": state["query"],
                "reason": "Search the Drugs.com catalog using the condition query.",
            }

        if observation["is_search_results"]:
            chosen_result = self._pick_condition_result(
                state["query"],
                observation["candidate_links"],
            )
            if chosen_result:
                return {
                    "type": "open_condition_result",
                    "target_url": chosen_result["href"],
                    "label": chosen_result["text"],
                    "reason": "Open the best matching condition medication page from search results.",
                }
            return {
                "type": "stop",
                "reason": (
                    f"No suitable Drugs.com condition result was found for '{state['query']}'."
                ),
            }

        if observation["is_condition_page"] and observation["view_all_url"] and not observation["is_page_all"]:
            return {
                "type": "view_all_results",
                "target_url": observation["view_all_url"],
                "reason": "Open the one-page medication table before parsing.",
            }

        if observation["is_condition_page"] and observation["row_count"] > 0:
            return {
                "type": "parse_medications",
                "reason": "The medication table is visible and ready to parse.",
            }

        return {
            "type": "stop",
            "reason": (
                f"Unexpected Drugs.com page state while searching for '{state['query']}': "
                f"{observation['summary']}"
            ),
        }

    def _execute_search(self, page: Any, query: str) -> None:
        page.locator('input[name="searchterm"]').first.fill(query)
        page.locator('button[type="submit"]').first.click()
        page.wait_for_url("**/search.php?searchterm=*", timeout=self.timeout_ms)
        page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)

    def _pick_condition_result(
        self,
        query: str,
        candidate_links: List[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        normalized_query = _normalize_match_text(query)
        query_tokens = set(normalized_query.split())

        best_link: Optional[Dict[str, str]] = None
        best_score = -1

        for link in candidate_links:
            href = link.get("href", "")
            text = _normalize_space(link.get("text"))
            normalized_text = _normalize_match_text(text)
            if "/condition/" not in href:
                continue
            if re.search(r"/condition/[a-z0-9]\.html$", href):
                continue

            score = 0
            if normalized_query and normalized_query in normalized_text:
                score += 80
            if "medications" in normalized_text:
                score += 30
            if "treatment options" in normalized_text:
                score += 20
            if normalized_query and _slugify(query) in href.lower():
                score += 40
            if query_tokens:
                score += len(query_tokens & set(normalized_text.split())) * 10

            if score > best_score:
                best_score = score
                best_link = {
                    "text": text,
                    "href": href,
                }

        return best_link

    def _parse_condition_page(
        self,
        page: Any,
        query: str,
        seed_aliases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        heading = ""
        if page.locator("h1").count():
            heading = _normalize_space(page.locator("h1").first.inner_text())

        condition_label = re.sub(r"^Medications for\s+", "", heading, flags=re.IGNORECASE).strip()
        if not condition_label:
            title = _normalize_space(page.title())
            match = re.search(r"List of \d+\s+(.*?)\s+Medications Compared", title, re.IGNORECASE)
            if match:
                condition_label = _normalize_space(match.group(1))
        if not condition_label:
            condition_label = _normalize_space(query)

        other_names = self._extract_condition_aliases(page)

        medication_rows = page.locator("tr.ddc-table-row-medication").evaluate_all(
            """
            (els) => els.map((el) => {
              const info = el.nextElementSibling;
              const pairs = {};
              if (info) {
                const dts = Array.from(info.querySelectorAll("dt"));
                const dds = Array.from(info.querySelectorAll("dd"));
                dts.forEach((dt, index) => {
                  const key = (dt.innerText || "").replace(/:\\s*$/, "").trim();
                  const value = (dds[index]?.innerText || "").replace(/\\s+/g, " ").trim();
                  if (key) {
                    pairs[key] = value;
                  }
                });
              }
              return {
                display_name: (el.querySelector("th a")?.innerText || "").replace(/\\s+/g, " ").trim(),
                details: pairs,
              };
            })
            """
        )

        drugs: List[str] = []
        for row in medication_rows:
            details = row.get("details", {})
            if str(details.get("Off-label", "")).strip().lower() == "yes":
                continue

            display_name = _normalize_space(row.get("display_name"))
            generic_name = _clean_generic_name(details.get("Generic name"))
            brand_names = _split_names(details.get("Brand name")) + _split_names(
                details.get("Brand names")
            )

            drugs.extend([display_name, generic_name, *brand_names])

        approved_drugs = _unique_strings(drugs)
        if not approved_drugs:
            raise DrugsComAgentError(
                f"Drugs.com returned a medication page for '{query}', but no approved drugs were parsed."
            )

        page_url = page.url
        url_slug_match = re.search(r"/condition/([^/?#]+)\.html", page_url, re.IGNORECASE)
        library_key = _slugify(url_slug_match.group(1) if url_slug_match else condition_label)

        aliases = _unique_strings([condition_label, query, *(seed_aliases or []), *other_names])
        return {
            "library_key": library_key,
            "label": condition_label,
            "aliases": aliases,
            "drugs": approved_drugs,
            "source": {
                "site": "Drugs.com",
                "source_url": page_url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _extract_condition_aliases(self, page: Any) -> List[str]:
        try:
            other_name_paragraphs = page.locator("p").evaluate_all(
                """
                (els) => els
                  .map((el) => (el.innerText || "").replace(/\\s+/g, " ").trim())
                  .filter((text) => text.toLowerCase().startsWith("other names:"))
                """
            )
            if other_name_paragraphs:
                other_names_text = re.sub(
                    r"^Other names:\s*",
                    "",
                    other_name_paragraphs[0],
                    flags=re.IGNORECASE,
                ).strip()
                return _split_aliases(other_names_text)
        except Exception:
            return []
        return []


def fetch_drugs_com_condition_library(
    query: str,
    headless: bool = True,
) -> Dict[str, Any]:
    agent = DrugsComConditionAgent(headless=headless)
    return agent.fetch_condition_library(query)
