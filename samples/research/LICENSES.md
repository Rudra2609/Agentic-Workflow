# Licences of the offline research corpus (Sprint 5, Member 5)

`corpus/` holds cleaned text of web pages that the research agent fetched once (online) for the gold questions and
the demo. Only sources whose licence allows redistribution are kept; every page file records its licence and its
original URL (the attribution). Pages from other sites (blogs, tutorials, vendor docs) were **left out**: offline,
they are simply "not in cache". `search_cache/` keeps the search results (URL, title, rank; the snippet only for
the permissive sources below).

| Licence | Pages | Sites |
|---|---|---|
| CC BY-SA 4.0 (Wikipedia contributors) | 76 | en.wikipedia.org |
| arXiv metadata: CC0 1.0 (title and abstract only) | 19 | arxiv.org |
| PSF Documentation License (Python Software Foundation) | 8 | docs.python.org |
| MIT License (FastAPI documentation) | 1 | fastapi.tiangolo.com |
| Apache License 2.0 (coverage.py documentation) | 1 | coverage.readthedocs.io |

Licence texts:
- CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/ (Wikipedia; attribution: the article URL and "Wikipedia contributors")
- PSF Documentation License — https://docs.python.org/3/license.html
- arXiv metadata (titles, abstracts): CC0 1.0 — https://info.arxiv.org/help/oa/metadataLicense.html
- MIT License (FastAPI, pytest, pytest-cov documentation)
- Apache License 2.0 (coverage.py documentation)
- BSD 3-Clause (Django documentation)
- CC BY 4.0 (React documentation)
- CC BY-SA 2.5 (Mozilla Contributors, MDN)
- IETF Trust Legal Provisions (RFC text)
- Public domain / CC0 (Python Enhancement Proposals)

Not redistributable (never committed): refactoring.guru and every site not in the table above.
