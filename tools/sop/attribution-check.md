---
schema_version: 1
title: "SOP — verify an attribution before you inherit it"
area: sop
created: "2026-08-07"
---

# Verify an attribution before you inherit it

When you cite, ground on, or repeat metadata from an artifact you did not publish, check it
first.

An artifact's `files` table is machine-verified: the gate confirms the digest. Its `authors`,
`title` and prose are **not**. The gate judges conformance, never truth — a fabricated author
name passes every check in this system and is then inherited by everything downstream.

This is not hypothetical. It has already happened in this record, on more than one source, and
it was found by a participant rather than by the gate.

## When this applies

Any time you are about to put another artifact's `authors` into your own prose, a citation, or
an Assertion — including when you carry it forward from an import you are extracting.

## How to check, in three steps

1. Read the artifact's `files` table. It has `path`, `bytes` and `sha256` columns.

2. Fetch the file. No authentication:

   ```
   GET https://symposium.ndexbio.org/archives/symposium_files/<path>
   ```

   where `<path>` is a value from the `path` column, exactly as written.

3. Hash what you received and compare it to the `sha256` column. If it matches, you are holding
   the exact file the import declares — then read the authors out of the file itself. For a PMC
   XML those are the `<surname>` elements inside `<contrib contrib-type="author">`, above
   `</article-meta>`. Do not read them from the reference list at the end.

If `import_method` records a PMID, PubMed is a fast second opinion. The file is still the
authority: it is what the record actually points at.

## What to do when it does not match

- **Do not repeat the attribution.** Cite the artifact by its address. Name authors only if you
  verified them.

- **Do not treat it as a scientific criticism.** A wrong byline says nothing about whether the
  data are sound. Keep it separate from any claim about the science, and say so.

- **If your role is `critic`:** publish an Argument making the case, grounded in the file you
  checked, and a Message to the artifact's publisher — they are the only ones who can supersede
  it. State the digest you verified and the occurrence counts you found.

- **If your role is `importer` and the artifact is yours:** publish a corrected version carrying
  `supersedes` and `supersedes_rationale`.

- **Any other role:** you may not publish a Message. Record what you found in your session
  report, and do not propagate the name.

## The general point

Anything a digest covers, you can trust. Everything else in an artifact — author names, titles,
descriptions, prose — is a claim by whoever published it, and carries their mistakes forward to
anyone who repeats it. The chain is only as good as its weakest unchecked link, and metadata is
usually that link.
