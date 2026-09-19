# Contributing

Start with a concrete behavior change or reproducible defect. Explain the expected outcome before changing the execution engine.

Use a small branch for one coherent change. Include a regression test, and update the execution contract or operator documentation when behavior changes. Do not change a published workflow version in place.

```bash
python scripts/check.py
python scripts/browser_smoke.py
```

PostgreSQL changes also need the optional tests with `TEST_DATABASE_URL` pointing to a disposable database. The fixture creates an isolated schema, but the account needs schema creation privileges. Never point tests at customer data.

Use names that communicate intent. A comment should explain a non-obvious constraint, failure window or tradeoff. Prefer a clearer function to a comment narrating each line. Keep documentation close to behavior and avoid unverified performance or security claims.

Do not submit private keys, `.env`, real customer data, generated databases or paid-provider recordings. Fixtures should be synthetic and explicitly labeled.

