# Journal post layout follow-up

The user visually accepted the index at 1440px and 390px. This follow-up leaves blog/index.html and shared styles.css unchanged. journal.css gets one narrow accessibility adjustment: main-navigation links now have a minimum width of 44px as well as a minimum height, including the short Blog label.

## Changes

All 20 posts now use the journal header, main navigation, footer, breadcrumb, skip link and end-of-article links to the blog and swaddle collection. That includes the 16 generated posts and four older hand-written posts. Existing article markup is byte-for-byte preserved: no prose, titles, links, publication dates or images inside articles were rewritten. Existing metadata and JSON-LD remain unchanged. Only the generic inline presentation stylesheet and outer chrome were replaced.

The new post.css sets a 70ch reading measure, serif headline hierarchy, generous paragraph spacing and visible publication dates. Mobile uses 16px outside gutters and a single-column closing navigation. Navigation and article links have 44px minimum-height targets. Legacy photos remain within the reading measure; their hero height is capped at 260px.

## Future publishing: integrate both branches

The separate ranklabs-app branch changes buildStaticBlogPostHtml to accept siteDir, and the static publishing caller supplies config.dir. If blog/post-layout.template exists, its two slots receive the generated head metadata and complete article. The template supplies the stylesheets, header and footer. Only the generic inline CSS is removed; Article JSON-LD, Open Graph, title, canonical, description, date and H1 generation remain intact. Customers without a template receive byte-identical standalone output. Invalid template slots fail rather than publish incomplete HTML.

The template and CSS are site-owned files committed in this site branch. Integrate BOTH this site's branch and ranklabs-app's branch before the next Sincerely Cozy publish. No generator card change: exact three-element cards and the first-article insertion rule remain unchanged, as does the already-linked dedupe guard.

## Checks completed

- 20/20 article elements byte-identical to the pre-backfill files.
- 20/20 retain metadata, JSON-LD and publication dates; exactly one H1 and one main each.
- 20/20 have header, navigation, footer; stylesheet and local chrome links resolve.
- Accepted index HTML and shared styles.css byte-identical; journal.css only adds a 44px minimum navigation-link width.
- 18 publisher and publish-failure-recovery tests pass, including site-template metadata/body preservation, missing-template fallback, malformed-template rejection and literal-token handling.
- Actual publisher function rendered the actual site template into /tmp/cozy-design/generated-post.html (temporary, not published).
- Actual card insertion simulation still passes; 21 cards inside the index grid and repeat-insertion dedupe preserved.

## Visual acceptance still needed for posts

Attempted the user's exact installed Playwright launch method: require('playwright').chromium.launch(), without an executable override. Chromium exists but exits with macOS MachPortRendezvousServer bootstrap_check_in Permission denied (1100), SIGTRAP. The error is saved at /tmp/cozy-design/browser-launch-error.txt. No screenshots were produced; post layout is not claimed as visually verified.

Run outside the restricted sandbox:

```sh
NODE_PATH=/Users/easybot/.hermes/workspace/ranklabs/repos/ranklabs-app/node_modules node /tmp/cozy-design/verify-posts.cjs
```

The script uses true 1440×1200 and 390×1200 viewports, checks all 20 posts and the index for horizontal overflow, one H1 and 44px link targets, captures first-screen and full-page images, and exercises generated post and index-card fixtures. Inspect the resulting screenshots; assertions alone are not visual approval.

Expected screenshot paths (not yet created):

- /tmp/cozy-design/screenshots/index-1440.png
- /tmp/cozy-design/screenshots/index-390.png
- /tmp/cozy-design/screenshots/is-it-safe-to-cover-stroller-with-blanket-1440.png
- /tmp/cozy-design/screenshots/is-it-safe-to-cover-stroller-with-blanket-390.png
- /tmp/cozy-design/screenshots/why-bamboo-1440.png
- /tmp/cozy-design/screenshots/why-bamboo-390.png
- Matching `-full.png` captures for these and every other post.
- /tmp/cozy-design/screenshots/generated-post-1440.png and generated-post-390.png
- /tmp/cozy-design/screenshots/future-publish-1440.png and future-publish-390.png

## Delivery

Both branches are named design/blog-codex, committed and unmerged. Original repositories' .git directories remain read-only; the ranklabs-app original also contains unrelated working changes. They were left untouched. Isolated checkouts: /tmp/cozy-design/repo and /tmp/cozy-design/ranklabs-app. Bundles: /tmp/cozy-design/blog-codex.bundle and /tmp/cozy-design/ranklabs-app-blog-codex.bundle. Nothing pushed or deployed.
