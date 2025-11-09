Replication Package: A Systematic Review on Software Aging and Rejuvenation

This repository contains the replication package for the paper:

> **A Systematic Review on Software Aging and Rejuvenation**  

The replication package includes all raw data and intermediate results from the systematic literature search and selection process, enabling transparency and reproducibility of the study.

---

## 🔍 Process Overview

The replication package follows the systematic literature review process (see `Related Documents/Search and Selection.png`):

1. **Initial Search**: Comprehensive search across four databases
2. **Impurity Removal**: Filtering of non-research publications
3. **Selection by Criteria**: Application of inclusion/exclusion criteria with inter-rater reliability assessment
4. **Snowballing**: Two rounds of backward and forward snowballing to ensure completeness
5. **Data Extraction**: Systematic extraction of key information from selected papers to address all Research Questions (RQs)
---
## 📁 Contents

### 1. `Initial Search.xlsx`
Contains the raw search results from four digital libraries using the defined search keywords and database-specific filters(see `Related Documents/Literature Search Process.md` for details).

**Sheets:**

- `Initial Search-ACM`: Results from ACM Digital Library
- `Initial Search-IEEE`: Results from IEEE Xplore Digital Library
- `Initial Search-Springer`: Results from SpringerLink
- `Initial Search-ScienceDirect`: Results from ScienceDirect
- `Initial Search-Merge`: Combined results from all databases


### 2. `Selection by Criteria.xlsx`
Documents the paper selection process based on inclusion and exclusion criteria (see `Related Documents/Inclusion & Exclusion Criteria.md` for criteria details).

**Sheets:**

- `Selection`: 
  - Decisions from Author 1 and Author 2 for each paper
  - Decisions from Author 3 in case of disagreements
  - Final inclusion/exclusion decisions
- `Kappa`: Calculation process for Cohen's Kappa inter-rater reliability score

### 3. `Snowballing.xlsx`

Document the snowballing (both backward and forward).

**Sheets (for each file):**

- `Backward`: Papers identified from reference lists
- `Forward`: Papers identified through citation tracking
- `Merge`: Combined snowballing results and selection decisions for snowballed papers

