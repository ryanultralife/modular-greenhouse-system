# Entering Josh's real engineering data

Everything the configurator quotes or engineers comes from one file:
**`data/catalog.json`**. The code never invents structural numbers — it only
reads what is in this file. Each figure carries a flag that tells the system
whether it is real (`verified`/`verified_price` = `true`) or a placeholder
(`false`) that is still waiting on Josh.

Until a value is verified, the system refuses to treat it as authoritative:

- Unverified **prices** appear as `TBD` and are kept out of the quote subtotal.
- Unverified **engineering limits** force every non-standard layout to
  `REQUIRES_ENGINEER_SIGNOFF`.

This is intentional. It guarantees no quote goes out with a made-up price and
no T/X/L build is ever advertised as "130 mph rated" without a real sign-off.

## What is already verified

| Field | Value | Source |
|-------|-------|--------|
| Base model: 4×4 Raised Bed | $899 | website |
| Base model: 6'5" Barn Style | $1,699 | website |
| Bay increment | 4 ft | website / patent |
| Wind rating (standard straight run) | 130 mph | website |
| Snow rating (standard straight run) | 6 ft | website |
| Warranty | 10 years | website |

## What still needs Josh's input

Open `data/catalog.json` and replace every entry where `verified` or
`verified_price` is `false`:

1. **SKU prices** — `extension_module`, `end_cap`, `door_end`,
   `junction_kit`, and the accessories. Set `price_usd` and flip
   `verified_price` to `true`.
2. **Per-SKU weights** — fill `weight_lb` (needed later for shipping logic).
3. **Configuration limits** — in `configuration_limits`, set the real values
   for the largest run length, footprint, and junction count that Josh's
   existing engineering already covers, then set `verified: true`. Once these
   are real, in-envelope non-standard builds report `PRELIMINARY_OK` instead of
   forcing a sign-off.

### Example: marking the extension module price as real

Before:

```json
"extension_module": { "name": "4' Extension Module (adds 1 bay)", "price_usd": null, "verified_price": false, "weight_lb": null }
```

After:

```json
"extension_module": { "name": "4' Extension Module (adds 1 bay)", "price_usd": 349, "verified_price": true, "weight_lb": 62 }
```

## How limits drive the engineering triage

For a **straight run** the published rating applies directly → status
`STANDARD`.

For **L / T / X** or extended builds the triage compares the layout against the
verified `configuration_limits`:

- all limits verified **and** layout within them → `PRELIMINARY_OK`
- any limit exceeded, or any limit still a placeholder → `REQUIRES_ENGINEER_SIGNOFF`

`PRELIMINARY_OK` means "matches a case Josh's engineering already covers." It is
still not a stamped structural certification — that always comes from a
qualified engineer. The triage just tells Josh which quotes he can turn around
immediately and which ones need a review first.
