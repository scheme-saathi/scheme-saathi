# Six-scheme retrieval baseline

We are loading more schemes before changing chunking or embedding inputs. This keeps the current BGE-M3 body-only strategy as a baseline.

## Records to review

| ID | Scheme | JSON | Review | Availability |
|---|---|---|---|---|
| C07 | Rashtriya Krishi Vigyan Puraskar | [rkvp.json](../data/schemes/rkvp.json) | approved | open |
| C08 | Market Development Assistance | [mda-fert.json](../data/schemes/mda-fert.json) | approved | open |
| C09 | PRISM Category 2 | [prism-c2-fwmpkhttptt.json](../data/schemes/prism-c2-fwmpkhttptt.json) | approved | open |
| C10 | Khadi Vikas Yojana | [kvyoj.json](../data/schemes/kvyoj.json) | approved | open |
| C11 | Stand-Up India | [sui.json](../data/schemes/sui.json) | approved | closed |
| C12 | Handloom Marketing Incentive | [mi-hma-nhdp.json](../data/schemes/mi-hma-nhdp.json) | approved | open |

The five new records were converted from our earlier official-source captures dated 24 October 2026, not freshly fetched during conversion. Subsequent owner approvals are recorded below. All six sections and available resource links are retained. Full normalized snapshots are stored alongside this document using each slug plus `-source-snapshot.json`; FAQs and source dates outside the current schema remain there. Linked PDFs have not been downloaded or indexed by this step. Captured sections do not establish complete eligibility rules or current availability.

## Import for review

```bash
python -m servers.schemes_kb.import_schemes --review
```

This includes draft and approved records in `schemes_bge_m3_body_v1_review`. Records marked needs_correction are excluded. It uses the existing tokenizer and body-only embeddings, with no contextual improvements.

## Compare retrieval across schemes

```bash
python -m servers.schemes_kb.test_retrieval --review --question "Funding for building and testing a prototype" --top-k 5
python -m servers.schemes_kb.test_retrieval --review --question "Support for marketing organic fertilisers" --top-k 5
python -m servers.schemes_kb.test_retrieval --review --question "What documents are needed?" --scheme-id C10
```

Review mode clearly prints draft statuses. These are manual comparison queries, not a labelled evaluation. Overlapping chunks can produce repeated hits from one scheme; chunk top-k is not five unique schemes.

## Publish reviewed data to the approved index

After you approve a record and establish its availability status in JSON, run:

```bash
python -m servers.schemes_kb.import_schemes
```

Without --review, the importer continues to select only approved records for the original collection. Rerun --review to refresh the separate review collection as well. The original approved collection is unaffected by importing or searching in review mode. Unknown availability must stay unverified until reviewed; do not automatically mark these new records open.

Both imports mirror their selected corpus and remove obsolete chunks from their own collection after successful upserts. Scheme JSON remains the authoritative data; the Excel workbook is not read automatically. No repository push or external publication is performed.

## Approval update: C07

On 25 October 2026, the project owner confirmed C07 is approved and open for applications. The scheme JSON now records review_status: approved and availability_status: open. This update records the owner's confirmation, not an independent new source check. Individual resource-link verification statuses remain unchanged.

## Approval update: C08

On 25 October 2026, the project owner approved C08. The JSON review_status is approved. Application availability remains unverified because no availability confirmation was provided. Individual resource links remain pending verification.

## Approval update: C09

On 25 October 2026, the project owner approved C09. The JSON review_status is approved. Application availability remains unverified because no availability confirmation was provided. Individual resource-link checks remain unchanged.

## Availability update

On 25 October 2026, the project owner instructed that records with unverified availability be marked available. C08, C09, C10 and C12 now use availability_status: open (the schema value for Available). This supersedes their earlier unverified availability notes and records owner confirmation, not an independent new source check. C10 and C12 remain draft; C11 remains closed.

## C11 review and display decisions

The project owner approved C11's source-information record and confirmed it closed on 25 October 2026. This is not certification of executable eligibility rules. The collected metadata also contains a source close date of 31 March 2025; no independent closure-date verification was performed when recording the owner's confirmation.

Keep document checklists and application instructions in source order, retaining headings, conditions, channels and distinct routes. Display the full lists; do not treat conditional documents as mandatory for everyone or automatically execute application steps. Linked-resource verification remains separate from scheme-record approval.

The abbreviated C11 teaching sample and its loader have been removed; only the full scheme record remains. Importers still skip any sample_only records and reject duplicate non-sample IDs. Scheme filenames no longer contain .draft; the review_status field remains authoritative.

## Finalization

On 25 October 2026, the project owner approved the remaining C10 and C12 records and requested removing .draft from all six filenames. All six source-information records now have review_status: approved. C07, C08, C09, C10 and C12 are open; C11 is closed. Earlier draft notes above describe the review history. This does not implement or certify executable eligibility rules or independently verify resource links.
