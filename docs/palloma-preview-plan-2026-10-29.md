# Sincerely Cozy — Palloma preview plan (OTW email Oct 29)

**Status:** Preview branch/PR only. **No production merge, no Pages production deploy** until Palloma + Josiah say go.
**Source:** otw@ mail (thread 9d4c5e23…), map `sincerely-cozy-redesign-site-map-2026-10-29.md`, photos zip (19 web JPGs).
**Base:** `sincerelycozy` `main` @ `5196fdb` (live phone already `(321) 340-3616`).

## Palloma decisions we will implement in the preview

1. **Homepage hero** = auto-rotating **5-photo** banner (zip `homepage-banner/web` slides 1–5). Soft fade ~5s. Dot indicators + optional arrows OK. **Remove Play slides / play-pause UI sitewide.** Honor `prefers-reduced-motion` (stop auto-rotate).
2. **Homepage multifunction** = rotating photo **left** + compact uses list **right** → link **“See all the ways to use it” → `/versatility`**. First photo = privacy-cropped `versatility-main…`; then nursing / burp / changing blanket / tummy time / playmat-2. No photos yet for Swaddle bath, Receiving blanket, Stroller canopy → list only.
3. **New `/versatility`** = one block per use with photos from `versatility-page/web` + **Buy on Amazon** (storefront until per-print sync). Captions + safe-use = **`[Caption placeholder: Palloma to write]`** / **`[Safe-use note: Palloma to confirm]`**.
4. **Privacy:** main versatility photo cropped so pacifier-clip letters are not readable; letters never in alt/captions.

## Still open — do not invent

| Open | Preview behavior |
|---|---|
| Phone on site? | Keep current main `(321) 340-3616` (already live). Flag for Palloma confirm. |
| Playmat own use vs under Tummy time? | Own `/versatility` block + homepage rotation photo; label “Playmat” with note for Palloma. |
| “Changing mat” vs “Changing blanket” | Use **Changing blanket** (her list); files stay `changing-mat-*`. |
| Swaddle bath / Receiving blanket / Stroller canopy photos | List + placeholder blocks only. |

## Preview deliverable (this PR)

Branch: `preview/otw-oct29-banner-versatility`  
PR → `main` (do **not** merge). Cloudflare Pages preview URL from the PR when available.

### Files / assets
- Copy banner + versatility web JPGs into `assets/images/homepage-banner/` and `assets/images/versatility/`.
- Use `versatility-main-privacy-cropped.jpg` (letters out) as homepage multifunction first slide + /versatility hero for that photo.
- Update `index.html` sections 1–2; add `versatility.html`; `sitemap.xml` + `_redirects` if needed; nav link “Ways to use it”; strip play/pause from carousel JS/CSS.
- Keep Amazon-only CTAs; **no Offer / AggregateRating / PostalAddress**; no invented prices.

### Out of scope this PR
Boys/girls/neutral filters, email/Klaviyo, full product gallery rebuild, production merge, credential use, purchases.

## After Palloma review
Rauru merges only on explicit Palloma + Josiah go. Reply to otw@ with plan + preview URLs (Rauru drafts).
