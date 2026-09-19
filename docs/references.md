# References

These sources informed implementation decisions. They are references, not certifications of the repository.

| Source | Application |
| :--- | :--- |
| [PostgreSQL SELECT locking clauses](https://www.postgresql.org/docs/current/sql-select.html) | Queue-style row selection with `SKIP LOCKED` |
| [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) | Short transaction boundaries and per-operation sessions |
| [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) | Destination allowlists, redirect policy, address validation and network defense |
| [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/) | Authentication dependencies and request handling |
| [OpenAI API reference](https://developers.openai.com/api/reference/) | Provider adapter contract |
| [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages) | Messages request/response translation |
| [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) | JSON response configuration and local validation |

Provider contracts evolve. Confirm a configured model's current capabilities before enabling it in a deployment. Contract fixtures do not validate account access, billing or live model availability.
