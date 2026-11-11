# Amazon Buy Box prices on product pages

Sincerely Cozy product pages show a visible price and a Product `Offer` in JSON-LD only when a live Amazon US Buy Box price has been fetched. Prices are never typed in by hand. There is no `review` or `aggregateRating` markup.

## What the job does

`scripts/refresh-amazon-prices.sh` is the scheduler-ready refresh entrypoint. After an explicit GO, daily runs that should also commit use `scripts/refresh-amazon-prices-commit.sh` instead. Both run `scripts/refresh-amazon-prices.py`, which:

1. Exchanges the LWA refresh token for an access token.
2. Calls the Selling Partner API **read-only** endpoint `getItemOffers` for each of the six ASINs, marketplace `ATVPDKIKX0DER` (US), `ItemCondition=New`:

   `GET https://sellingpartnerapi-na.amazon.com/products/pricing/v0/items/{ASIN}/offers?MarketplaceId=ATVPDKIKX0DER&ItemCondition=New`

3. Uses the **Buy Box** amount (`LandedPrice` if present, otherwise `ListingPrice`). Currency must be USD. If an ASIN has no Buy Box, that page gets no Offer and no visible price.
4. Writes `data/amazon-prices.json` and patches `swaddles/{slug}.html`. `priceValidUntil` is the fetch time plus 48 hours, America/New_York.
5. Validates that each page’s visible price matches its JSON-LD Offer, and that no `review` or `aggregateRating` keys are present.

The job never calls listing-write, feed, or catalog-write APIs. It does not load `~/.hermes/workspace/amazon/.env` or the older `AMAZON_LWA_*` names.

## Credentials

All secrets are read at runtime. They must not be committed, printed, or written into log lines (fingerprints and lengths only).

| Name | Required | Source |
|---|---|---|
| `AMAZON_SPAPI_CLIENT_SECRET` | yes | environment |
| `AMAZON_SPAPI_REFRESH_TOKEN` | yes | environment |
| `AMAZON_SPAPI_CLIENT_ID` | yes, unless a file is set | environment |
| `AMAZON_SPAPI_CLIENT_ID_FILE` (or `AMAZON_SPAPI_ENV_FILE`) | optional | path to a one-line client id, or `AMAZON_SPAPI_CLIENT_ID=...`. **The file overrides the env client id**, because the env value may be a pasted text block. |

On the Rank Labs box the clean client id file is `/home/box/ranklabs/secrets/amazon-spapi.env`.

## Availability mapping

`_availability` looks at `Offers[]` from `getItemOffers` (the Buy Box winner rows if any, otherwise every offer). `Summary.TotalOfferCount` and `SubCondition==New` by themselves never mean InStock.

| Signal on a **New**-condition offer | schema.org availability |
|---|---|
| `ShippingTime.availabilityType` is `NOW` | `InStock` |
| `IsBuyBoxWinner` or `IsFulfilledByAmazon` is true, and the shipping type is not a future/backorder value | `InStock` |
| `ShippingTime.availabilityType` is `FUTURE_WITH_DATE`, or the offer is an explicit backorder | `PreOrder` |
| Anything else, including `FUTURE_WITHOUT_DATE`, no `Offers` list, or only `TotalOfferCount>0` / `SubCondition==New` | `OutOfStock` |

If a Buy Box amount exists but availability is `OutOfStock` or `PreOrder`, the Offer still carries that availability and the amount (the plan allows an Offer with those fields). A page never claims `InStock` without an in-stock New offer as defined above.

## Failure mode

- If **every** ASIN call fails (LWA or `getItemOffers`) and the catalog `priceValidUntil` is still in the future, the site files are left alone (exit 2). The commit wrapper does not commit and prints `ALERT:SHEIK:price-refresh:exit=2 ...` on stderr so a routine can notify Sheik. The script does not send email.
- If every ASIN call fails and the window has expired (or there is no price file), Offers and visible prices are stripped. The Product schema stays.
- On a **per-ASIN** transport or API error, if `now` is still before **that ASIN's** stored `priceValidUntil` (falling back to the catalog window), the existing Offer and visible price are kept and the window is not extended. If the window has expired or there is no stored price, that ASIN's Offer and price are dropped. This matches the all-fail keep-or-strip rule, applied per ASIN.
- A successful response with no Buy Box is not an error: that ASIN is dropped, never invented.

## Commit wrapper

`scripts/refresh-amazon-prices-commit.sh` is the commit entrypoint. It:

1. `git fetch`es and requires a clean checkout on `main` that equals `origin/main`.
2. Runs the refresh.
3. Before staging, refuses any `git status --porcelain` entry other than an unstaged `M` on the seven allowlisted paths (`data/amazon-prices.json` and the six `swaddles/*.html` files). Deletions (`D`), renames (`R`), additions (`A`), untracked files (`??`), and any staged entries are rejected. It also refuses if `data/amazon-prices.json` is missing.
4. Stages only those seven allowlisted paths.
5. After `git add`, re-checks the index: `git diff --cached --name-status` must be `M` only, and only on allowlisted paths. Otherwise it runs `git reset --hard HEAD` to restore the worktree and exits 1.
6. Also refuses if an HTML diff hunk falls outside the Product Offer JSON-LD and the `amazon-price` markers.
7. On refresh exit 1, restores the working tree (`git restore` / `git checkout`) and does not commit.
8. On refresh exit 2, does not commit and prints the `ALERT:SHEIK:price-refresh:exit=2` hook on stderr (non-zero exit). No email is sent.
9. With `--push`, after the index check passes and the commit succeeds, runs `git push origin HEAD:main` for that single commit. On push failure it runs `git fetch origin` then `git reset --hard origin/main`, prints `ALERT:SHEIK:price-refresh:push-failed` on stderr, and exits non-zero. Without `--push` it stays commit-only.

## Schedule (not installed yet)

Do not add cron or a routine, and do not pass `--push`, until there is an explicit GO. Cloudflare Pages deploys `main` to production.

After that GO, the daily command at **7:00 AM America/New_York** is:

```bash
AMAZON_SPAPI_CLIENT_ID_FILE=/home/box/ranklabs/secrets/amazon-spapi.env \
  /home/box/.hermes/workspace/ranklabs/sites/sincerelycozy/scripts/refresh-amazon-prices-commit.sh --push
```

Run it only from a clean `main` checkout of `ranklabs-api/sincerelycozy`. If that checkout is dirty or behind, fix the checkout (or use the GitHub Git Data API) instead of creating a new clone or worktree. A successful commit uses:

`chore(prices): refresh Amazon Buy Box prices YYYY-MM-DD`

Validate a checkout without calling Amazon:

```bash
python3 scripts/refresh-amazon-prices.py --root . --validate-only
```
