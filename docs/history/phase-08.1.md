# Phase 8.1 — within-standard ranking + guard edges (moved verbatim from CLAUDE.md; originally inside the Phase 8 section)

**Phase 8.1 (within-standard ranking + guard edges).** `clauses.residual_query(standard, query)`:
once a standard is chosen, the query minus stopwords, FILLER, `FOLLOW_UP_WORDS` and every word of
that standard's own record (title, keywords, document name, number) — except a process word that is
a word of one of that standard's MAIN-BODY section headings ("8 MARKING", "21 TESTS"; annex headings
don't count), which names a clause there. `attach` ranks on the residual; an empty residual, or one
that matches no clause ("tell me about …"), attaches the scope clause only. `rank_within` unchanged;
caps and confidence gates unchanged; eval identical. `FOLLOW_UP_WORDS` gained `requirements` (the
singular was already there). Guard: annex-style labels need a dot (`F-1.4`; "M-20", "Class B-1",
"Type A-2" pass), `Annex F-1` still counts, a range cites both ends. Live hi/te answers wrote
"Clause 9" in English every time; the one native marker seen was Hindi `अनुबंध F` (Annex F) —
added, only before an annex letter, because अनुबंध also means "contract".

