# Model Comparison Report

**Date:** 2026-03-07
**Host:** DGX Spark (NVIDIA GB10, 128 GB unified memory, aarch64)
**Models tested:** qwen3:32b (Ollama local), devstral-small-2 (Ollama local), gemini-3-flash-preview (Google API)
**Test method:** Playwright → Streamlit UI → PydanticAI agent → ChromaDB tools
**Questions:** 5 identical questions per model

---

## Performance Summary

| Model | Avg Time | Min | Max | Avg Words | Type |
|-------|----------|-----|-----|-----------|------|
| **gemini-3-flash-preview** | **23.0s** | 13.0s | 33.1s | **301** | Cloud API |
| **devstral-small-2** | **32.1s** | 18.0s | 73.2s | **73** | Local (15 GB) |
| **qwen3:32b** | **206.7s** | 78.4s | 278.8s | **448** | Local (20 GB) |

## Per-Question Timing

| # | Question | gemini-3-flash | devstral-small-2 | qwen3:32b |
|---|----------|----------------|-------------------|-----------|
| 1 | Cheapest S&P 500 ETFs — compare costs | **33.1s** | 73.2s | 253.7s |
| 2 | European government bond ETFs + risk levels | **28.1s** | 28.1s | 278.8s |
| 3 | Compare iShares MSCI World vs Vanguard All-World | **23.0s** | 23.1s | 253.9s |
| 4 | Highest risk ETFs (level 7) — what do they invest in? | **18.0s** | 18.1s | 168.7s |
| 5 | How many providers + fund counts? | **13.0s** | 18.0s | 78.4s |

---

## Quality Assessment

### Q1: "What are the cheapest S&P 500 ETFs available? Compare their total costs."

| Criterion | gemini-3-flash | qwen3:32b | devstral-small-2 |
|-----------|----------------|-----------|-------------------|
| **ETFs found** | 5 ETFs across 3 providers (SPDR, Xtrackers, Vanguard) | 7+ ETFs but only Xtrackers | 2 Xtrackers ETFs only |
| **Cost accuracy** | Correct — SPDR at 0.03%, Xtrackers Swap at 0.04%, Vanguard at 0.07% | Correct for Xtrackers, missed cheaper SPDR | Showed 0.05% — missed cheaper options |
| **Cross-provider** | Yes — compared across providers | No — only Xtrackers results | No — only Xtrackers |
| **Visualisation** | Generated a chart (bar chart of costs) | No chart | No chart |
| **Analysis depth** | Concise but complete with key takeaways | Very detailed with investor profiles and caveats | Basic table only |
| **Score** | **9/10** | **7/10** (thorough but single-provider) | **4/10** |

### Q2: "Which ETFs focus on European government bonds? List them with their risk levels."

| Criterion | gemini-3-flash | qwen3:32b | devstral-small-2 |
|-----------|----------------|-----------|-------------------|
| **Relevance** | **European gov bonds** — exactly what was asked | US Treasury bonds — wrong region | US TIPS only — wrong region and type |
| **ETFs found** | 12 ETFs (Eurozone + UK Gilts) with ISINs, risk levels, strategies | 3 US bond ETFs | 1 US inflation ETF |
| **Organisation** | Grouped by Eurozone vs UK, table format with strategy column | General comparison table | Single paragraph description |
| **Insights** | Risk vs maturity explanation, ESG/Green bond options noted | Use cases and investor considerations | None |
| **Score** | **10/10** | **4/10** (wrong region) | **2/10** (wrong everything) |

### Q3: "Compare iShares Core MSCI World (IE00B4L5Y983) vs Vanguard FTSE All-World (IE00BK5BQT80)"

| Criterion | gemini-3-flash | qwen3:32b | devstral-small-2 |
|-----------|----------------|-----------|-------------------|
| **Both ETFs retrieved** | Yes — looked up both ISINs | Only Vanguard — missed iShares | Neither — "couldn't find matching funds" |
| **Side-by-side comparison** | Full comparison table (index, coverage, costs, replication, dividends) | No comparison — only described one fund | Complete failure |
| **Key differences** | Developed-only vs Developed+Emerging, 0.20% vs 0.22% costs | Only Vanguard data presented | N/A |
| **Recommendation** | Clear guidance on when to choose each | None | None |
| **Score** | **10/10** | **5/10** | **0/10** |

### Q4: "What are the highest risk ETFs (risk level 7) and what do they invest in?"

| Criterion | gemini-3-flash | qwen3:32b | devstral-small-2 |
|-----------|----------------|-----------|-------------------|
| **Correct result** | Found Ethereum ETC, correct ISIN | Found same ETC, correct ISIN | Found same ETC |
| **Explanation depth** | Detailed: why risk 7, physical backing, volatility, regulatory risks, intended investor | Brief: 2 sentences | Brief: 3 sentences |
| **Additional context** | Technical/operational risks, stress scenarios, no principal protection | Offered to look up more | Added product type context |
| **Score** | **10/10** | **8/10** | **7/10** |

### Q5: "How many ETF providers are in the database and how many funds does each have?"

| Criterion | gemini-3-flash | qwen3:32b | devstral-small-2 |
|-----------|----------------|-----------|-------------------|
| **Accuracy** | Correct (492, 412, 386, 153) | Correct | Correct |
| **Visualisation** | Generated a bar chart | No chart | No chart |
| **Presentation** | Chart + brief summary with context | List + total + commentary | List + total only |
| **Score** | **10/10** | **10/10** | **9/10** |

---

## Overall Scores

| Model | Q1 | Q2 | Q3 | Q4 | Q5 | **Average** | **Avg Time** |
|-------|----|----|----|----|----|----|-----|
| **gemini-3-flash-preview** | 9 | 10 | 10 | 10 | 10 | **9.8/10** | **23.0s** |
| **qwen3:32b** | 7 | 4 | 5 | 8 | 10 | **6.8/10** | **206.7s** |
| **devstral-small-2** | 4 | 2 | 0 | 7 | 9 | **4.4/10** | **32.1s** |

---

## Key Findings

### gemini-3-flash-preview (Google Cloud API)
- **Quality:** 9.8/10 — outstanding across all question types
- **Speed:** 23s average — fastest of all three
- **Strengths:** Reliable tool calling, multi-provider search results, generates charts automatically, provides structured comparisons with tables, always answers the actual question asked
- **Weaknesses:** Requires internet + API key, cloud dependency, potential cost at scale
- **Verdict:** Best overall by a wide margin in both quality AND speed

### qwen3:32b (Ollama local, 20 GB)
- **Quality:** 6.8/10 — good analysis depth but misses the point on some questions
- **Speed:** 207s average — painfully slow (9x slower than Gemini)
- **Strengths:** Very thorough analysis when it finds the right documents, good formatting
- **Weaknesses:** Often searches too narrowly (single provider), sometimes returns wrong region (US vs European), slow tool-calling loop
- **Verdict:** Decent quality but too slow for interactive use

### devstral-small-2 (Ollama local, 15 GB)
- **Quality:** 4.4/10 — unreliable, fails on complex queries
- **Speed:** 32s average — fast locally
- **Strengths:** Quick responses for simple factual queries
- **Weaknesses:** Fails on ISIN lookups, returns wrong asset classes, gives up on comparisons
- **Verdict:** Not suitable for this use case

### nemotron-3-nano:30b
- **Status:** Download incomplete. Not tested.

---

## Verdict

| Rank | Model | Speed | Quality | Tool Calling | Charts | Cost |
|------|-------|-------|---------|--------------|--------|------|
| **1** | **gemini-3-flash-preview** | 23s | 9.8/10 | Excellent | Yes | API fees |
| **2** | qwen3:32b | 207s | 6.8/10 | Good | No | Free (local) |
| **3** | devstral-small-2 | 32s | 4.4/10 | Poor | No | Free (local) |

**Recommendation:** Use **gemini-3-flash-preview** as the default model. It's 9x faster than qwen3:32b, produces dramatically better answers, reliably calls all tools, generates charts, and correctly handles multi-ETF comparisons. The only trade-off is cloud API dependency and cost.

If a local/offline model is required, qwen3:32b is the only viable option but expect 3-4 minute response times. Nemotron-3-nano:30b should still be tested when available — it may offer a better local speed/quality balance.
