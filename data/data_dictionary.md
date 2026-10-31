# Data dictionary: atliq_digest

MySQL schema `atliq_digest`. Fictional AtliQ Hardware sales, Wed 1 Apr to Sun 4 Oct 2026, money in
USD. Built by the data team and already imported: file `01_silver_raw_data.sql`, then
`02_gold_agent_layer.sql`.

## How "today" works

- `sales_orders` holds orders up to **Sun 4 Oct 2026**.
- `settings.as_of_date` is the last complete day the agent may see. It starts at **2026-09-30**.
  When the agent runs at 8 AM, all of yesterday's orders are already loaded, so `as_of_date` may move
  up to yesterday, never to today.
- The view `v_sales_daily` only returns days up to `as_of_date`, so 1 to 4 Oct are stored but not
  visible yet. Moving `as_of_date` forward makes new days visible. Nothing is copied.

## Layers and who can read them

| Layer | Objects | Read by |
|---|---|---|
| Silver: source data | 9 tables (below) | root (the data team) |
| Gold: business-ready | view `v_sales_daily` | `agent_ro` |
| Agent support | `targets_daily`, `owners`, `settings`, `run_log` | `agent_ro` |

## Gold view: v_sales_daily (what the agent analyses)

One row per **day, customer and product**.

| Column | Meaning |
|---|---|
| date | Order date |
| region, sub_zone, market | Where. 5 regions (APAC, EU, LATAM, MEA, North America), 15 markets |
| customer, channel, platform | Who. Channels: E-Commerce, Retailer, Distributor |
| division, segment, category, product, variant | What. 14 categories × Standard, Plus, Pro |
| sold_qty | Units sold |
| gross_price | List price per unit |
| gross_sales … gross_margin | Money, calculated as below |

How the money is calculated:
```
gross_sales            = sold_qty x gross_price
pre_invoice_deduction  = gross_sales x pre_invoice_pct
net_invoice_sales      = gross_sales - pre_invoice_deduction
post_invoice_discount  = net_invoice_sales x discount_pct
post_invoice_other     = net_invoice_sales x post_other_pct
net_sales              = net_invoice_sales - post_invoice_discount - post_invoice_other
manufacturing_cost     = sold_qty x unit_cost
freight_cost           = net_sales x freight_pct
other_cost             = net_sales x other_cost_pct
gross_margin           = net_sales - manufacturing_cost - freight_cost - other_cost

gross margin %         = SUM(gross_margin) / SUM(net_sales) x 100
discount %             = SUM(post_invoice_discount) / SUM(net_invoice_sales) x 100
price per unit         = SUM(gross_sales) / SUM(sold_qty)
cost per unit          = SUM(manufacturing_cost) / SUM(sold_qty)
```

## Agent support tables

| Table | Columns | Notes |
|---|---|---|
| targets_daily | date, region, net_sales_target | Daily net sales target per region, up to 4 Oct. Weekly target = sum of the 7 days across all regions |
| owners | owner_id, region, market, channel, name, role, email | Who gets a drop alert. Lookup: market + channel, then market, then region head |
| settings | setting_key, setting_value | One row: `as_of_date` |
| run_log | run_id, run_at, job, as_of_date, status, details | One row per job run. `job`: new_data, daily_check, weekly_digest. `status`: OK or ERROR |

## Owners

| Region | Market | Channel | Name | Role |
|---|---|---|---|---|
| APAC | | | Sam Saxena | Regional Manager - APAC |
| EU | | | Hope Hegde | Regional Manager - EU |
| MEA | | | Shuri Shetty | Regional Manager - MEA |
| North America | | | Emily Carter | North America Sales Head |
| LATAM | | | Diego Ramos | LATAM Sales Head |
| APAC | India | | Arjun Mehta | India Country Manager |
| APAC | India | E-Commerce | Sneha Rao | India E-Commerce Lead |
| North America | USA | | Jake Miller | USA Country Manager |
| North America | USA | Retailer | Rachel Lee | USA Retail Lead |

Any market without its own row (for example Germany) goes to its region head. Emails are fictional
(`first.last@atliq-demo.com`).

## Logins (demo passwords; put them in `.env`)

| Login | Password | Can do | Used for |
|---|---|---|---|
| `agent_ro` | `AgentRead2026` | SELECT on `v_sales_daily`, `targets_daily`, `owners`, `settings`; SELECT and INSERT on `run_log` | Everything the agent reads, plus writing the run log |
| `agent_ingest` | `AgentIngest2026` | SELECT on `sales_orders`; SELECT and UPDATE on `settings` | Only moving `as_of_date` forward |

Connection: host `127.0.0.1`, port `3306`, database `atliq_digest`.

## Normal patterns (not problems)

- Friday is the highest day (about +10%), Sunday the lowest (about −30%).
- The last 3 days of each month are about 15% higher.
- Growth is about 1% a month. Daily noise is about 6%.

## Silver tables (source data, for reference; the agent cannot read these)

| Table | Columns | Notes |
|---|---|---|
| sales_orders | date, customer_code, product_code, sold_qty | 267,387 rows. Quantities only |
| dim_market | market, sub_zone, region | |
| dim_customer | customer_code, customer, platform, channel, market | 46 customers |
| dim_product | product_code, division, segment, category, product, variant | 42 products |
| price_list | product_code, valid_from, valid_to, gross_price | |
| cost_sheet | product_code, valid_from, valid_to, unit_cost | A new row starts when the supplier cost changes |
| discount_rules | region, valid_from, valid_to, discount_pct | A new row starts when a promotion rule changes |
| customer_terms | customer_code, pre_invoice_pct, post_other_pct | |
| freight_rates | market, freight_pct, other_cost_pct | |
