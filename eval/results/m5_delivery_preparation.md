# M5 delivery preparation receipt

2026-09-27. Candidate built: `3f87595b6c67a532596b9018551410f494dcdbc5`.
Product code includes the local period fix `29a1d9e`; original M5.0 results remain
unchanged. This receipt is no-provider preparation, not live end-to-end acceptance.

## Brief and handover

Read all four pages of the local case brief and visually checked packaging,
deliverables and presentation pages. Required: full-source GitHub repository with
intact history; Docker startup with environment/key documentation; README covering
run instructions, implementation, decisions and next work; local live demo. The
call allocates about 10 minutes to demo and 20 to technical discussion. Hosting is
explicitly unnecessary. No Docker registry or source ZIP is mandated. Keep the
confidential brief local; no copy was added to the deliverable.

GitHub was checked through authenticated CLI: private repository
`LaoM10617/jingwenxu_siteco_docRetriever`; main remote is `6c6d922` at inspection;
only owner `LaoM10617` is listed as collaborator. No push, visibility change,
invitation or message was sent. Reviewer access is not yet established.

## Source packaging checks

Exported candidate with git archive to local `tmp/m5-delivery/source-3f87595.zip`
and extracted to `tmp/m5-delivery/source` for building. ZIP contains committed
source only, not Git history; the GitHub repository remains the required handover.
The package is a candidate snapshot, not the final delivery archive.

Archive SHA256: `a2d2da03d9166cba81c926cbb44c5a72d897728f3fab91476cf3b167b992083f`. Entries: 209.

Scanned 403 reachable Git blob objects and archive contents against the three
known local credential values without printing them: zero matches. Archive path
checks found no private/data/tmp directories, credential files, .env, SQLite or
.db files. This checks known credentials and named exclusions, not all possible
unknown secrets. Build uses the committed .dockerignore allowlist.

## Clean Docker preparation

- Compose project: `siteco-m5-delivery`; new frontend 18105 / backend 18104.
- Empty host runtime: `tmp/m5-delivery/runtime`; no previous data/index/cache copied.
- Explicit local env file outside exported source; all three provider keys blank.
- compose config --quiet passed. Both images built successfully from exported source.
- Docker cache was allowed; dependency installation and frontend build ran in this
  build. This is not a claim of a fresh Docker engine or a no-cache build.
- README tokenizer command freshly downloaded and checksum-verified its public file.
- compose up --wait succeeded; both containers healthy.
- Backend image: `sha256:ea8d439723bc7853990f844fa4682d5f989318c14c862005340734fb181b76be`.
- Frontend image: `sha256:b9936d06ef823b181cee8f73f2f95ed9c7661b723c3316d5a421ad9c94cf1c7c`.
- Frontend-proxied /api/health returned status ok / version 0.1.0;
  /api/documents returned an empty list.
- Edge/Playwright opened the actual frontend, showed empty Materials and missing
  Gemini/Voyage credentials in Settings: zero page errors, zero write requests.
  Screenshots and machine receipt are local under tmp/m5-delivery.
- Built-in CUA failed before navigation with sandbox helper setup error. Browser
  verification used existing Edge/Playwright instead. The first locator check
  needed to open the initially closed sidebar; this was a test-script correction,
  not a product change.
- Original siteco-m28-smoke services remained healthy on 18095/18094.

No upload, generation/embedding call or Settings connection test ran. Public
package/base-image/tokenizer downloads are distinct from inference calls. Both
new services remain running without keys for the next approved step.

## Remaining gate

The concrete nine-turn live plan and 64-attempt / USD2 estimate cap are in
[the acceptance proposal](../../docs/m5-clean-acceptance.md), awaiting budget approval.
The user can inspect the prepared local UI at http://127.0.0.1:18105. Functional
uploads, answer correctness, source checks, follow-ups, refresh and failure behavior
remain to be accepted on this candidate. Final review, final commit selection,
remote push and reviewer access remain outstanding; do not label this M5 complete.
