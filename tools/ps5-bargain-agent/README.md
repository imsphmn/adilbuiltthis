# PS5 Bargain Agent

This scheduled monitor searches UK listings for a complete, working PlayStation 5 bundle below **£280 total**.

## Strict match rules

A listing must indicate:

- A working PS5 console
- A genuine Sony DualSense controller
- A parsed total below £280, including known delivery and mandatory buyer fees
- Original PS5 Disc, original PS5 Digital, or PS5 Slim Disc

It rejects:

- PS5 Slim Digital
- Console-only and controller-only listings
- Faulty, broken, parts-only and repair listings
- Empty boxes, faceplates, stands and other accessories
- Upfront-payment and deposit requests
- Sold, ended and out-of-stock pages where detectable
- Distant Gumtree collection listings unless protected delivery keeps the full total below £280

## Alerts

Each new qualifying listing creates a GitHub issue assigned to `imsphmn`. GitHub then sends a notification according to the account's notification settings. Duplicate listing IDs are not alerted twice.

The issue includes the listing link, parsed total, model estimate, risk flags, and a pre-purchase test checklist.

## Schedule

The workflow is scheduled four times per hour, at 3, 18, 33 and 48 minutes past the hour, and can also be run manually from GitHub Actions. GitHub may occasionally delay scheduled jobs.

## Marketplace coverage

The monitor searches Gumtree and second-hand retailers directly, with local searches centred on New Malden. It also attempts eBay discovery, but eBay blocks some automated server searches. For that reason, automated eBay coverage is best-effort rather than complete.

## Important limitation

Marketplace anti-bot controls and incomplete listing descriptions can occasionally prevent verification. Treat each alert as a fast shortlist, not as proof that the seller or console is safe. Confirm that the ad is still live, confirm the final checkout total, and test the console before paying.
