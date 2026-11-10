# Amazon Buy Box prices on product pages

Sincerely Cozy product pages show a visible price and a Product `Offer` in JSON-LD only when a live Amazon US Buy Box price has been fetched. Prices are never typed in by hand. There is no `review` or `aggregateRating` markup.

## What the job does

`scripts/refresh-amazon-prices.sh` is the scheduler-ready entrypoint. It runs `scripts/refresh-amazon-prices.py`, which:

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

## Failure mode

- If the refresh fails and `priceValidUntil` is still in the future, the site files are left alone.
- If the refresh fails and the window has expired (or there is no price file), Offers and visible prices are stripped. The Product schema stays.
- If only some ASINs have a Buy Box, the others are left without an Offer. Missing prices are never invented.

## Schedule (not installed yet)

Do not add cron or a routine until there is an explicit GO to run this on a schedule, and a standing GO before any auto-commit to `main` (Cloudflare Pages deploys `main` to production).

After that GO, the daily command at **7:00 AM America/New_York** is:

```bash
AMAZON_SPAPI_CLIENT_ID_FILE=/home/box/ranklabs/secrets/amazon-spapi.env \
  /home/box/.hermes/workspace/ranklabs/sites/sincerelycozy/scripts/refresh-amazon-prices.sh
```

Run it only from a clean `main` checkout of `ranklabs-api/sincerelycozy`. If that checkout is dirty or behind, use the GitHub Git Data API (same path as site content PRs) instead of creating a new clone or worktree. A later standing GO can commit a successful refresh with:

`chore(prices): refresh Amazon Buy Box prices YYYY-MM-DD`

Validate a checkout without calling Amazon:

```bash
python3 scripts/refresh-amazon-prices.py --root . --validate-only
```
