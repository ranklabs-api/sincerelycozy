# Cozy Journal redesign — draft review

Status: index visually accepted by the user at 1440px and 390px on 2026-10-28, with 20 cards, one H1 and no horizontal overflow. The post-page follow-up is implemented and statically checked; its visual acceptance remains pending (see post-pages.md). Reference-site visual measurements remain unverified.

## Design

Removed the large hero photo altogether. A warm off-white canvas, plum ink, Georgia headings, and restrained lavender feature panel give the journal a distinct editorial hierarchy. System fonts avoid font downloads and layout shifts. A starting-point guide and three topic links precede a two-column reading room; mobile CSS stacks these with 16px outer gutters. Cards have generous internal padding, full-card links, visible focus states, and no dependency on image columns. All existing titles and excerpts are unchanged.

Only blog/index.html and its new journal.css stylesheet affect the website. Shared styles.css is unchanged. Header destinations and footer content remain intact. A versioned index-only stylesheet prevents the old shared stylesheet cache from controlling the redesign.

## Five-brand research

Consulted these actual brand pages using web retrieval before implementing. The available text establishes hierarchy, navigation and content composition. Chrome headless launch failed (SIGABRT under the sandbox), connected Chrome reported unavailable, and browser discovery returned no connected browsers. Therefore image crop ratios, rendered font sizes, spacing rhythm, exact first-screen coverage and mobile differences are **unverified for all five**. These are not claimed as completed visual observations.

| Brand and source | Confirmed content structure | Pattern applied and why |
| --- | --- | --- |
| [Solly Baby — The Uplift](https://sollybaby.com/blogs/news) | Named publication, topic links (including Motherhood and Postpartum), linked story headings, pagination. | A distinct journal masthead and plain-language entry points help the page feel like a publication. |
| [Little Sleepies — The Cozy Corner](https://littlesleepies.com/blogs/news) | Named editorial section, category navigation, featured story and guide, repeated Read More links. | Put one helpful guide ahead of the archive so parents have a starting point. |
| [Kyte Baby — Blog](https://kytebaby.com/blogs/news) | Repeated linked titles followed by explanatory excerpts, with pagination. | Keep complete excerpts beneath the title so the publisher's minimal card still helps readers choose. |
| [Nanit — Parenthood Unfiltered](https://www.nanit.com/blogs/parent-confidently) | Introductory description, image-backed topic features before an archive, explicit reading links. | Separate evergreen starting points from the complete archive. Use calm colour instead of a large image. |
| [Lovevery — Parent Resources](https://blog.lovevery.com/?page_id=23941) | Age and subject navigation, search, linked H2 titles and descriptive summaries. | Organize entry points around parent needs: sleep, fabric care and gifting. Retain crawlable summaries. |

No competitor assets, copy or trademarks were incorporated. The exact type scale and spacing in journal.css are original design choices, not measurements of these references.

## Publisher compatibility

Generator unchanged; no changes in ranklabs-app. Every original card remains exactly article.blog-card > h2.blog-card-title > a, followed by p.blog-card-excerpt. No article occurs before the grid. The featured guide uses a section/div. There are no position-dependent categories, dates or counts to go stale.

Executed the actual insertIntoBlogIndex function from ranklabs-app in a VM with filesystem writes redirected to memory. It inserted the exact generated card before the first existing article inside the grid, producing 21 cards. Publishing again returned the existing `already linked` guard. A temporary fixture is saved outside the repository. **Visual equivalence is still pending.** Both fixture and original use identical CSS selectors, with no first-child/nth-child exceptions.

## Checks passed

- All 20 original post cards unchanged and linked; all main-content hrefs resolve to actual blog files.
- Exactly one H1; post titles remain H2.
- Title 56 characters; description 153 characters.
- Canonical and og:url exactly https://sincerelycozy.com/blog/; all requested Open Graph and Twitter tags present.
- Original Organization JSON-LD and footer preserved; no rating/review schema added.
- The only remaining image is the header logo, with meaningful alt and explicit dimensions.
- styles.css and all six required regression pages are byte-identical to the original commit.
- No page content depends on JavaScript.

## Original visual acceptance checklist (index now accepted by user)

At 1440px and 390px, capture and inspect the blog, homepage, products index, baby-blue product page, FAQ, care instructions and how-to-swaddle-a-baby post. Check horizontal overflow and focus/tap targets. Render the future-publish fixture at both sizes and compare it with neighbours. Then finish the five reference-site visual observations above. A prepared Playwright script exists at /tmp/cozy-design/verify-visual.cjs; no screenshots were produced because Chrome could not launch.

## Deliberate omissions

No per-card photos or metadata, so publishing cannot produce incomplete cards. No automatic categories inferred from words in titles. Topic links are honest guide links rather than nonfunctional filter pills. No new Blog/ItemList schema or hardcoded post count that would go stale. No fabricated endorsements, authors, reading times or dates. No change to the generator or shared stylesheet.

## Branch location

The supplied workspace's .git directory is read-only, preventing branch creation there. Work is committed on design/blog-codex in the isolated checkout at /tmp/cozy-design/repo. The original checkout remains clean on main. A Git bundle is provided alongside the checkout. Nothing was merged or pushed.
