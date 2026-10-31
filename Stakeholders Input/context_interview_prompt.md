# Context Interview Prompt

Paste everything below the line into ChatGPT or Claude (free versions work).
Answer the questions. At the end you get your context file. Save it as `context/<yourname>.md`.

---

You are helping me write a context file for an AI agent. The agent reads company sales data every
week and writes me a one-page digest, and alerts people when sales drop suddenly.
The context file tells the agent who I am, what I care about, and how I want things written.

The company is AtliQ Hardware. It sells PCs, peripherals, accessories, networking and storage
in 15 markets across 5 regions (APAC, EU, North America, LATAM, MEA), through three channels:
E-Commerce, Retailer and Distributor.

The data the agent can use, per day, customer and product: sold quantity, gross sales,
pre-invoice deduction, post-invoice discount, other deductions, net sales, manufacturing cost,
freight cost, other cost, gross margin. There are also daily net sales targets per region.

How to run this interview:
- Ask me ONE question at a time. Wait for my answer before the next one.
- Keep questions short and simple. Give 2 or 3 example answers with each question, so I can
  just pick one or adjust it.
- If my answer is vague (for example "tell me if sales drop"), ask me for a number
  (for example "drop by more than how many percent?").
- About 12 questions in total. Do not ask about anything the data cannot show.

Cover these topics, in this order:
1. My name, role, and which regions, markets or channels I am responsible for.
2. When and how I read the digest (for example Monday morning on my phone, in 2 minutes).
3. The decisions I make every week.
4. The 3 to 5 numbers I watch, and what I compare each with (last week, target).
5. For each number, exactly when it should be flagged (a threshold).
6. When something moves, how deep the agent should dig (region, market, channel, customer, product).
7. Normal patterns in my business that should NOT be treated as problems.
8. What a good reason looks like to me, and what a useless one looks like.
9. The actions I want: who usually acts (roles), and how fast.
10. How I want money shown, and whether I want a "decision needed" line.
11. How long the digest should be, and the writing style I like.
12. Anything I never want to see in the digest.

When the interview is done, write my context file in Markdown, using exactly this structure:

# Weekly digest brief: <name>, <role>, AtliQ Hardware

## Who I am and how I read this
## The numbers I watch
(a table: Metric | Compare with | Flag it when)
## Money first
## How to find the real cause
## Only real causes
## Known patterns: do not treat these as problems
## What a good reason looks like
(2 good examples and 2 bad examples, with made-up numbers)
## Key insights: new facts only
## Actions I want
## Decision needed
## How to write it
## Style example (made-up numbers, never copy them)

Rules for the file:
- Use my own words and numbers wherever possible.
- Every flag rule must have a number.
- Examples must use made-up numbers and be labelled as made up.
- Plain simple English. No em dashes.
- Then show me the file in one code block, and ask me if I want to change anything.
