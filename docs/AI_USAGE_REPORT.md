# AI Usage Report

I used three AI tools while building this project:

- **Claude Code**: planning, code review, debugging, and first drafts of the documentation.
- **Codex CLI**: most of the code was written with it, from task descriptions I prepared.
- **Claude Design**: the visual design of the web interface.

I built the project in stages: ingestion, retrieval, indexing, the agent, API and UI, evaluation, deployment. For each
stage I first wrote down what had to be built and how it would be checked, then had the AI write the code. After that
I ran the tests, checked the results, and only then merged the change into the repository.

AI made debugging against real APIs much faster than doing it alone. The generator for the synthetic company corpus was
also written with AI help.

**Where it got things wrong:** some code had bugs that only tests or real runs caught:
- MinHash was far too slow;
- bulk ingestion ignored document ids;
- the verifier rejected correct answers because the NLI model misjudged long texts.

The first version of the evaluation questions was too templated, so I rewrote them in natural language.

**What I decided myself:**
- **Infrastructure:** everything had to run on free tiers.
- **Hosting:** Hugging Face Spaces and Google Cloud Run both turned out to need payment, so I chose Render. That meant
  building a lite mode that fits in 512 MB, without the reranker and the NLI model.
- **Evaluation:** I compared the agent with plain RAG on the same model, so the difference reflects the agent and not
  the model.
- **UI:** I picked the final version of the interface.
- **Approval:** every stage went in only after I approved it.
