# Decision — one quality system for every Andromeda search

- **Status:** accepted
- **Accepted:** July 13, 2026
- **Applies to:** Andromeda result pages and search APIs

## Decision

The current HTML is a visual starter. Its example answer is fixed, but the real product must not be.

Every **All** search uses the same result-quality pipeline:

1. understand what kind of answer the query needs;
2. retrieve current sources;
3. check important claims against those sources;
4. return structured answer data;
5. render that data with the shared Andromeda result components.

The structured answer can include:

- the answer type, such as a fact, definition, comparison, steps, status, or navigation;
- one short key answer when the sources clearly support it;
- context that prevents the key answer from being misleading;
- answer paragraphs and their citations;
- freshness and uncertainty information;
- normal links and optional image, news, or video blocks.

The purple highlighter is not a decoration added to every response or a wash across the whole key-answer
sentence. It marks only the shortest decisive supported phrase, such as `3.50.4`, when that exact phrase
appears in both the answer and its cited evidence. If the sources disagree, are stale, or do not support a
short answer, Andromeda shows the uncertainty instead of inventing a highlight.

AI Overview appears only in **All**. Images, News, and Videos use their own full result layouts and do
not show the overview. A simple website-finding query may also skip the overview when it adds no value.
`!ai` always skips it for that one search.

## Why

Google uses shared result systems and lets the query decide which result features appear. Its AI
Overview and featured-snippet documentation also says those features appear only when its systems find
them useful. Andromeda follows that product pattern without copying Google's interface.

## Quality gate

Implementation is not complete until tests cover several query shapes, not only the demo query:

- direct factual answer;
- current software or release question;
- comparison;
- how-to steps;
- navigational website lookup;
- conflicting or weak sources;
- `!ai`;
- Images, News, and Videos.

Tests must confirm that citations support the displayed claims, stale data is labeled, unsupported key
answers are not highlighted, and every result type uses the same visual-quality floor.
