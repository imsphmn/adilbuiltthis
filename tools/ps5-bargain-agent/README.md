# PS5 Bargain Agent

This scheduled monitor searches UK listings for a complete, working PlayStation 5 bundle below **£280 total**.

## Strict match rules

A listing must indicate:

- A working PS5 console
- A genuine Sony DualSense controller
- A parsed price below £280 including known delivery
- Original PS5 Disc, original PS5 Digital, or PS5 Slim Disc

It rejects:

- PS5 Slim Digital
- Console-only and controller-only listings
- Faulty, broken, parts-only and repair listings
- Empty boxes, faceplates, stands and other accessories
- Sold, ended and out-of-stock pages where detectable

## Alerts

Each new qualifying listing creates a GitHub issue assigned to `imsphmn`. GitHub then sends a notification according to the account's notification settings. Duplicate listing IDs are not alerted twice.

The issue includes the listing link, parsed total, model estimate, risk flags, and a pre-purchase test checklist.

## Schedule

The workflow runs every 30 minutes and can also be run manually from GitHub Actions.

## Important limitation

Marketplace anti-bot controls and incomplete listing descriptions can occasionally prevent verification. Treat each alert as a fast shortlist, not as proof that the seller or console is safe. Confirm the final checkout total and test the console before paying.
